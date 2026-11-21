import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_validator

from app.services.agents.models import get_agent_config

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DATABASE_PLAN_PROMPT_PATH = PROMPTS_DIR / "planning" / "database_plan_generator.txt"
DOCUMENT_PLAN_PROMPT_PATH = PROMPTS_DIR / "planning" / "document_plan_generator.txt"
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class CanvasConfig(BaseModel):
    width: int = Field(default=1920, description="Canvas width in pixels")
    height: int = Field(default=1080, description="Canvas height in pixels")


class ComponentLocation(BaseModel):
    x: int = Field(default=80, description="X coordinate on 1920x1080 canvas")
    y: int = Field(default=100, description="Y coordinate on 1920x1080 canvas")
    width: int = Field(default=800, description="Component width in pixels")
    height: int = Field(default=300, description="Component height in pixels")

    @model_validator(mode="before")
    @classmethod
    def coerce_location(cls, data: Any) -> Any:
        if isinstance(data, dict):
            try:
                return {
                    "x": int(float(data.get("x", 80))),
                    "y": int(float(data.get("y", 100))),
                    "width": int(float(data.get("width", 800))),
                    "height": int(float(data.get("height", 300))),
                }
            except Exception:
                return {"x": 80, "y": 100, "width": 800, "height": 300}
        return data


class SlideComponent(BaseModel):
    component: str = Field(default="content", description="Component name or type")
    position: ComponentLocation = Field(default_factory=ComponentLocation, description="Bounding box position")
    location: Optional[ComponentLocation] = None
    content: Any = Field(default_factory=dict, description="Component content or payload")
    data: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def sync_position_and_content(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync position and location
            pos = data.get("position") or data.get("location") or {}
            data["position"] = pos
            data["location"] = pos

            # Sync content and data
            cnt = data.get("content") if "content" in data else data.get("data")
            data["content"] = cnt if cnt is not None else ""
            data["data"] = cnt if cnt is not None else ""
        return data


class SlidePlan(BaseModel):
    canvas: CanvasConfig = Field(default_factory=CanvasConfig, description="Canvas dimensions (1920x1080)")
    components: List[SlideComponent] = Field(default_factory=list, description="Visual components on the slide")
    fallback: Optional[str] = Field(default=None, description="Optional fallback message when info not found")


def _format_rows(retrived_rows: Optional[Union[Dict[str, Any], List[Any], str]]) -> str:
    """Formats retrieved database rows into clean JSON string for the prompt."""
    if retrived_rows is None:
        return "No database records retrieved."

    if isinstance(retrived_rows, (dict, list)):
        try:
            if isinstance(retrived_rows, dict) and "rows" in retrived_rows:
                all_rows = retrived_rows.get("rows") or []
                if len(all_rows) > 50:
                    truncated_payload = {
                        "columns": retrived_rows.get("columns", []),
                        "total_rows_count": len(all_rows),
                        "showing_first_50_rows": all_rows[:50]
                    }
                    return json.dumps(truncated_payload, indent=2, default=str)
                return json.dumps(retrived_rows, indent=2, default=str)
            elif isinstance(retrived_rows, list) and len(retrived_rows) > 50:
                truncated_payload = {
                    "total_rows_count": len(retrived_rows),
                    "showing_first_50_rows": retrived_rows[:50]
                }
                return json.dumps(truncated_payload, indent=2, default=str)
            return json.dumps(retrived_rows, indent=2, default=str)
        except Exception:
            return str(retrived_rows)

    return str(retrived_rows or "{}")


def SlidePlanningAgent(
    user_query: str,
    source: str = "database",
    svg_code: Optional[str] = None,
    retrived_rows: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    retrived_context: Optional[str] = None,
    sql_required: bool = True,
    project_id: Optional[str] = None,
    slide_number: int = 1,
    user_id: Optional[str] = None,
    slide_type: Optional[str] = None,
    slide_info: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Slide Planning Agent (Unified for Database and Document sources):
    - Analyzes user query, previous/current SVG code, and retrieved data:
      * If source == 'database': uses prompts/planning/database_plan_generator.txt with {{svg_code}} & {{retrived_rows}}
      * If source == 'documents': uses prompts/planning/document_plan_generator.txt with {{svg_code}} & {{retrived_context}}
    - Decides WHAT components to place and WHERE (bounding box coordinates on 1920x1080 canvas).
    - Ensures 100% Zero Hallucination and pure JSON skeleton output (no styling).
    - If documents do not contain relevant information, returns {"fallback": "the information not provided in docuemts"}.

    :param user_query: User's instruction or query
    :param source: 'database' or 'documents'
    :param svg_code: Current or previous slide SVG template code
    :param retrived_rows: Query result payload from SQL execution (if source == 'database')
    :param retrived_context: Chunks text retrieved from documents (if source == 'documents')
    :param sql_required: True if data-driven slide from DB records
    :param project_id: Optional project identifier
    :param slide_number: Target slide index (1-based)
    :param user_id: Optional user identifier
    :param slide_type: 'current' or 'previous'
    :param slide_info: Contextual instruction for current or previous slide
    :return: Dict matching the standard layout plan schema or fallback dict
    """
    cleaned_query = (user_query or "").strip()
    source_clean = (source or "database").lower().strip()

    # 1. Resolve template SVG code and slide_type if not directly provided
    template_svg = svg_code
    resolved_slide_type = slide_type
    if not template_svg and project_id:
        try:
            from app.services.presentations.manager import GetSVGCode, is_empty_slide
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
        except Exception as e:
            print(f"[!] SlidePlanningAgent SVG resolution notice: {e}")

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

    # 2. Select and populate prompt template dynamically based on source
    is_doc_source = source_clean in ("documents", "document", "docs")

    if is_doc_source:
        prompt_path = DOCUMENT_PLAN_PROMPT_PATH
        if not prompt_path.exists():
            # Check fallback prompt path
            prompt_path = PROMPTS_DIR / "document_plan_generator.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Document planning prompt template not found at: {DOCUMENT_PLAN_PROMPT_PATH}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        context_str = str(retrived_context or "").strip()
        if not context_str:
            context_str = "No document context chunks retrieved."

        populated_prompt = (
            prompt_template
            .replace("{{slide_type}}", clean_slide_type)
            .replace("{{slide_info}}", clean_slide_info)
            .replace("{{svg_code}}", template_svg)
            .replace("{{retrived_context}}", context_str)
            .replace("{{user_query}}", cleaned_query)
        )
    else:
        # Default: Database source
        prompt_path = DATABASE_PLAN_PROMPT_PATH
        if not prompt_path.exists():
            raise FileNotFoundError(f"Database planning prompt template not found at: {DATABASE_PLAN_PROMPT_PATH}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        rows_str = _format_rows(retrived_rows) if sql_required else "No database records (direct slide edit mode)."

        populated_prompt = (
            prompt_template
            .replace("{{slide_type}}", clean_slide_type)
            .replace("{{slide_info}}", clean_slide_info)
            .replace("{{svg_code}}", template_svg)
            .replace("{{retrived_rows}}", rows_str)
            .replace("{{user_query}}", cleaned_query)
        )

    # 3. Configure LLM connection from models.py
    llm_cfg = get_agent_config("slide_planning_agent")
    base_url = str(llm_cfg.get("BASE_URL") or "https://openrouter.ai/api/v1/chat/completions").rstrip("/")
    api_key = str(llm_cfg.get("API_KEY") or "")
    model = str(llm_cfg.get("MODEL_NAME") or "z-ai/glm-5.3-flash")
    temperature = float(llm_cfg.get("TEMPERATURE", 0.2))

    if not api_key:
        print("[!] Warning: LLM_API_KEY not set for SlidePlanningAgent.")

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
        "max_tokens": 8096,
        "response_format": {"type": "json_object"}
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

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_bytes = resp.read()
            resp_json = json.loads(resp_bytes.decode("utf-8"))
            raw_content = resp_json["choices"][0]["message"]["content"]
            usage = resp_json.get("usage", {})

            # Log to workflow logger
            try:
                from app.logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name=f"Node: Slide Planning ({source_clean})",
                    agent_name="Slide Planning Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging slide planning call: {log_err}")

            # Strip markdown fences if present
            stripped = raw_content.strip()
            if "```" in stripped:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
                if match:
                    stripped = match.group(1).strip()
            first_brace = stripped.find("{")
            last_brace = stripped.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                stripped = stripped[first_brace:last_brace + 1]

            parsed_data = json.loads(stripped)

            # Check if LLM emitted fallback
            if isinstance(parsed_data, dict) and "fallback" in parsed_data and parsed_data["fallback"]:
                fallback_msg = str(parsed_data["fallback"])
                print(f"[*] [SlidePlanningAgent] Fallback detected: {fallback_msg}")
                return {"fallback": fallback_msg}

            # Validate structured JSON using Pydantic
            plan = SlidePlan.model_validate(parsed_data)
            return plan.model_dump()

    except Exception as err:
        print(f"[!] Error in SlidePlanningAgent: {err}. Generating fallback plan.")
        return SlidePlan().model_dump()
