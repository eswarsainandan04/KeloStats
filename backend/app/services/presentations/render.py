import io
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.storage import get_storage
from .manifest import (
    add_slide_to_manifest,
    delete_slide_from_manifest,
    get_slide_filename_by_count,
    load_manifest,
    set_slide_blank_status,
)


# ==============================================================================
# Slide Loading & Rendering via Storage Adapter
# ==============================================================================

def load_slides_from_storage(user_id: str, project_id: str) -> List[Dict[str, Any]]:
    """
    Loads all slides from storage under workspace/{user_id}/{project_id}/slides/
    ordered directly according to manifest.json.
    Returns clean, unaltered slide markup directly as-is without regex manipulations.
    """
    clean_uid = str(user_id or "").strip()
    clean_pid = str(project_id or "").strip()

    if not clean_uid or not clean_pid:
        return []

    storage = get_storage()
    manifest = load_manifest(user_id=clean_uid, project_id=clean_pid)
    slides: List[Dict[str, Any]] = []

    if manifest:
        for item in manifest:
            filename = item.get("filename")
            s_num = int(item.get("count", 0))
            if not filename:
                continue

            storage_key = f"workspace/{clean_uid}/{clean_pid}/slides/{filename}"
            if not storage.exists(storage_key):
                continue

            try:
                raw_content = storage.read_text(storage_key)
                title = item.get("title") or item.get("name") or f"Slide {s_num}"
                is_svg = storage_key.endswith(".svg")

                slides.append({
                    "slide_number": s_num,
                    "filename": filename,
                    "name": f"Slide {s_num}",
                    "title": title,
                    "storage_key": storage_key,
                    "s3_key": storage_key,
                    "content_type": "image/svg+xml" if is_svg else "text/plain",
                    "is_blank_slide": bool(item.get("is_blank_slide", False)),
                    "raw_svg": raw_content,
                })
            except Exception as read_err:
                print(f"[SlideRender] [-] Error reading slide {storage_key}: {read_err}")

    # Fallback if manifest returned empty: discover SVG/slide files in storage directly
    # SVG files take priority over other slide files
    if not slides:
        prefix = f"workspace/{clean_uid}/{clean_pid}/slides/"
        try:
            all_keys = storage.list_files(prefix=prefix)

            svg_keys = sorted([k for k in all_keys if k.endswith(".svg") and not k.endswith("/")])
            fallback_slide_keys = sorted([k for k in all_keys if not k.endswith(".svg") and not k.endswith("/")])

            # Build stem -> key dict; SVG overrides fallback files
            stem_to_key: dict = {}
            for k in fallback_slide_keys:
                stem_to_key[Path(k).stem] = k
            for k in svg_keys:
                stem_to_key[Path(k).stem] = k  # SVG wins

            slide_keys = sorted(stem_to_key.values())

            for idx, key in enumerate(slide_keys, start=1):
                raw_content = storage.read_text(key)
                filename = Path(key).name
                is_svg = key.endswith(".svg")
                title = f"Slide {idx}"

                slides.append({
                    "slide_number": idx,
                    "filename": filename,
                    "name": f"Slide {idx}",
                    "title": title,
                    "storage_key": key,
                    "s3_key": key,
                    "content_type": "image/svg+xml" if is_svg else "text/plain",
                    "is_blank_slide": False,
                    "raw_svg": raw_content,
                })
        except Exception as scan_err:
            print(f"[SlideRender] [-] Error scanning storage slides fallback: {scan_err}")

    return slides


# Backwards compatibility alias
load_slides_from_s3 = load_slides_from_storage


# ==============================================================================
# Slide Creation, Deletion & Updating Services
# ==============================================================================

def create_blank_slide(
    user_id: str,
    project_id: str,
    after_slide: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Dynamically generates and inserts a pure blank SVG slide:
    1. Adds slide entry to manifest.json with UUID.svg filename (ordering maintained).
    2. Reads and formats blank_slide.svg template.
    3. Saves SVG to storage under workspace/{user_id}/{project_id}/slides/{UUID}.svg.
    4. Returns updated slide metadata.
    """
    clean_uid = str(user_id or "").strip()
    clean_pid = str(project_id or "").strip()

    if not clean_uid or not clean_pid:
        raise ValueError("user_id and project_id are required.")

    # 1. Add slide entry to manifest with .svg extension and is_blank_slide=True
    new_svg_filename = f"{uuid.uuid4()}.svg"
    slide_filename, next_slide_num, updated_manifest = add_slide_to_manifest(
        user_id=clean_uid,
        project_id=clean_pid,
        after_count=after_slide,
        new_filename=new_svg_filename,
        is_blank_slide=True
    )

    # 2. Read SVG template
    pages_dir = Path(__file__).resolve().parent.parent / "pages"
    template_path = pages_dir / "blank_slide.svg"

    fallback_svg = f"""<svg viewBox="0 0 1920 1080" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" font-family="Arial, Helvetica, sans-serif"><rect width="1920" height="1080" fill="#FFFFFF"/></svg>"""

    if template_path.exists():
        try:
            template_text = template_path.read_text(encoding="utf-8")
            fmt_num_2d = f"{int(next_slide_num):02d}"
            fmt_num = str(next_slide_num)
            blank_svg = (
                template_text
                .replace("{next_slide_num:02d}", fmt_num_2d)
                .replace("{{next_slide_num:02d}}", fmt_num_2d)
                .replace("{next_slide_num}", fmt_num)
                .replace("{{next_slide_num}}", fmt_num)
            )
        except Exception as fmt_err:
            print(f"[SlideRender] [!] Warning formatting blank slide template: {fmt_err}")
            blank_svg = fallback_svg
    else:
        blank_svg = fallback_svg

    # 3. Save pure SVG to storage
    storage_key = f"workspace/{clean_uid}/{clean_pid}/slides/{slide_filename}"
    storage = get_storage()
    storage.create(key=storage_key, data=blank_svg.encode("utf-8"), content_type="image/svg+xml; charset=utf-8")
    print(f"[SlideRender] [+] Successfully saved new blank SVG slide to storage: {storage_key}")

    return {
        "status": "success",
        "message": f"Successfully created pure blank white slide {next_slide_num}",
        "slide_number": next_slide_num,
        "filename": slide_filename,
        "name": f"Slide {next_slide_num}",
        "storage_key": storage_key,
        "s3_key": storage_key,
        "content_type": "image/svg+xml",
        "is_blank_slide": True,
        "raw_svg": blank_svg,
        "total_slides": len(updated_manifest)
    }


def delete_slide(
    user_id: str,
    project_id: str,
    slide_number: int,
) -> Dict[str, Any]:
    """
    Deletes a slide from storage and updates manifest.json:
    1. Validates that at least 1 slide remains.
    2. Deletes the slide from storage.
    3. Re-indexes remaining slides in manifest.json.
    """
    clean_uid = str(user_id or "").strip()
    clean_pid = str(project_id or "").strip()

    if not clean_uid or not clean_pid or slide_number is None:
        raise ValueError("user_id, project_id, and slide_number are required.")

    try:
        clean_slide_num = int(slide_number)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid slide_number: {slide_number}")

    existing_slides = load_slides_from_storage(user_id=clean_uid, project_id=clean_pid)
    if not existing_slides:
        raise KeyError(f"No slides found for project {clean_pid}.")

    if len(existing_slides) <= 1:
        raise ValueError("Cannot delete the only remaining slide in the presentation.")

    target_slide = next(
        (s for s in existing_slides if str(s.get("slide_number", "")).strip() == str(clean_slide_num)),
        None
    )
    if not target_slide:
        raise KeyError(f"Slide {clean_slide_num} not found in project {clean_pid}.")

    deleted_filename, updated_manifest = delete_slide_from_manifest(
        user_id=clean_uid,
        project_id=clean_pid,
        slide_identifier=clean_slide_num
    )

    fresh_slides = load_slides_from_storage(user_id=clean_uid, project_id=clean_pid)

    return {
        "status": "success",
        "message": f"Successfully deleted slide {slide_number} ({deleted_filename}) from project {clean_pid}",
        "deleted_slide_number": slide_number,
        "deleted_filename": deleted_filename,
        "remaining_slides_count": len(fresh_slides),
        "slides": fresh_slides
    }


def upload_slide_content(
    user_id: str,
    project_id: str,
    slide_content: str = "",
    slide_number: Optional[int] = None,
    filename: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Uploads or updates a slide directly in storage, synchronized with manifest.json.
    """
    clean_uid = str(user_id or "").strip()
    clean_pid = str(project_id or "").strip()

    if not clean_uid or not clean_pid:
        raise ValueError("user_id and project_id are required.")

    s_num = slide_number or 1
    target_filename = filename
    content_str = (slide_content or kwargs.get("content") or kwargs.get("svg_code") or kwargs.get("code") or "").strip()
    is_svg = "<svg" in content_str.lower()

    if not target_filename:
        target_filename = get_slide_filename_by_count(clean_uid, clean_pid, s_num)

    if not target_filename:
        target_filename = f"{uuid.uuid4()}.svg"
        add_slide_to_manifest(
            user_id=clean_uid,
            project_id=clean_pid,
            after_count=s_num - 1,
            new_filename=target_filename
        )

    content_type = "image/svg+xml; charset=utf-8" if (is_svg or (target_filename and target_filename.endswith(".svg"))) else "text/plain; charset=utf-8"

    storage = get_storage()
    storage_key = f"workspace/{clean_uid}/{clean_pid}/slides/{target_filename}"
    storage.create(key=storage_key, data=content_str.encode("utf-8"), content_type=content_type)
    print(f"[SlideRender] [+] Successfully uploaded slide: {storage_key}")

    # Slide now has content; mark is_blank_slide = False in manifest
    set_slide_blank_status(user_id=clean_uid, project_id=clean_pid, slide_number=s_num, is_blank_slide=False)

    return {
        "status": "success",
        "message": f"Successfully saved slide to storage: {storage_key}",
        "storage_key": storage_key,
        "s3_key": storage_key,
        "filename": target_filename,
        "slide_number": s_num
    }
