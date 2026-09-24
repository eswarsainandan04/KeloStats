import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PLANNING_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "slide_planing_agent_prompt.txt"
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
    location: ComponentLocation = Field(default_factory=ComponentLocation, description="Bounding box location")
    data: Any = Field(default_factory=dict, description="Flexible component payload")


class SlidePlan(BaseModel):
    canvas: CanvasConfig = Field(default_factory=CanvasConfig, description="Canvas dimensions (1920x1080)")
    components: List[SlideComponent] = Field(default_factory=list, description="Visual components on the slide")





def SlidePlanningAgent(
    user_query: str,
    html_code: Optional[str] = None,
    retrived_rows: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    sql_required: bool = True,
    project_id: Optional[str] = None,
    slide_number: int = 1,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Slide Planning Agent:
    - Analyzes user query, retrieved SQL database rows (if sql_required is True),
      and current slide HTML code.
    - Decides WHAT components to place and WHERE (bounding box coordinates on 1920x1080 canvas).
    - Ensures zero styling/color bloat, focusing purely on component data and non-overlapping locations.
    - Returns a validated slide layout plan dictionary.

    :param user_query: The natural language prompt / instruction from user
    :param html_code: Current or previous slide HTML template
    :param retrived_rows: Query result payload from SQL execution (None if sql_required=False)
    :param sql_required: True if data-driven slide from DB records; False if direct editing/styling
    :param project_id: Optional project identifier
    :param slide_number: Target slide index (1-based)
    :param user_id: Optional user identifier
    :return: Dict matching the standard layout plan schema {"canvas": ..., "components": [...]}
    """
    cleaned_query = (user_query or "").strip()

    # 1. Format retrieved_rows to clean JSON string
    if sql_required and retrived_rows is not None:
        if isinstance(retrived_rows, (dict, list)):
            if isinstance(retrived_rows, dict) and "rows" in retrived_rows:
                all_rows = retrived_rows.get("rows") or []
                if len(all_rows) > 50:
                    truncated_payload = {
                        "columns": retrived_rows.get("columns", []),
                        "total_rows_count": len(all_rows),
                        "showing_first_50_rows": all_rows[:50]
                    }
                    data_str = json.dumps(truncated_payload, indent=2, default=str)
                else:
                    data_str = json.dumps(retrived_rows, indent=2, default=str)
            elif isinstance(retrived_rows, list) and len(retrived_rows) > 50:
                data_str = json.dumps({
                    "total_rows_count": len(retrived_rows),
                    "showing_first_50_rows": retrived_rows[:50]
                }, indent=2, default=str)
            else:
                data_str = json.dumps(retrived_rows, indent=2, default=str)
        else:
            data_str = str(retrived_rows or "{}")
    else:
        data_str = "No database records (direct slide edit mode)."

    # 2. Resolve template HTML if not provided
    template_html = html_code
    if not template_html and project_id:
        try:
            from Agents.ppt_generation_agent import GetHTMLCode, is_empty_slide
            current_html = GetHTMLCode(project_id=project_id, slide_number=slide_number, user_id=user_id)
            if is_empty_slide(current_html):
                if slide_number > 1:
                    prev_html = GetHTMLCode(project_id=project_id, slide_number=slide_number - 1, user_id=user_id)
                    template_html = prev_html if (prev_html and not is_empty_slide(prev_html)) else current_html
                else:
                    template_html = current_html
            else:
                template_html = current_html
        except Exception as e:
            print(f"[!] SlidePlanningAgent HTML resolution notice: {e}")

    if not template_html or not template_html.strip():
        template_html = "<!-- Default Presentation Slide Canvas (Blank) -->"

    # 3. Read prompt template
    if not PLANNING_PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Slide planning prompt template not found at: {PLANNING_PROMPT_TEMPLATE_PATH}")

    with open(PLANNING_PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    if sql_required:
        mode_context = f"""
            DATABASE RECORDS:
            {data_str}
 
            INSTRUCTION:
            Based on the user query, the current/previous slide HTML, and the retrieved database records above, arrange the information into the JSON format with components, bounding box locations (coordinates on 1920x1080 canvas), and flexible data.
        """
    else:
        mode_context = """
            INSTRUCTION:
            Based on the user query and the current/previous slide HTML above, generate or edit the slide components, updating their data or spatial locations as per the user's request.
        """

    populated_prompt = (
        prompt_template
        .replace("{{user_query}}", cleaned_query)
        .replace("{{html_code}}", template_html)
        .replace("{{mode_context}}", mode_context)
        .replace("{{sql_required}}", str(sql_required))
        .replace("{{retrived_rows}}", data_str)
    )

    # 4. Configure LLM connection
    base_url = os.getenv("PLANNING_LLM_BASE_URL")
    api_key =  os.getenv("PLANNING_LLM_API_KEY")
    model = os.getenv("PLANNING_LLM_MODEL")


    if not api_key:
        print("[!] Warning: LLM_API_KEY not set. Returning default fallback plan.")

    endpoint_url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

    request_data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": populated_prompt
            }
        ],
        "temperature": 0.2,
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
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name="Node: Slide Planning",
                    agent_name="Slide Planning Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging slide planning call: {log_err}")
            # Validate structured JSON using Pydantic model_validate_json
            try:
                plan = SlidePlan.model_validate_json(raw_content)
                return plan.model_dump()
            except Exception:
                # Handle responses if wrapped in markdown code fences
                stripped = raw_content.strip()
                if "```" in stripped:
                    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
                    if match:
                        stripped = match.group(1).strip()
                first_brace = stripped.find("{")
                last_brace = stripped.rfind("}")
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    stripped = stripped[first_brace:last_brace + 1]

                plan = SlidePlan.model_validate_json(stripped)
                return plan.model_dump()

    except Exception as err:
        print(f"[!] Error in SlidePlanningAgent: {err}. Generating fallback plan.")
        return SlidePlan().model_dump()
