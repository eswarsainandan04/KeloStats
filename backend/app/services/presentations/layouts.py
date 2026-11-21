import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import text

from app.core.config import settings
from app.core.storage import get_storage
from app.services.connectors import app_db_engine as engine


# ==============================================================================
# Domain Services for Presentation Templates & Layouts
# ==============================================================================

def get_all_templates() -> List[Dict[str, Any]]:
    """
    Queries public.templates table and returns all available presentation templates.
    """
    try:
        with engine.connect() as conn:
            query = text("SELECT * FROM public.templates ORDER BY template_id ASC;")
            result = conn.execute(query).fetchall()

            templates_list = []
            for row in result:
                mapping = row._mapping if hasattr(row, "_mapping") else dict(row)
                template_id = str(mapping.get("template_id", "")).strip()
                templates_list.append({
                    "template_id": template_id,
                    "template_name": str(mapping.get("template_name", "")).strip(),
                    "category": str(mapping.get("category", "") or "general").strip(),
                    "preview_url": f"/api/templates/{template_id}/preview",
                })
            return templates_list
    except Exception as exc:
        print(f"[-] [LayoutsService] Error fetching templates from database: {exc}")
        return []


def get_template_preview_image(template_id: str) -> Tuple[bytes, str]:
    """
    Retrieves the binary preview image for a template.
    Checks templates/{template_id}/preview.png first.
    Generates a high-fidelity SVG fallback if no raster image exists.
    """
    clean_tid = str(template_id or "").strip()
    storage = get_storage()

    preview_key = f"templates/{clean_tid}/preview.png"
    if storage.exists(preview_key):
        try:
            data = storage.read(preview_key)
            return data, "image/png"
        except Exception as read_err:
            print(f"[!] Notice reading raster preview for template {clean_tid}: {read_err}")

    # High-fidelity SVG card fallback
    svg_fallback = f"""<svg viewBox="0 0 800 450" width="800" height="450" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e293b"/>
      <stop offset="100%" stop-color="#0f172a"/>
    </linearGradient>
  </defs>
  <rect width="800" height="450" fill="url(#grad)"/>
  <rect x="60" y="60" width="680" height="330" rx="16" fill="#ffffff" stroke="#e2e8f0" stroke-width="2"/>
  <circle cx="120" cy="120" r="28" fill="#FF5148" opacity="0.15"/>
  <path d="M110 110 L130 110 L130 130 L110 130 Z" fill="#FF5148"/>
  <text x="120" y="220" font-family="sans-serif" font-size="28" font-weight="bold" fill="#1a202c">Executive Presentation</text>
  <text x="120" y="260" font-family="sans-serif" font-size="16" fill="#718096">Template ID: {clean_tid}</text>
  <rect x="120" y="290" width="120" height="8" rx="4" fill="#FF5148"/>
</svg>"""
    return svg_fallback.encode("utf-8"), "image/svg+xml"


def get_template_slides_data(template_id: str) -> Dict[str, Any]:
    """
    Loads all slide SVGs for a given template from storage
    (templates/{template_id}/slides/).
    Returns slide content directly without modifications.
    """
    clean_tid = str(template_id or "").strip()
    storage = get_storage()
    prefix = f"templates/{clean_tid}/slides/"

    slides: List[Dict[str, Any]] = []

    try:
        found_keys = storage.list_files(prefix=prefix)

        svg_keys = sorted([k for k in found_keys if k.endswith(".svg") and not k.endswith("/")])
        other_keys = sorted([k for k in found_keys if not k.endswith(".svg") and not k.endswith("/")])

        # Build stem -> key mapping: SVG overrides fallback files
        stem_to_key: Dict[str, str] = {}
        for k in other_keys:
            stem_to_key[Path(k).stem] = k
        for k in svg_keys:
            stem_to_key[Path(k).stem] = k  # SVG wins

        slide_keys = sorted(stem_to_key.values())

        for idx, key in enumerate(slide_keys, start=1):
            filename = Path(key).name
            is_svg = key.endswith(".svg")
            try:
                raw_content = storage.read_text(key, encoding="utf-8")
                slide_name = f"Slide {idx}"

                slides.append({
                    "slide_number": idx,
                    "filename": filename,
                    "name": slide_name,
                    "storage_key": key,
                    "s3_key": key,
                    "content_type": "image/svg+xml" if is_svg else "text/plain",
                    "raw_svg": raw_content,
                })
            except Exception as slide_err:
                print(f"[-] [LayoutsService] Error reading slide {key}: {slide_err}")
    except Exception as exc:
        print(f"[-] [LayoutsService] Error listing template slides from storage: {exc}")

    # Fallback to local slides directory if storage returned no slides
    if not slides:
        local_slides_dir = Path(__file__).resolve().parent.parent.parent.parent / "slides"
        if local_slides_dir.exists():
            local_svgs = sorted(local_slides_dir.glob("slide_*.svg"))
            local_other = sorted([p for p in local_slides_dir.glob("slide_*.*") if p.suffix != ".svg"])
            stem_map: Dict[str, Path] = {}
            for p in local_other:
                stem_map[p.stem] = p
            for p in local_svgs:
                stem_map[p.stem] = p  # SVG wins
            local_files = sorted(stem_map.values(), key=lambda p: p.name)

            for idx, p in enumerate(local_files, start=1):
                is_svg = p.suffix == ".svg"
                try:
                    raw_content = p.read_text(encoding="utf-8")
                    slides.append({
                        "slide_number": idx,
                        "filename": p.name,
                        "name": f"Slide {idx}",
                        "storage_key": f"local/{p.name}",
                        "s3_key": f"local/{p.name}",
                        "content_type": "image/svg+xml" if is_svg else "text/plain",
                        "raw_svg": raw_content,
                    })
                except Exception as l_err:
                    print(f"[-] [LayoutsService] Error reading local slide {p}: {l_err}")

    # Lookup template name from DB
    template_name = "Presentation Template"
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT template_name FROM public.templates WHERE template_id = :tid LIMIT 1;"),
                {"tid": clean_tid}
            ).fetchone()
            if row and row[0]:
                template_name = str(row[0])
    except Exception:
        pass

    return {
        "status": "success",
        "template_id": clean_tid,
        "template_name": template_name,
        "slide_count": len(slides),
        "slides": slides,
    }
