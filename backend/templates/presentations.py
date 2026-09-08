import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import create_engine, text

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
backend_root = current_dir.parent
if (backend_root / ".env").exists():
    load_dotenv(dotenv_path=backend_root / ".env")
elif (current_dir / ".env").exists():
    load_dotenv(dotenv_path=current_dir / ".env")
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

router = APIRouter(tags=["Presentation Templates"])


def get_s3_client():
    """
    Returns an initialized S3 client for Supabase Storage.
    """
    try:
        from workspace.manage_workspace import get_s3_client as _get_client
        client = _get_client()
        if client:
            return client
    except Exception:
        pass

    import boto3
    from botocore.config import Config

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
# Helper functions for slide processing
# ==============================================================================

def extract_slide_number(filename_or_key: str) -> int:
    """Extracts integer slide number from key or filename (e.g. 'slide_02.html' -> 2)."""
    match = re.search(r"slide_0*(\d+)", filename_or_key, re.IGNORECASE)
    return int(match.group(1)) if match else 999


def extract_slide_title(html_str: str, default_title: str) -> str:
    """Extracts clean slide title from <title> or <h1> tag in HTML."""
    if not html_str:
        return default_title

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_str, re.IGNORECASE | re.DOTALL)
    if title_match:
        t = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
        t = re.sub(r"^Slide\s*\d+\s*[-–:]\s*", "", t, flags=re.IGNORECASE)
        if t:
            return t

    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_str, re.IGNORECASE | re.DOTALL)
    if h1_match:
        t = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
        if t:
            return t

    return default_title


def prepare_embeddable_html(raw_html: str) -> str:
    """
    Transforms a standalone HTML slide into a safe embeddable markup string
    for React dangerouslySetInnerHTML inside UI preview canvas.
    Scopes out global body/html rules so page layout is never contaminated.
    """
    if not raw_html:
        return ""

    style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", raw_html, re.DOTALL | re.IGNORECASE)
    combined_css = "\n".join(style_blocks)

    combined_css = re.sub(r"(?:^|[\r\n\}])\s*body\s*\{[^}]*\}", "", combined_css)
    combined_css = re.sub(r"(?:^|[\r\n\}])\s*html\s*\{[^}]*\}", "", combined_css)

    combined_css = re.sub(
        r"(?:^|[\r\n\}])\s*\*\s*\{([^}]*)\}",
        r".slide-canvas, .slide-canvas * { \1 }",
        combined_css,
    )

    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.DOTALL | re.IGNORECASE)
    content = body_match.group(1).strip() if body_match else raw_html.strip()

    script_tags = re.findall(r"<script[\s\S]*?</script>", raw_html, re.IGNORECASE)
    for s_tag in script_tags:
        if s_tag not in content:
            content += f"\n{s_tag}"

    if combined_css.strip():
        return f"<style>\n{combined_css}\n</style>\n{content}"
    return content


# ==============================================================================
# Endpoints
# ==============================================================================

@router.get("/api/get/templates", summary="Get PPT templates from public.templates")
@router.get("/api/templates", summary="Get PPT templates from public.templates")
def get_templates():
    """
    Executes:
    SELECT * FROM public.templates
    ORDER BY template_id ASC

    Returns all presentation templates with S3 preview URL.
    """
    try:
        with engine.connect() as conn:
            query = text("SELECT * FROM public.templates ORDER BY template_id ASC;")
            result = conn.execute(query).fetchall()

            templates_list = []
            for row in result:
                mapping = row._mapping if hasattr(row, "_mapping") else dict(row)
                template_id = str(mapping.get("template_id", ""))
                templates_list.append({
                    "template_id": template_id,
                    "template_name": str(mapping.get("template_name", "")),
                    "category": str(mapping.get("category", "") or "general"),
                    "preview_url": f"/api/templates/{template_id}/preview",
                })

            return {
                "status": "success",
                "count": len(templates_list),
                "templates": templates_list
            }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch templates: {str(exc)}"
        )


@router.get("/api/templates/{template_id}/preview", summary="Stream template preview.png from Supabase S3")
def get_template_preview(template_id: str):
    """
    Fetches templates/{template_id}/preview.png from Supabase S3 bucket and streams it.
    """
    s3_client = get_s3_client()
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_key = f"templates/{template_id}/preview.png"

    if s3_client:
        try:
            obj = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
            image_bytes = obj["Body"].read()
            content_type = obj.get("ContentType") or "image/png"
            return Response(
                content=image_bytes,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"}
            )
        except Exception as err:
            print(f"[!] Template preview S3 fetch notice for {s3_key}: {err}")

    # Fallback placeholder SVG if S3 preview is unavailable
    svg_fallback = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="800" height="450">
      <defs>
        <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#fff5f5"/>
          <stop offset="100%" stop-color="#fed7d7"/>
        </linearGradient>
      </defs>
      <rect width="800" height="450" fill="url(#grad)"/>
      <rect x="60" y="60" width="680" height="330" rx="16" fill="#ffffff" stroke="#e2e8f0" stroke-width="2"/>
      <circle cx="120" cy="120" r="28" fill="#FF5148" opacity="0.15"/>
      <path d="M110 110 L130 110 L130 130 L110 130 Z" fill="#FF5148"/>
      <text x="120" y="220" font-family="sans-serif" font-size="28" font-weight="bold" fill="#1a202c">Executive Presentation</text>
      <text x="120" y="260" font-family="sans-serif" font-size="16" fill="#718096">Template ID: {template_id}</text>
      <rect x="120" y="290" width="120" height="8" rx="4" fill="#FF5148"/>
    </svg>"""
    return Response(
        content=svg_fallback.encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache"}
    )


@router.get("/api/templates/{template_id}/slides", summary="Load all slide HTMLs for a template from Supabase S3")
def get_template_slides(template_id: str):
    """
    Loads all slides from Supabase S3 under:
    templates/{template_id}/slides/
    Sorts them numerically (slide_01.html -> slide_02.html).
    Returns list of slides with raw HTML and embeddable rendered_html.
    """
    s3_client = get_s3_client()
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    prefix = f"templates/{template_id}/slides/"

    slides: List[Dict[str, Any]] = []

    if s3_client:
        try:
            resp = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
            contents = resp.get("Contents", [])

            html_items = [
                item for item in contents
                if item["Key"].endswith(".html") and not item["Key"].endswith("/")
            ]

            # Sort items by slide number extracted from filename
            html_items.sort(key=lambda item: extract_slide_number(item["Key"]))

            for item in html_items:
                key = item["Key"]
                filename = key.split("/")[-1]
                s_num = extract_slide_number(filename)

                try:
                    obj = s3_client.get_object(Bucket=bucket_name, Key=key)
                    raw_html = obj["Body"].read().decode("utf-8")
                    slide_name = extract_slide_title(raw_html, f"Slide {s_num:02d}")
                    rendered_html = prepare_embeddable_html(raw_html)

                    slides.append({
                        "slide_number": s_num,
                        "filename": filename,
                        "name": slide_name,
                        "s3_key": key,
                        "raw_html": raw_html,
                        "rendered_html": rendered_html,
                    })
                except Exception as slide_err:
                    print(f"[-] Error reading S3 HTML slide {key}: {slide_err}")

        except Exception as exc:
            print(f"[-] Error listing template slides from S3: {exc}")

    # Fallback to local slides directory if S3 returned no slides (e.g. during local tests)
    if not slides:
        local_slides_dir = backend_root.parent / "slides"
        if local_slides_dir.exists():
            local_files = sorted(
                list(local_slides_dir.glob("slide_*.html")),
                key=lambda p: extract_slide_number(p.name)
            )
            for p in local_files:
                s_num = extract_slide_number(p.name)
                try:
                    raw_html = p.read_text(encoding="utf-8")
                    slides.append({
                        "slide_number": s_num,
                        "filename": p.name,
                        "name": extract_slide_title(raw_html, f"Slide {s_num:02d}"),
                        "s3_key": f"local/{p.name}",
                        "raw_html": raw_html,
                        "rendered_html": prepare_embeddable_html(raw_html),
                    })
                except Exception as l_err:
                    print(f"[-] Error reading local slide {p}: {l_err}")

    # Lookup template name from DB
    template_name = "Presentation Template"
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT template_name FROM public.templates WHERE template_id = :tid LIMIT 1;"),
                {"tid": template_id}
            ).fetchone()
            if row and row[0]:
                template_name = str(row[0])
    except Exception:
        pass

    return {
        "status": "success",
        "template_id": template_id,
        "template_name": template_name,
        "slide_count": len(slides),
        "slides": slides,
    }
