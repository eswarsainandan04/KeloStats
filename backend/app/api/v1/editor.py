from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.auth import get_current_user_id
from app.services.presentations import (
    upload_slide_content,
)

router = APIRouter(tags=["Workspace Editor"])


# ==============================================================================
# Pydantic Request Models
# ==============================================================================

class SlideToolsUpdateRequest(BaseModel):
    user_id: Optional[str] = None
    project_id: str
    slide_number: int
    svg_code: Optional[str] = None
    slide_code: Optional[str] = None
    action: Optional[str] = "update_slide"


# ==============================================================================
# Editor Endpoints
# ==============================================================================

'''
@router.get("/workspace/editor/download", summary="Compile slides to editable PPTX and download")
def download_presentation_endpoint(
    project_id: str = Query(..., description="Project ID"),
    user_id: Optional[str] = Query(None, description="User ID"),
    authenticated_user_id: str = Depends(get_current_user_id),
):
    """
    1. Loads all slides from storage under workspace/{user_id}/{project_id}/slides/.
    2. Compiles slides into PowerPoint (.pptx).
    3. Saves presentation.pptx to storage under workspace/{user_id}/{project_id}/presentation.pptx.
    4. Streams presentation.pptx as a direct file download.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id
    if not effective_user_id or not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id and project_id are required."
        )

    uid = str(effective_user_id).strip()
    pid = str(project_id).strip()

    try:
        pptx_bytes = compile_and_save_pptx(user_id=uid, project_id=pid)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(val_err)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PPTX: {str(exc)}"
        )

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": 'attachment; filename="presentation.pptx"'}
    )
'''


@router.post("/workspace/editor/tools", summary="Update slide SVG code from frontend DesigningTools")
def update_slide_tools_endpoint(
    payload: SlideToolsUpdateRequest,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Endpoint for frontend DesigningTools:
    Updates the active slide's SVG design and code in storage and keeps manifest.json synchronized.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or payload.user_id
    slide_content = (payload.svg_code or payload.slide_code or "").strip()
    if not effective_user_id or not payload.project_id or not payload.slide_number or not slide_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id, project_id, slide_number, and svg_code are required."
        )

    uid = str(effective_user_id).strip()
    pid = payload.project_id.strip()

    try:
        upload_slide_content(
            user_id=uid,
            project_id=pid,
            slide_number=payload.slide_number,
            slide_content=slide_content,
        )
        print(f"[+] [/api/workspace/editor/tools] Slide {payload.slide_number} design updated for project {pid}")

        return {
            "status": "success",
            "message": f"Successfully updated slide {payload.slide_number} design in project {pid}",
            "slide_number": payload.slide_number,
            "svg_code": slide_content,
            "slide_code": slide_content,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist slide design changes: {str(exc)}"
        )
