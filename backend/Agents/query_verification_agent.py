import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "query_verfication.txt"


class VerificationStatus(str, Enum):
    SCHEMA_MATCH = "SCHEMA_MATCH"
    RETRIEVAL_REQUIRED = "RETRIEVAL_REQUIRED"


class QueryVerificationResponse(BaseModel):
    status: VerificationStatus = Field(default=VerificationStatus.SCHEMA_MATCH, description="Verification status")
    reason: str = Field(default="No reason provided.", description="Reason for verification status")

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> VerificationStatus:
        if isinstance(value, str):
            clean_val = value.strip().upper()
            for item in VerificationStatus:
                if item.value == clean_val:
                    return item
        return VerificationStatus.SCHEMA_MATCH


def QueryVerifyAgent(
    user_query: str,
    llm_prompt_text: str,
    database_id: Optional[str] = None,
) -> Dict[str, str]:
    """
    Query Verification Agent:
    - Calls LLM to verify whether the user query is related to the schema,
      requires dynamic entity retrieval, or is unrelated/unanswerable.
    - Returns structured classification dict: {"status": status, "reason": reason}

    :param user_query: User natural language request
    :param llm_prompt_text: Extracted database schema text context
    :param database_id: Target database ID (optional)
    :return: Dict containing 'status' ("SCHEMA_MATCH" | "RETRIEVAL_REQUIRED" | "UNRELATED") and 'reason'
    """
    # 1. Read prompt template
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Verification prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # 2. Populate prompt placeholders
    populated_prompt = (
        prompt_template
        .replace("{{llm_prompt_text}}", llm_prompt_text)
        .replace("{{user_query}}", user_query)
    )

    # 3. Read LLM configuration from .env
    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError("LLM_API_KEY is not set in environment or .env file.")

    if not base_url.endswith("/chat/completions"):
        endpoint_url = f"{base_url}/chat/completions"
    else:
        endpoint_url = base_url

    # 4. Call LLM for verification
    request_data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": populated_prompt
            }
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    req_body = json.dumps(request_data).encode("utf-8")
    req = urllib.request.Request(
        endpoint_url,
        data=req_body,
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

            # Log interaction to active workflow logger
            try:
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name="Node 2",
                    agent_name="Verification Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging verification agent interaction: {log_err}")

            try:
                parsed = QueryVerificationResponse.model_validate_json(raw_content)
            except Exception:
                stripped = raw_content.strip()
                if "```" in stripped:
                    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
                    if match:
                        stripped = match.group(1).strip()
                first_brace = stripped.find("{")
                last_brace = stripped.rfind("}")
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    stripped = stripped[first_brace:last_brace + 1]
                parsed = QueryVerificationResponse.model_validate_json(stripped)

            status = parsed.status.value
            if status != "RETRIEVAL_REQUIRED":
                status = "SCHEMA_MATCH"

            return {
                "status": status,
                "reason": parsed.reason
            }
    except urllib.error.HTTPError as http_err:
        err_msg = http_err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API Error ({http_err.code}): {err_msg}") from http_err
    except Exception as err:
        print(f"[!] Warning parsing verification result: {err}. Defaulting to SCHEMA_MATCH.")
        return {
            "status": "SCHEMA_MATCH",
            "reason": f"Fallback due to verification parse warning: {str(err)}"
        }



