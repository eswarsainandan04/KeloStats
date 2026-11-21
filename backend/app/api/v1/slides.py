from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.auth import get_current_user_id
from app.services.presentations import (
    create_blank_slide,
    delete_slide,
    load_slides_from_storage,
    upload_slide_content,
)

router = APIRouter(tags=["Workspace Slides"])


# ==============================================================================
# Pydantic Request Models
# ==============================================================================

class NewSlideRequest(BaseModel):
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    after_slide: Optional[int] = None


class DeleteSlideRequest(BaseModel):
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    slide_number: Optional[int] = None


class UploadSlideRequest(BaseModel):
    user_id: Optional[str] = None
    project_id: str
    slide_number: Optional[int] = None
    filename: Optional[str] = None
    svg_code: Optional[str] = None
    slide_content: Optional[str] = None
    content: Optional[str] = None
    name: Optional[str] = None


# ==============================================================================
# Slide Management Endpoints
# ==============================================================================

@router.post("/workspace/slides/new_slide", summary="Create and insert a pure blank slide")
def create_new_blank_slide_endpoint(
    payload: Optional[NewSlideRequest] = None,
    user_id: Optional[str] = Query(None, description="User ID"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    after_slide: Optional[int] = Query(None, description="Insert after this slide number"),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Dynamically generates and inserts a new blank slide into storage:
    1. Tracks slide in manifest.json with UUID filename.
    2. Inserts after after_slide position (if specified).
    3. Saves slide to storage.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or (payload.user_id if payload else None) or user_id or ""
    effective_project_id = (payload.project_id if payload else None) or project_id or ""
    insert_after = payload.after_slide if (payload and payload.after_slide is not None) else after_slide

    uid = str(effective_user_id).strip()
    pid = str(effective_project_id).strip()

    if not uid or not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id and project_id are required."
        )

    try:
        result = create_blank_slide(
            user_id=uid,
            project_id=pid,
            after_slide=insert_after,
        )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create new slide: {str(exc)}"
        )


@router.post("/workspace/slides/delete_slide", summary="Delete a slide from presentation")
def delete_slide_endpoint(
    payload: Optional[DeleteSlideRequest] = None,
    user_id: Optional[str] = Query(None, description="User ID"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    slide_number: Optional[int] = Query(None, description="Slide number to delete"),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Deletes a slide from storage and updates manifest.json:
    1. Validates that at least 1 slide remains.
    2. Deletes the slide from storage.
    3. Re-indexes remaining slides in manifest.json.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or (payload.user_id if payload else None) or user_id or ""
    effective_project_id = (payload.project_id if payload else None) or project_id or ""
    s_num = payload.slide_number if (payload and payload.slide_number is not None) else slide_number

    uid = str(effective_user_id).strip()
    pid = str(effective_project_id).strip()

    if not uid or not pid or s_num is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id, project_id, and slide_number are required."
        )

    try:
        result = delete_slide(
            user_id=uid,
            project_id=pid,
            slide_number=s_num,
        )
        return result
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(k_err).strip("'")
        )
    except ValueError as v_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(v_err)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete slide: {str(exc)}"
        )


@router.get("/workspace/slides/load", summary="Load slides for UI Presentation Editor")
def get_rendered_slides(
    project_id: str = Query(..., description="Project ID"),
    user_id: Optional[str] = Query(None, description="User ID"),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Loads all slides from storage under workspace/{user_id}/{project_id}/slides/
    ordered by manifest.json, with raw and embeddable SVG slide markup.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id
    if not effective_user_id or not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id and project_id are required parameters."
        )

    uid = str(effective_user_id).strip()
    pid = str(project_id).strip()

    slides = load_slides_from_storage(user_id=uid, project_id=pid)

    return {
        "status": "success",
        "user_id": uid,
        "project_id": pid,
        "total_slides": len(slides),
        "slides": slides,
    }


@router.get("/workspace/slides/preview/{slide_number}", summary="Get standalone preview of a single slide")
def get_slide_preview(
    slide_number: int,
    project_id: str = Query(..., description="Project ID"),
    user_id: Optional[str] = Query(None, description="User ID"),
    authenticated_user_id: str = Depends(get_current_user_id),
):
    """
    Returns standalone markup for an individual slide (ideal for iframes or direct browser tab preview).
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id
    if not effective_user_id or not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id and project_id are required parameters."
        )

    uid = str(effective_user_id).strip()
    pid = str(project_id).strip()

    slides = load_slides_from_storage(user_id=uid, project_id=pid)
    matching = [s for s in slides if s["slide_number"] == slide_number]

    if not matching:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slide {slide_number} not found for project {pid}.",
        )

    content_str = matching[0].get("raw_svg") or matching[0].get("raw_code") or ""
    return Response(content=content_str, media_type="image/svg+xml", status_code=200)


@router.post("/workspace/slides/upload_slide", summary="Save or update a slide directly in storage")
def upload_slide_endpoint(
    payload: UploadSlideRequest,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Uploads or updates a slide directly in storage under
    workspace/{user_id}/{project_id}/slides/{filename}, tracked by manifest.json.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or payload.user_id
    slide_content = (payload.svg_code or payload.slide_content or payload.content or "").strip()
    if not effective_user_id or not payload.project_id or not slide_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id, project_id, and svg_code (or slide_content) are required."
        )

    try:
        result = upload_slide_content(
            user_id=str(effective_user_id).strip(),
            project_id=payload.project_id.strip(),
            slide_content=slide_content,
            slide_number=payload.slide_number,
            filename=payload.filename,
        )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload slide: {str(exc)}"
        )
