import os
import sys
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Load environment variables
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

RAG_PLANNING_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "rag_planing_agent_prompt.txt"
BACKEND_ROOT = backend_dir


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


def RAGPlannerAgent(
    user_query: str,
    html_code: Optional[str] = None,
    generated_context: Optional[str] = None,
    project_id: Optional[str] = None,
    slide_number: int = 1,
    user_id: Optional[str] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    RAG Slide Planning Agent:
    - Analyzes the user query, the synthesized document knowledge (generated_context
      produced by KnowledgeAnswerAgent), and the current/previous slide HTML code.
    - Designs a structured 16:9 layout plan on a 1920x1080 canvas with non-overlapping
      bounding box coordinates and rich, structured document findings.
    - Returns a validated slide layout plan dictionary matching the standard SlidePlan schema.

    :param user_query: The natural language prompt / instruction from user
    :param html_code: Current or previous slide HTML template
    :param generated_context: Synthesized document knowledge/answer from KnowledgeAnswerAgent
    :param project_id: Optional project identifier
    :param slide_number: Target slide index (1-based)
    :param user_id: Optional user identifier
    :return: Dict matching the standard layout plan schema {"canvas": ..., "components": [...]}
    """
    cleaned_query = (user_query or "").strip()
    context_str = str(generated_context or "").strip()
    if not context_str:
        context_str = "No specific document context provided. Generate layout based on user query."

    # 1. Resolve template HTML if not provided
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
            print(f"[!] RAGPlannerAgent HTML resolution notice: {e}")

    if not template_html or not template_html.strip():
        template_html = "<!-- Default Presentation Slide Canvas (Blank) -->"

    # 2. Read prompt template
    if not RAG_PLANNING_PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"RAG slide planning prompt template not found at: {RAG_PLANNING_PROMPT_TEMPLATE_PATH}")

    with open(RAG_PLANNING_PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    populated_prompt = (
        prompt_template
        .replace("{{user_query}}", cleaned_query)
        .replace("{{generated_context}}", context_str)
        .replace("{{html_code}}", template_html)
    )

    # 3. Configure LLM connection
    base_url = (
        os.getenv("PLANNING_LLM_BASE_URL")
        or os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    ).rstrip("/")
    api_key = (
        os.getenv("PLANNING_LLM_API_KEY")
        or os.getenv("LLM_API_KEY", "")
    )
    model = (
        os.getenv("PLANNING_LLM_MODEL")
        or os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    )

    if not api_key:
        print("[!] Warning: LLM_API_KEY not set in RAGPlannerAgent. Returning default fallback plan.")
        return SlidePlan().model_dump()

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
                    node_name="Node: RAG Slide Planning",
                    agent_name="RAG Planner Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging RAG slide planning call: {log_err}")

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
        print(f"[!] Error in RAGPlannerAgent: {err}. Generating fallback plan.")
        return SlidePlan().model_dump()
