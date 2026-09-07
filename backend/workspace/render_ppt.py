import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import boto3
from botocore.config import Config

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
backend_root = current_dir.parent
if (backend_root / ".env").exists():
    load_dotenv(dotenv_path=backend_root / ".env")
else:
    load_dotenv()

router = APIRouter(prefix="/api/workspace/render", tags=["Workspace Render PPT"])


def get_s3_client():
    """Returns an authenticated S3 client for Supabase Storage."""
    endpoint = os.getenv("SUPABASE_S3_ENDPOINT")
    access_key = os.getenv("SUPABASE_S3_ACCESS_KEY_ID")
    secret_key = os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY")
    region = os.getenv("SUPABASE_S3_REGION") or "us-east-1"

    if not endpoint or not access_key or not secret_key:
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


# ==============================================================================
# HTML Slide Processing Helpers
# ==============================================================================

def extract_slide_number(filename_or_key: str) -> int:
    """Extracts integer slide number from key or filename (e.g. 'slide_02.html' -> 2)."""
    match = re.search(r"slide_0*(\d+)", filename_or_key, re.IGNORECASE)
    return int(match.group(1)) if match else 999


def extract_slide_title(html_str: str, default_title: str) -> str:
    """Extracts clean slide title from <title> or <h1> tag in HTML."""
    if not html_str:
        return default_title

    # 1. Try <title>
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_str, re.IGNORECASE | re.DOTALL)
    if title_match:
        t = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
        # Remove common prefixes like 'Slide 02 - '
        t = re.sub(r"^Slide\s*\d+\s*[-–:]\s*", "", t, flags=re.IGNORECASE)
        if t:
            return t

    # 2. Try first <h1>
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_str, re.IGNORECASE | re.DOTALL)
    if h1_match:
        t = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
        if t:
            return t

    return default_title


def prepare_embeddable_html(raw_html: str) -> str:
    """
    Transforms a standalone HTML slide into a safe embeddable markup string
    for React dangerouslySetInnerHTML inside UI editor canvas and thumbnail strips.

    1. Extracts <style> blocks and scopes out global body/html rules so the Next.js
       dashboard UI and layout are never contaminated.
    2. Extracts <body> content (or slide container).
    3. Retains full CSS container-queries and relative typography.
    """
    if not raw_html:
        return ""

    # Extract all <style> blocks
    style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", raw_html, re.DOTALL | re.IGNORECASE)
    combined_css = "\n".join(style_blocks)

    # Remove global body / html rules (e.g. min-height: 100vh, background: #0f172a, margin, padding)
    combined_css = re.sub(r"(?:^|[\r\n\}])\s*body\s*\{[^}]*\}", "", combined_css)
    combined_css = re.sub(r"(?:^|[\r\n\}])\s*html\s*\{[^}]*\}", "", combined_css)

    # Scope universal selector '*' to slide container only
    combined_css = re.sub(
        r"(?:^|[\r\n\}])\s*\*\s*\{([^}]*)\}",
        r".slide-canvas, .slide-canvas * { \1 }",
        combined_css,
    )

    # Extract body content
    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.DOTALL | re.IGNORECASE)
    content = body_match.group(1).strip() if body_match else raw_html.strip()

    # Ensure all <script> tags from raw_html are preserved in embeddable output
    script_tags = re.findall(r"<script[\s\S]*?</script>", raw_html, re.IGNORECASE)
    for s_tag in script_tags:
        if s_tag not in content:
            content += f"\n{s_tag}"

    # If style tags exist, prepend the scoped styles
    if combined_css.strip():
        return f"<style>\n{combined_css}\n</style>\n{content}"
    return content


# ==============================================================================
# S3 Slide Loader: Loads HTML slides from Supabase S3
# Path: workspace/{user_id}/{project_id}/slides/
# ==============================================================================

def load_slides_from_s3(user_id: str, project_id: str) -> List[Dict[str, Any]]:
    """
    Loads all slides from Supabase S3 under:
    workspace/{user_id}/{project_id}/slides/
    ordered according to workspace/{user_id}/{project_id}/manifest.json.

    Returns sorted list of slide objects with raw HTML, embeddable rendered_html,
    and UUID filename.
    """
    from workspace.manifest import load_manifest

    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()
    slides: List[Dict[str, Any]] = []

    if s3_client and user_id and project_id:
        manifest = load_manifest(user_id=user_id, project_id=project_id, s3_client=s3_client)
        if manifest:
            for item in manifest:
                filename = item.get("filename")
                s_num = int(item.get("count", 0))
                if not filename:
                    continue
                key = f"workspace/{user_id}/{project_id}/slides/{filename}"
                try:
                    obj = s3_client.get_object(Bucket=bucket_name, Key=key)
                    raw_html = obj["Body"].read().decode("utf-8")
                    slide_name = extract_slide_title(raw_html, f"Slide {s_num}")
                    rendered_html = prepare_embeddable_html(raw_html)

                    slides.append({
                        "slide_number": s_num,
                        "filename": filename,
                        "name": slide_name,
                        "s3_key": key,
                        "raw_html": raw_html,
                        "rendered_html": rendered_html,
                    })
                except Exception as err:
                    print(f"[-] Error reading S3 HTML slide {key}: {err}")

            if slides:
                return slides

    # ==========================================================================
    # Local Practice Fallback (for local development and initial testing)
    # ==========================================================================
    practice_dir = backend_root.parent / "practice"
    practice_slides_candidates = [
        practice_dir,
        practice_dir / "slides",
    ]

    local_html_files: List[Path] = []
    for candidate_dir in practice_slides_candidates:
        if candidate_dir.exists():
            local_html_files.extend(list(candidate_dir.glob("slide_*.html")))

    if local_html_files:
        local_by_num: Dict[int, Path] = {}
        for p in local_html_files:
            s_num = extract_slide_number(p.name)
            if s_num == 999:
                continue
            if s_num not in local_by_num:
                local_by_num[s_num] = p
            elif re.search(r"slide_\d{2,}\.html", p.name, re.IGNORECASE):
                local_by_num[s_num] = p

        for s_num in sorted(local_by_num.keys()):
            p = local_by_num[s_num]
            try:
                raw_html = p.read_text(encoding="utf-8")
                slide_name = extract_slide_title(raw_html, f"Slide {s_num}")
                rendered_html = prepare_embeddable_html(raw_html)

                slides.append({
                    "slide_number": s_num,
                    "name": slide_name,
                    "s3_key": f"local/{p.name}",
                    "raw_html": raw_html,
                    "rendered_html": rendered_html,
                })
            except Exception as e:
                print(f"[-] Error reading local HTML fallback {p}: {e}")

    return slides


# ==============================================================================
# API Endpoints for UI Presentation Editor
# ==============================================================================

@router.get("/slides", summary="Load HTML slides from Supabase S3 for UI Presentation Editor")
def get_rendered_slides(
    user_id: str = Query(..., description="User ID"),
    project_id: str = Query(..., description="Project ID"),
):
    """
    1. Scans and loads all slide_*.html files from Supabase S3 under:
       path: workspace/{user_id}/{project_id}/slides/
    2. Processes and scopes each HTML slide for high-fidelity canvas and thumbnail rendering.
    3. Returns full slide objects to the frontend UI editor.
    """
    if not user_id or not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id and project_id are required query parameters.",
        )

    slides = load_slides_from_s3(user_id=user_id, project_id=project_id)

    return {
        "status": "success",
        "user_id": user_id,
        "project_id": project_id,
        "total_slides": len(slides),
        "slides": slides,
    }


@router.get("/preview/{slide_number}", summary="Get standalone full HTML page preview of a single slide")
def get_slide_html_preview(
    slide_number: int,
    user_id: str = Query(..., description="User ID"),
    project_id: str = Query(..., description="Project ID"),
):
    """Returns standalone HTML for an individual slide (ideal for iframes or direct browser tab preview)."""
    slides = load_slides_from_s3(user_id=user_id, project_id=project_id)
    matching = [s for s in slides if s["slide_number"] == slide_number]

    if not matching:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slide {slide_number} not found for project {project_id}.",
        )

    target_slide = matching[0]
    return HTMLResponse(content=target_slide["raw_html"], status_code=200)


class UploadSlideRequest(BaseModel):
    user_id: str
    project_id: str
    slide_number: Optional[int] = None
    filename: Optional[str] = None
    html_content: str
    name: Optional[str] = None


@router.post("/upload_slide", summary="Save or update an HTML slide in Supabase S3")
def upload_slide_to_s3(payload: UploadSlideRequest):
    """
    Uploads an HTML slide directly to Supabase S3 under:
    workspace/{user_id}/{project_id}/slides/{filename}
    tracked by manifest.json.
    """
    from workspace.manifest import get_slide_filename_by_count, add_slide_to_manifest
    import uuid

    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()
    if not s3_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase S3 client is not configured or unavailable.",
        )

    filename = payload.filename
    s_num = payload.slide_number or 1
    if not filename:
        filename = get_slide_filename_by_count(payload.user_id, payload.project_id, s_num, s3_client=s3_client)

    if not filename:
        filename = f"{uuid.uuid4()}.html"
        add_slide_to_manifest(
            user_id=payload.user_id,
            project_id=payload.project_id,
            after_count=s_num - 1,
            new_filename=filename,
            s3_client=s3_client
        )

    s3_key = f"workspace/{payload.user_id}/{payload.project_id}/slides/{filename}"
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=payload.html_content.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
        )
        return {
            "status": "success",
            "message": f"Successfully saved slide to S3: {s3_key}",
            "s3_key": s3_key,
            "filename": filename,
            "slide_number": s_num,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload slide to S3: {str(exc)}",
        )
