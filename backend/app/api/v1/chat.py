import re
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core.auth import get_current_user_id
from app.services.agents.orchestrator import run_orchestrator
from app.services.messages import get_chat_history, save_chat_message

router = APIRouter(tags=["Workflow & Workspace Chat"])


# ==============================================================================
# Pydantic Request Models
# ==============================================================================

class QueryWorkflowRequest(BaseModel):
    user_query: str
    database_id: Optional[str] = None
    db_id: Optional[str] = None
    collection_id: Optional[str] = None
    source: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    slide_number: Optional[Union[int, str]] = 1
    slide_filename: Optional[str] = None


class SaveChatMessageRequest(BaseModel):
    project_id: str
    role: str  # 'User' or 'AI'
    message: str


# ==============================================================================
# Endpoints
# ==============================================================================

@router.post("/workflow/query", summary="Run LangGraph workflow for user query, database, and project")
def workflow_query_endpoint(
    payload: QueryWorkflowRequest,
    request: Request,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    POST /api/workflow/query
    Guarded by verified JWT Authentication via Depends(get_current_user_id).
    Runs multi-agent LangGraph workflow.
    """
    target_db_id = payload.database_id or payload.db_id
    target_collection_id = payload.collection_id
    target_source = payload.source
    target_project_id = payload.project_id
    target_user_id = authenticated_user_id or getattr(request.state, "user_id", None) or payload.user_id

    # Resolve target slide number from slide_filename (e.g. 'slide_04.svg') or slide_number
    target_slide_number = 1
    if payload.slide_filename:
        m = re.search(r"slide_0*(\d+)", payload.slide_filename, re.IGNORECASE)
        if m:
            target_slide_number = int(m.group(1))
    elif payload.slide_number is not None:
        try:
            target_slide_number = int(payload.slide_number)
        except (ValueError, TypeError):
            m = re.search(r"\d+", str(payload.slide_number))
            target_slide_number = int(m.group(0)) if m else 1

    if target_slide_number < 1:
        target_slide_number = 1

    if not payload.user_query or not payload.user_query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required field 'user_query' in request payload."
        )

    try:
        graph_result = run_orchestrator(
            user_query=payload.user_query,
            database_id=target_db_id,
            collection_id=target_collection_id,
            project_id=target_project_id,
            user_id=target_user_id,
            slide_number=target_slide_number,
            source=target_source
        )

        slide_num_result = graph_result.get("slide_number") or target_slide_number
        final_text = graph_result.get("final_output") or "Sorry, I cant help you rght now"

        return {
            "status": graph_result.get("status") or "COMPLETED",
            "intent": graph_result.get("classification_intent"),
            "decision": graph_result.get("decision"),
            "original_query": graph_result.get("original_user_query") or payload.user_query,
            "reformulated_query": graph_result.get("reformulated_query"),
            "is_reformulated": graph_result.get("is_reformulated") or False,
            "sql_required": graph_result.get("sql_required"),
            "verification_status": graph_result.get("verification_status"),
            "verification_reason": graph_result.get("verification_reason"),
            "generated_sql": graph_result.get("generated_sql"),
            "retrieved_rows_count": graph_result.get("retrieved_rows_count") or 0,
            "output": final_text,
            "slide_svg": graph_result.get("generated_slide_svg"),
            "slide_number": slide_num_result,
            "slide_filename": f"slide_{slide_num_result:02d}.svg",
            "database_id": target_db_id,
            "project_id": target_project_id
        }
    except Exception as exc:
        print(f"[!] [workflow_query_endpoint] Caught error: {exc}")
        fallback_msg = "Sorry, I cant help you rght now"
        if target_project_id:
            try:
                save_chat_message(project_id=target_project_id, role="AI", message=fallback_msg)
            except Exception as save_err:
                print(f"[!] Failed to save fallback message: {save_err}")
        return {
            "status": "FAILED",
            "intent": None,
            "decision": None,
            "sql_required": None,
            "verification_status": None,
            "verification_reason": None,
            "generated_sql": None,
            "retrieved_rows_count": 0,
            "output": fallback_msg,
            "slide_svg": None,
            "slide_number": target_slide_number,
            "slide_filename": f"slide_{target_slide_number:02d}.svg",
            "database_id": target_db_id,
            "project_id": target_project_id
        }


@router.get("/workspace/chat/{project_id}", summary="Get chat messages history for a project")
def get_chat_messages_endpoint(
    project_id: str,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Returns chronological chat history for a workspace project.
    Guarded by verified JWT Authentication via Depends(get_current_user_id).
    """
    if not project_id or not project_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id is required."
        )

    clean_project_id = project_id.strip()
    messages = get_chat_history(project_id=clean_project_id, user_id=authenticated_user_id)
    return {
        "status": "success",
        "project_id": clean_project_id,
        "count": len(messages),
        "messages": messages
    }


@router.post("/workspace/chat", summary="Save a single chat message to history")
def save_chat_message_endpoint(
    payload: SaveChatMessageRequest,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Directly persists a chat message in chat history.
    Guarded by verified JWT Authentication.
    """
    if not payload.project_id or not payload.project_id.strip():
        raise HTTPException(status_code=400, detail="project_id is required.")
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message content is required.")

    msg_id = save_chat_message(
        project_id=payload.project_id.strip(),
        role=payload.role.strip(),
        message=payload.message.strip(),
    )
    if not msg_id:
        raise HTTPException(status_code=400, detail="Failed to persist message (invalid workspace project_id).")

    return {
        "status": "success",
        "message_id": msg_id,
        "project_id": payload.project_id.strip()
    }