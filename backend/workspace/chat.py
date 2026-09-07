import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import create_engine, text

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
if (current_dir.parent / ".env").exists():
    load_dotenv(dotenv_path=current_dir.parent / ".env")
elif (current_dir / ".env").exists():
    load_dotenv(dotenv_path=current_dir / ".env")
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

router = APIRouter(prefix="/api/workspace/chat", tags=["Workspace Chat"])


def save_chat_message(project_id: Optional[str], role: str, message: Optional[str]) -> Optional[str]:
    """
    Persists a chat message in the chat_messages table:
    chat_messages(message_id UUID, project_id VARCHAR FK, role VARCHAR, message TEXT, created_at, updated_at)

    :param project_id: The workspace project ID
    :param role: Message sender role ('User' or 'AI')
    :param message: The text message content
    :return: Generated message_id UUID string if inserted, or None
    """
    if not project_id or not str(project_id).strip():
        return None

    cleaned_msg = str(message or "").strip()
    if not cleaned_msg:
        return None

    clean_project_id = str(project_id).strip()

    try:
        with engine.connect() as conn:
            # Check foreign key existence in workspace table before inserting
            check_sql = text("SELECT 1 FROM workspace WHERE project_id = :p_id LIMIT 1;")
            exists = conn.execute(check_sql, {"p_id": clean_project_id}).fetchone()

            if not exists:
                print(f"[!] [Chat DB] Warning: project_id '{clean_project_id}' does not exist in workspace table. Skipping chat_messages insert.")
                return None

            insert_sql = text("""
                INSERT INTO chat_messages (project_id, role, message, created_at, updated_at)
                VALUES (:project_id, :role, :message, NOW(), NOW())
                RETURNING message_id;
            """)
            result = conn.execute(insert_sql, {
                "project_id": clean_project_id,
                "role": role,
                "message": cleaned_msg
            })
            conn.commit()
            row = result.fetchone()
            msg_id = str(row[0]) if row else None
            print(f"[+] [Chat DB] Persisted {role} message to chat_messages (id: {msg_id}) for project: {clean_project_id}")
            return msg_id
    except Exception as exc:
        print(f"[-] [Chat DB] Error inserting {role} message for project '{clean_project_id}': {exc}")
        return None


def get_chat_history(project_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all chat messages for the specified project_id ordered chronologically.
    """
    if not project_id:
        return []

    try:
        with engine.connect() as conn:
            query = text("""
                SELECT message_id, project_id, role, message, created_at, updated_at
                FROM chat_messages
                WHERE project_id = :project_id
                ORDER BY created_at ASC;
            """)
            result = conn.execute(query, {"project_id": project_id}).fetchall()

            messages = []
            for row in result:
                messages.append({
                    "id": str(row.message_id),
                    "project_id": row.project_id,
                    "sender": "user" if str(row.role).lower() == "user" else "ai",
                    "role": row.role,
                    "text": row.message,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "timestamp": row.created_at.strftime("%I:%M %p") if row.created_at else None,
                })
            return messages
    except Exception as exc:
        print(f"[-] [Chat DB] Error retrieving chat history for project '{project_id}': {exc}")
        return []


@router.get("/{project_id}", summary="Get chat messages history for a project")
def get_chat_messages_endpoint(project_id: str):
    """
    Returns chronological chat history for a workspace project.
    """
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id is required."
        )

    messages = get_chat_history(project_id)
    return {
        "status": "success",
        "project_id": project_id,
        "count": len(messages),
        "messages": messages
    }
