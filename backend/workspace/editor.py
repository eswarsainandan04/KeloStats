import io
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel

from databases.tools.pptxgenjs_exe_tool import execute_pptxgenjs_tool, get_s3_client
from workspace.render_ppt import (
    load_slides_from_s3,
    prepare_embeddable_html,
    extract_slide_number,
)
from workspace.download_ppt import compile_html_slides_to_pptx

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
backend_root = current_dir.parent
if (backend_root / ".env").exists():
    load_dotenv(dotenv_path=backend_root / ".env")
else:
    load_dotenv()

router = APIRouter(prefix="/api/workspace/editor", tags=["Workspace Editor"])

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}

# Standard 16:9 dimensions in inches and points
SLIDE_WIDTH_IN = 13.333
SLIDE_HEIGHT_IN = 7.5
EMU_PER_INCH = 914400.0


class InitEditorRequest(BaseModel):
    user_id: str
    project_id: str


def parse_pptx_slides(pptx_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parses all visual shapes, accent lines, dot matrices, and text elements directly
    from presentation.pptx XML data with exact 16:9 percentage coordinates and typography.
    """
    slides: List[Dict[str, Any]] = []

    try:
        with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as z:
            slide_xml_names = [
                n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            ]
            slide_xml_names.sort(
                key=lambda x: int("".join(filter(str.isdigit, x)) or 0)
            )

            for idx, sname in enumerate(slide_xml_names):
                slide_num = idx + 1
                root = ET.fromstring(z.read(sname))

                shapes: List[Dict[str, Any]] = []
                plain_texts: List[str] = []

                for sp in root.findall(".//p:sp", NS):
                    xfrm = sp.find(".//a:xfrm", NS)
                    if xfrm is None:
                        continue

                    off = xfrm.find("a:off", NS)
                    ext = xfrm.find("a:ext", NS)
                    if off is None or ext is None:
                        continue

                    x_in = int(off.attrib.get("x", 0)) / EMU_PER_INCH
                    y_in = int(off.attrib.get("y", 0)) / EMU_PER_INCH
                    w_in = int(ext.attrib.get("cx", 0)) / EMU_PER_INCH
                    h_in = int(ext.attrib.get("cy", 0)) / EMU_PER_INCH

                    left_pct = round((x_in / SLIDE_WIDTH_IN) * 100, 3)
                    top_pct = round((y_in / SLIDE_HEIGHT_IN) * 100, 3)
                    width_pct = round((w_in / SLIDE_WIDTH_IN) * 100, 3)
                    height_pct = round((h_in / SLIDE_HEIGHT_IN) * 100, 3)

                    # Geometry type (rect, oval, etc.)
                    geom = sp.find(".//a:prstGeom", NS)
                    geom_type = geom.attrib.get("prst", "rect") if geom is not None else "rect"

                    # Color and opacity from solidFill
                    fill = sp.find(".//a:solidFill", NS)
                    color_val = "000000"
                    opacity_val = 1.0
                    if fill is not None:
                        clr = fill.find(".//a:srgbClr", NS)
                        if clr is not None:
                            color_val = clr.attrib.get("val", "000000")
                            alpha = clr.find(".//a:alpha", NS)
                            if alpha is not None:
                                opacity_val = round(int(alpha.attrib.get("val", "100000")) / 100000.0, 3)

                    txBody = sp.find("p:txBody", NS)

                    if txBody is None:
                        # Non-text visual shape (e.g. coral accent line, dot matrix ovals)
                        shapes.append({
                            "type": "shape",
                            "geom": geom_type,
                            "left": left_pct,
                            "top": top_pct,
                            "width": width_pct,
                            "height": height_pct,
                            "color": f"#{color_val}",
                            "opacity": opacity_val,
                        })
                    else:
                        # Text shape
                        paragraphs = []
                        for p in txBody.findall(".//a:p", NS):
                            p_text = "".join(p.itertext()).strip()
                            if not p_text:
                                continue

                            plain_texts.append(p_text)

                            # Alignment
                            pPr = p.find("a:pPr", NS)
                            align = "left"
                            if pPr is not None:
                                algn_attr = pPr.attrib.get("algn")
                                if algn_attr == "ctr":
                                    align = "center"
                                elif algn_attr == "r":
                                    align = "right"

                            # Text run properties
                            r = p.find("a:r", NS)
                            rPr = r.find("a:rPr", NS) if r is not None else None
                            
                            font_size_pt = 14.0
                            bold = False
                            font_family = "Arial"
                            text_color = "000000"
                            letter_spacing_em = "0"

                            if rPr is not None:
                                if "sz" in rPr.attrib:
                                    try:
                                        font_size_pt = round(int(rPr.attrib["sz"]) / 100.0, 1)
                                    except Exception:
                                        pass
                                bold = (rPr.attrib.get("b", "0") == "1")

                                latin = rPr.find("a:latin", NS)
                                if latin is not None and "typeface" in latin.attrib:
                                    font_family = latin.attrib["typeface"]

                                if "spc" in rPr.attrib:
                                    try:
                                        # centipoints to em (approx 100 = 0.08em)
                                        spc_val = int(rPr.attrib["spc"])
                                        letter_spacing_em = f"{round(spc_val / 1200.0, 3)}em"
                                    except Exception:
                                        pass

                                clr = rPr.find(".//a:srgbClr", NS)
                                if clr is not None and "val" in clr.attrib:
                                    text_color = clr.attrib["val"]

                            paragraphs.append({
                                "text": p_text,
                                "fontSizePt": font_size_pt,
                                "bold": bold,
                                "fontFamily": font_family,
                                "color": f"#{text_color}",
                                "align": align,
                                "letterSpacing": letter_spacing_em,
                            })

                        if paragraphs:
                            shapes.append({
                                "type": "text",
                                "left": left_pct,
                                "top": top_pct,
                                "width": width_pct,
                                "height": height_pct,
                                "paragraphs": paragraphs,
                            })

                title = plain_texts[0] if plain_texts else f"Slide {slide_num}"
                subtitle = plain_texts[1] if len(plain_texts) > 1 else ""

                slides.append({
                    "slide_number": slide_num,
                    "title": title,
                    "subtitle": subtitle,
                    "texts": plain_texts,
                    "shapes": shapes,
                })

    except Exception as exc:
        print(f"[-] Error parsing PPTX slides: {exc}")

    return slides


@router.post("/init", summary="Execute presentation.js and parse exact shapes & typography from S3 presentation.pptx")
def init_workspace_editor(payload: InitEditorRequest):
    """
    1. Executes presentation.js using tools/pptxgenjs_exe_tool.py.
    2. Uploads generated presentation.pptx to Supabase S3: workspace/{user_id}/{project_id}/presentation.pptx.
    3. Fetches presentation.pptx from Supabase S3 and extracts all shapes, typography, and accent lines.
    4. Returns the exact visual deck for high-fidelity presentation preview.
    """
    if not payload.user_id or not payload.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id and project_id are required."
        )

    # 1. Execute tool in temporary directory and upload to S3
    tool_result = execute_pptxgenjs_tool(user_id=payload.user_id, project_id=payload.project_id)

    # 2. Fetch presentation.pptx from Supabase S3
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()
    pptx_s3_key = f"workspace/{payload.user_id}/{payload.project_id}/presentation.pptx"

    slides = []
    pptx_exists = False

    if s3_client:
        try:
            pptx_obj = s3_client.get_object(Bucket=bucket_name, Key=pptx_s3_key)
            pptx_bytes = pptx_obj["Body"].read()
            pptx_exists = True
            # 3. Parse all shapes, typography, and positions
            slides = parse_pptx_slides(pptx_bytes)
        except Exception as err:
            print(f"[-] Could not load presentation.pptx from S3: {err}")

    return {
        "status": "success",
        "tool_execution": tool_result,
        "pptx_exists": pptx_exists,
        "s3_key": pptx_s3_key if pptx_exists else None,
        "total_slides": len(slides),
        "slides": slides
    }


@router.get("/download", summary="Compile HTML slides to editable presentation.pptx, save to S3, and download")
def download_presentation(
    user_id: str,
    project_id: str
):
    """
    1. Loads all HTML slides from Supabase S3 under workspace/{user_id}/{project_id}/slides/.
    2. Compiles HTML slides into PowerPoint (.pptx):
       - Backgrounds, shapes, charts, and dot matrices are saved as high-res images.
       - All text (titles, descriptions, numbers, bullets) remains 100% native editable text.
    3. Saves presentation.pptx to Supabase S3 at workspace/{user_id}/{project_id}/presentation.pptx.
    4. Streams presentation.pptx as a local file download.
    """
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()

    slides = load_slides_from_s3(user_id=user_id, project_id=project_id)
    if not slides:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No slides found for project {project_id} under user {user_id}."
        )

    try:
        pptx_bytes = compile_html_slides_to_pptx(slides)
    except Exception as exc:
        print(f"[-] Error compiling HTML slides to PPTX: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PPTX: {str(exc)}"
        )

    # Save to Supabase S3
    pptx_s3_key = f"workspace/{user_id}/{project_id}/presentation.pptx"
    if s3_client:
        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=pptx_s3_key,
                Body=pptx_bytes,
                ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation"
            )
            print(f"[+] Successfully saved {pptx_s3_key} to Supabase S3")
        except Exception as s3_err:
            print(f"[-] Warning: Failed to upload PPTX to S3: {s3_err}")

    # Return as direct local download
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": 'attachment; filename="presentation.pptx"'}
    )


class NewSlideRequest(BaseModel):
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    after_slide: Optional[int] = None


@router.post("/new_slide", summary="Dynamically create and insert a pure blank white slide in Supabase S3")
@router.get("/new_slide", summary="Dynamically create and insert a pure blank white slide in Supabase S3")
def create_new_blank_slide(
    payload: Optional[NewSlideRequest] = None,
    user_id: Optional[str] = Query(None, description="User ID"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    after_slide: Optional[int] = Query(None, description="Insert after this slide number"),
):
    """
    Dynamically generates and inserts a pure blank white slide:
    1. Uses manifest.json to track slides with UUID filenames.
    2. If after_slide is provided (e.g. 4), inserts after slide 4 (becoming slide 5).
    3. Uploads to Supabase S3 under workspace/{user_id}/{project_id}/slides/{UUID}.html.
    4. Updates manifest.json and returns the updated slide details.
    """
    from workspace.manifest import add_slide_to_manifest

    uid = (payload.user_id if payload and payload.user_id else user_id) or ""
    pid = (payload.project_id if payload and payload.project_id else project_id) or ""
    insert_after = (payload.after_slide if payload and payload.after_slide is not None else after_slide)

    uid = uid.strip()
    pid = pid.strip()

    if not uid or not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id and project_id are required."
        )

    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()

    # 1. Add slide entry to manifest.json
    slide_filename, next_slide_num, updated_manifest = add_slide_to_manifest(
        user_id=uid,
        project_id=pid,
        after_count=insert_after,
        s3_client=s3_client
    )

    # 2. Pure blank white slide HTML (16:9 widescreen, clean white background, zero content)
    blank_html = f"""
    <!DOCTYPE html>
        <html lang="en">
        <head>
         <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Slide {next_slide_num:02d} - Blank Slide</title>
        <style>
            body {{
                margin: 0;
                padding: 24px;
                min-height: 100vh;
                background-color: #0f172a;
                display: flex;
                align-items: center;
                justify-content: center;
                font-family: Arial, Helvetica, sans-serif;
            }}

               /* Presentation Slide Canvas (Standard 16:9 Widescreen: 1920x1080) */
            .slide-canvas {{
                position: relative;
                width: 100%;
                aspect-ratio: 16 / 9;
                background-color: #FFFFFF;
                overflow: hidden;
                container-type: inline-size;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            }}

            .slide-canvas * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
        </style>
        </head>
       <body>

        <!-- Slide {next_slide_num:02d} Presentation Canvas (Pure Blank White Slide) -->
        <div id="slide_{next_slide_num:02d}" class="slide-canvas">
        </div>
 
       </body>
     </html>
    """

    s3_key = f"workspace/{uid}/{pid}/slides/{slide_filename}"

    # 3. Upload new blank slide to Supabase S3
    if s3_client:
        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=blank_html.encode("utf-8"),
                ContentType="text/html; charset=utf-8"
            )
            print(f"[+] Successfully uploaded new blank slide to S3: {s3_key}")
        except Exception as upload_err:
            print(f"[-] S3 upload failed for {s3_key}: {upload_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload new slide to Supabase S3: {str(upload_err)}"
            )
    else:
        # Local fallback if S3 is not configured
        local_practice_slides = backend_root.parent / "practice" / "slides"
        local_practice_root = backend_root.parent / "practice"
        target_dir = local_practice_slides if local_practice_slides.exists() else local_practice_root
        target_file = target_dir / slide_filename
        target_file.write_text(blank_html, encoding="utf-8")
        print(f"[+] Saved blank slide locally to fallback: {target_file}")

    rendered_html = prepare_embeddable_html(blank_html)

    return {
        "status": "success",
        "message": f"Successfully created pure blank white slide {next_slide_num}",
        "slide_number": next_slide_num,
        "filename": slide_filename,
        "name": f"Slide {next_slide_num}",
        "s3_key": s3_key,
        "raw_html": blank_html,
        "rendered_html": rendered_html,
        "total_slides": len(updated_manifest)
    }


class DeleteSlideRequest(BaseModel):
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    slide_number: Optional[int] = None


@router.post("/delete_slide", summary="Delete a slide from presentation in Supabase S3")
@router.delete("/delete_slide", summary="Delete a slide from presentation in Supabase S3")
def delete_slide_endpoint(
    payload: Optional[DeleteSlideRequest] = None,
    user_id: Optional[str] = Query(None, description="User ID"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    slide_number: Optional[int] = Query(None, description="Slide number to delete"),
):
    """
    Deletes a slide from Supabase S3 and updates manifest.json:
    1. Validates that user_id, project_id, and slide_number are provided.
    2. Ensures at least 1 slide remains (cannot delete the only slide).
    3. Deletes the target slide from S3 (e.g. {UUID}.html).
    4. Updates manifest.json re-indexing remaining slide counts 1..N without renaming files.
    5. Returns updated slide list and status.
    """
    from workspace.manifest import delete_slide_from_manifest

    uid = (payload.user_id if payload and payload.user_id else user_id) or ""
    pid = (payload.project_id if payload and payload.project_id else project_id) or ""
    s_num = (payload.slide_number if payload and payload.slide_number is not None else slide_number)

    uid = uid.strip()
    pid = pid.strip()

    if not uid or not pid or s_num is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id, project_id, and slide_number are required."
        )

    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()

    existing_slides = load_slides_from_s3(user_id=uid, project_id=pid)
    if not existing_slides:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No slides found for project {pid}."
        )

    if len(existing_slides) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the only remaining slide in the presentation."
        )

    # Check if target slide exists
    target_slide = next((s for s in existing_slides if s.get("slide_number") == s_num), None)
    if not target_slide:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slide {s_num} not found in project {pid}."
        )

    # Delete slide from manifest and S3
    deleted_filename, updated_manifest = delete_slide_from_manifest(
        user_id=uid,
        project_id=pid,
        slide_identifier=s_num,
        s3_client=s3_client
    )

    # Reload updated slides list according to manifest
    fresh_slides = load_slides_from_s3(user_id=uid, project_id=pid)

    return {
        "status": "success",
        "message": f"Successfully deleted slide {s_num} ({deleted_filename}) from project {pid}",
        "deleted_slide_number": s_num,
        "deleted_filename": deleted_filename,
        "remaining_slides_count": len(fresh_slides),
        "slides": fresh_slides
    }






