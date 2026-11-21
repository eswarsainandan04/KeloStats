import io
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.core.storage import get_storage
from app.services.connectors import app_db_engine
from app.services.agents.models import get_agent_config
from app.services.presentations.manager import GetSVGCode, is_empty_slide, _extract_svg_only

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
PPT_GENERATION_PROMPT_PATH = PROMPTS_DIR / "presentation" / "ppt_generation_prompt.txt"
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def resolve_user_id(project_id: Optional[str] = None, user_id: Optional[str] = None) -> Optional[str]:
    """
    Resolves the authenticated user_id.
    Prefers user_id passed directly from JWT auth / graph state.
    Falls back to querying the workspace table via app_db_engine.
    """
    if user_id and str(user_id).strip():
        return str(user_id).strip()

    if project_id:
        try:
            from sqlalchemy import text
            with app_db_engine.connect() as conn:
                row = conn.execute(
                    text("SELECT user_id FROM workspace WHERE project_id = :pid LIMIT 1;"),
                    {"pid": str(project_id).strip()}
                ).fetchone()
                if row and row[0]:
                    return str(row[0]).strip()
        except Exception as db_err:
            print(f"[!] DB user_id lookup notice for project '{project_id}': {db_err}")

    return None


# Backward compatibility alias
get_user_id_for_project = resolve_user_id


def save_slide_to_storage(
    project_id: str,
    slide_number: int,
    slide_code: str,
    user_id: Optional[str] = None
) -> bool:
    """
    Saves the generated SVG slide code into storage adapter under:
    workspace/{user_id}/{project_id}/slides/{UUID}.svg
    and keeps manifest.json accurately synchronized with .svg filenames.
    """
    if not project_id or not slide_code:
        return False

    uid = resolve_user_id(project_id=project_id, user_id=user_id)
    if not uid:
        print(f"[!] Warning: Unable to resolve user_id for project '{project_id}'; skipping slide persistence.")
        return False

    storage = get_storage()
    cleaned_code = _clean_svg_response(slide_code) or slide_code.strip()

    # 1. Resolve or create filename via manifest.json
    manifest_key = f"workspace/{uid}/{project_id}/manifest.json"
    filename = None
    manifest_items = []
    manifest_updated = False

    try:
        if storage.exists(manifest_key):
            raw_manifest = storage.read_text(manifest_key)
            parsed = json.loads(raw_manifest)
            manifest_items = parsed if isinstance(parsed, list) else parsed.get("slides", [])
            for item in manifest_items:
                if int(item.get("count", 0)) == slide_number:
                    old_fname = item.get("filename")
                    # LLM has modified this slide -> mark is_blank_slide = False
                    if item.get("is_blank_slide") is not False:
                        item["is_blank_slide"] = False
                        manifest_updated = True
                    # Migrate legacy filename in manifest to .svg
                    if old_fname and not old_fname.endswith(".svg"):
                        filename = f"{old_fname.rsplit('.', 1)[0]}.svg"
                        item["filename"] = filename
                        manifest_updated = True
                    else:
                        filename = old_fname
                    break
    except Exception as m_err:
        print(f"[!] Notice reading manifest in save_slide_to_storage: {m_err}")

    # Generate new filename if none was found in manifest
    if not filename:
        import uuid
        filename = f"{uuid.uuid4()}.svg"
        manifest_items.append({"filename": filename, "count": slide_number, "is_blank_slide": False})
        manifest_updated = True

    if manifest_updated:
        manifest_items.sort(key=lambda x: int(x.get("count", 0)))
        for idx, item in enumerate(manifest_items, start=1):
            item["count"] = idx

        manifest_bytes = json.dumps(manifest_items, indent=2).encode("utf-8")
        try:
            if storage.exists(manifest_key):
                storage.update(manifest_key, manifest_bytes, content_type="application/json")
            else:
                storage.create(manifest_key, manifest_bytes, content_type="application/json")
        except Exception as m_save_err:
            print(f"[!] Notice saving updated manifest: {m_save_err}")

    primary_key = f"workspace/{uid}/{project_id}/slides/{filename}"
    content_type = "image/svg+xml; charset=utf-8"
    slide_bytes = cleaned_code.encode("utf-8")

    try:
        if storage.exists(primary_key):
            storage.update(primary_key, slide_bytes, content_type=content_type)
        else:
            storage.create(primary_key, slide_bytes, content_type=content_type)
        print(f"[+] [save_slide_to_storage] Saved Slide {slide_number} ({filename}) to storage: {primary_key}")
        return True
    except Exception as upload_err:
        print(f"[-] [save_slide_to_storage] Failed to save Slide {slide_number} to {primary_key}: {upload_err}")
        return False


# Compatibility alias
save_slide_to_s3 = save_slide_to_storage


def _clean_svg_response(raw_response: str) -> str:
    """
    Extracts pure SVG code from the model output.
    Strips reasoning tags, markdown fences, and conversational commentary.
    """
    text = (raw_response or "").strip()

    # 1. Strip <think>...</think>
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # 2. Extract ```xml / ```svg content if present
    match = re.search(r"```(?:xml|svg)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # 3. Locate <svg ... </svg>
    start_idx = text.find("<svg")
    end_idx = text.rfind("</svg>")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        text = text[start_idx:end_idx + 6].strip()

    return text


def PPTGenerationAgent(
    user_query: str,
    slide_plan: Optional[Union[Dict[str, Any], str]] = None,
    slide_number: int = 1,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    svg_code: Optional[str] = None,
    sql_required: bool = True,
    slide_type: Optional[str] = None,
    slide_info: Optional[str] = None,
    **kwargs
) -> str:
    """
    PPT Generation Agent:
    - Observes current/previous slide SVG code and applies the structured slide plan content.
    - Uses single prompt from prompts/presentation/ppt_generation_prompt.txt.
    - Zero hardcoded fallbacks and zero styling bloat.
    - Returns pure, presentation-ready SVG slide code.

    :param user_query: The natural language prompt / instruction from user
    :param slide_plan: Structured layout plan JSON containing components and coordinates
    :param slide_number: Target slide index (1-based)
    :param project_id: Optional project identifier for storage sync
    :param user_id: Optional user identifier
    :param svg_code: Current or previous slide SVG template
    :param sql_required: Boolean flag indicating if data-driven
    :param slide_type: 'current' or 'previous'
    :param slide_info: Contextual instruction for current or previous slide
    :return: Pure SVG slide code
    """
    cleaned_query = (user_query or "").strip()

    # 1. Format slide_plan to clean JSON string
    if slide_plan is not None:
        if isinstance(slide_plan, (dict, list)):
            plan_str = json.dumps(slide_plan, indent=2, default=str)
        else:
            plan_str = str(slide_plan or "{}")
    else:
        plan_str = "{}"

    # 2. Determine template SVG code and slide_type
    template_svg = svg_code
    resolved_slide_type = slide_type
    if not template_svg and project_id:
        current_svg = GetSVGCode(project_id=project_id, slide_number=slide_number, user_id=user_id)
        if is_empty_slide(current_svg, project_id=project_id, slide_number=slide_number, user_id=user_id):
            if slide_number > 1:
                prev_num = slide_number - 1
                prev_svg = GetSVGCode(project_id=project_id, slide_number=prev_num, user_id=user_id)
                prev_is_blank = is_empty_slide(prev_svg, project_id=project_id, slide_number=prev_num, user_id=user_id)
                template_svg = prev_svg if (prev_svg and not prev_is_blank) else current_svg
                if not resolved_slide_type:
                    resolved_slide_type = "previous"
            else:
                template_svg = current_svg
                if not resolved_slide_type:
                    resolved_slide_type = "current"
        else:
            template_svg = current_svg
            if not resolved_slide_type:
                resolved_slide_type = "current"

    if not template_svg or not template_svg.strip():
        template_svg = '<svg viewBox="0 0 1920 1080" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg"><rect width="1920" height="1080" fill="#FFFFFF"/></svg>'

    # Resolve dynamic slide_type and slide_info instructions
    clean_slide_type = (resolved_slide_type or "current").lower().strip()
    if clean_slide_type not in ("previous", "current"):
        clean_slide_type = "current"

    if not slide_info or not str(slide_info).strip():
        if clean_slide_type == "previous":
            clean_slide_info = "you need carry the theme from previous slide and add the new content in blank slide but do not copy previous slide to blank slide"
        else:
            clean_slide_info = "you need to update this current slide, with possible adjustment or modifiication or creation basing on user request in user query"
    else:
        clean_slide_info = str(slide_info).strip()

    # 3. Read single prompt template from prompts/presentation/ppt_generation_prompt.txt
    if not PPT_GENERATION_PROMPT_PATH.exists():
        raise FileNotFoundError(f"PPT generation prompt template not found at: {PPT_GENERATION_PROMPT_PATH}")

    with open(PPT_GENERATION_PROMPT_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    populated_prompt = (
        prompt_template
        .replace("{{slide_type}}", clean_slide_type)
        .replace("{{slide_info}}", clean_slide_info)
        .replace("{{svg_code}}", template_svg)
        .replace("{{slide_plan}}", plan_str)
        .replace("{{Prompt}}", cleaned_query)
        .replace("{{user_query}}", cleaned_query)
    )

    # 4. Configure LLM connection from models.py
    llm_cfg = get_agent_config("ppt_generation_agent")
    base_url = str(llm_cfg.get("BASE_URL") or "https://openrouter.ai/api/v1/chat/completions").rstrip("/")
    api_key = str(llm_cfg.get("API_KEY") or "")
    model = str(llm_cfg.get("MODEL_NAME") or "z-ai/glm-5.3-flash")
    temperature = float(llm_cfg.get("TEMPERATURE", 0.2))

    if not api_key:
        raise ValueError("LLM_API_KEY is not set in environment or .env file.")

    endpoint_url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

    request_data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": populated_prompt
            }
        ],
        "temperature": temperature,
        "max_tokens": 15000
    }

    req = urllib.request.Request(
        endpoint_url,
        data=json.dumps(request_data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Kelostats-Agent/1.0"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        resp_bytes = resp.read()
        resp_json = json.loads(resp_bytes.decode("utf-8"))
        raw_content = resp_json["choices"][0]["message"]["content"]
        usage = resp_json.get("usage", {})

        # Log interaction to workflow logger
        try:
            from app.logs.llm_logger import log_agent_call
            log_agent_call(
                node_name="Node: PPT Generation",
                agent_name="PPT Generation Agent",
                llm_input=populated_prompt,
                llm_output=raw_content,
                usage=usage
            )
        except Exception as log_err:
            print(f"[!] Warning logging PPT generation interaction: {log_err}")

        generated_svg = _clean_svg_response(raw_content)
        if not generated_svg:
            generated_svg = raw_content.strip()

        # 5. Save generated slide to storage
        if project_id:
            save_slide_to_storage(
                project_id=project_id,
                slide_number=slide_number,
                slide_code=generated_svg,
                user_id=user_id
            )

        return generated_svg
