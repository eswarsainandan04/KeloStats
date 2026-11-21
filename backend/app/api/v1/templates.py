from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Response, status

from app.services.presentations.layouts import (
    get_all_templates,
    get_template_preview_image,
    get_template_slides_data,
)

router = APIRouter(tags=["Presentation Templates"])


# ==============================================================================
# Presentation Templates Endpoints
# ==============================================================================

@router.get("/templates", summary="Get presentation templates from database")
@router.get("/get/templates", summary="Get presentation templates alias")
def get_templates_endpoint() -> Dict[str, Any]:
    """
    Returns all presentation templates with preview URL.
    Whitelisted for public catalog viewing without requiring JWT login.
    """
    try:
        templates_list = get_all_templates()
        return {
            "status": "success",
            "count": len(templates_list),
            "templates": templates_list,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch templates: {str(exc)}",
        )


@router.get("/templates/{template_id}/preview", summary="Stream template preview image")
def get_template_preview_endpoint(template_id: str):
    """
    Fetches template preview image (preview.png from storage or responsive SVG fallback).
    Whitelisted for public catalog viewing.
    """
    try:
        image_bytes, content_type = get_template_preview_image(template_id)
        cache_header = "public, max-age=86400" if content_type == "image/png" else "no-cache"
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": cache_header},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch template preview: {str(exc)}",
        )


@router.get("/templates/{template_id}/slides", summary="Load all slides for a template")
def get_template_slides_endpoint(template_id: str) -> Dict[str, Any]:
    """
    Loads all slides for a template with raw and embeddable SVG slide markup.
    Whitelisted for public deck previewing.
    """
    try:
        data = get_template_slides_data(template_id)
        return data
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load template slides: {str(exc)}",
        )
