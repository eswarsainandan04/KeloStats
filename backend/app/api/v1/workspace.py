from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.auth import get_current_user_id
from app.services.presentations.manager import (
    create_workspace,
    delete_workspace,
    get_workspace,
    list_user_workspaces,
    update_workspace_source,
    update_workspace_request_mode,
)

router = APIRouter(prefix="/workspace", tags=["Workspace Projects"])


# ==============================================================================
# Pydantic Request Models
# ==============================================================================

class CreateWorkspacePayload(BaseModel):
    project_name: str
    user_id: Optional[str] = None
    database_id: Optional[str] = None
    collection_id: Optional[str] = None
    source: Optional[str] = None
    template_id: str


class UpdateWorkspaceSourcePayload(BaseModel):
    project_id: str
    user_id: Optional[str] = None
    source: str  # 'database' | 'documents'
    database_id: Optional[str] = None
    collection_id: Optional[str] = None


class UpdateWorkspaceRequestModePayload(BaseModel):
    project_id: str
    user_id: Optional[str] = None
    request_mode: str


class DeleteWorkspacePayload(BaseModel):
    project_id: Optional[str] = None
    user_id: Optional[str] = None


# ==============================================================================
# Endpoints
# ==============================================================================

@router.post("/create", summary="Create workspace project, initialize storage folder, and copy template files")
def create_workspace_session(
    payload: CreateWorkspacePayload,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Creates a new workspace presentation project:
    1. Validates inputs and resolves source mode.
    2. Inserts workspace DB record.
    3. Creates storage folder and copies template files.
    4. Initializes manifest.json.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or payload.user_id
    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id could not be resolved from authenticated session."
        )

    try:
        result = create_workspace(
            project_name=payload.project_name,
            user_id=str(effective_user_id).strip(),
            template_id=payload.template_id,
            database_id=payload.database_id,
            collection_id=payload.collection_id,
            source=payload.source,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workspace project: {str(exc)}"
        )


@router.post("/update_source", summary="Update workspace project source mode")
def update_workspace_source_endpoint(
    payload: UpdateWorkspaceSourcePayload,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Updates the 'source' column ('database', 'documents', 'auto') for a project workspace.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or payload.user_id
    try:
        result = update_workspace_source(
            project_id=payload.project_id,
            source=payload.source,
            database_id=payload.database_id,
            collection_id=payload.collection_id,
            user_id=effective_user_id,
        )
        return result
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(k_err).strip("'")
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update workspace source: {str(exc)}"
        )


@router.post("/update_request_mode", summary="Update workspace request mode ('ask' or 'agent')")
def update_workspace_request_mode_endpoint(
    payload: UpdateWorkspaceRequestModePayload,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Updates the workspace request mode ('ask' or 'agent') in the workspace table.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or payload.user_id
    try:
        result = update_workspace_request_mode(
            project_id=payload.project_id,
            request_mode=payload.request_mode,
            user_id=effective_user_id,
        )
        return result
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(k_err).strip("'")
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update workspace mode: {str(exc)}"
        )


@router.get("/list", summary="Fetch all workspace projects for a user from storage and DB")
def list_workspaces(
    user_id: Optional[str] = Query(None, description="User ID"),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Fetches all workspace projects for the authenticated user, combining DB records
    with slide counts and presentation files from storage.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id
    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id query parameter is required."
        )

    clean_user_id = str(effective_user_id).strip()
    workspaces = list_user_workspaces(user_id=clean_user_id)

    return {
        "status": "success",
        "user_id": clean_user_id,
        "total_workspaces": len(workspaces),
        "workspaces": workspaces,
    }


@router.post("/delete", summary="Delete a workspace project")
def delete_workspace_endpoint(
    payload: Optional[DeleteWorkspacePayload] = None,
    project_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Deletes a project workspace:
    1. Removes all files from storage under workspace/{user_id}/{project_id}/
    2. Deletes dependent chat_messages records.
    3. Deletes workspace record from database.
    Guarded by verified JWT authentication.
    """
    target_project_id = (payload.project_id if payload and payload.project_id else project_id or "").strip()
    effective_user_id = authenticated_user_id or (payload.user_id if payload and payload.user_id else user_id or "").strip()

    if not target_project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id is required."
        )

    try:
        result = delete_workspace(
            project_id=target_project_id,
            user_id=effective_user_id,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete project: {str(exc)}"
        )
