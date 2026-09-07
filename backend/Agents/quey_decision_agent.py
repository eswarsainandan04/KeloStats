import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "query_decision_prompt.txt"


def _clean_json_response(raw_response: str) -> str:
    """
    Strips markdown code blocks, reasoning tags, and extracts clean JSON.
    """
    text = raw_response.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    return text


def QueryDecisionAgent(user_query: str) -> Dict[str, str]:
    """
    Query Decision Agent:
    - Determines if an in-scope request is:
      1. 'agent': Action command or directive to generate, create, or present slides/decks/PPT
      2. 'normal_qa': Factual/analytical question asking for numbers, metrics, or answers from data
    
    :param user_query: In-scope user query string
    :return: Dict with 'decision' ("normal_qa" | "agent") and 'reason'
    """
    cleaned_query = (user_query or "").strip()
    if not cleaned_query:
        return {
            "decision": "normal_qa",
            "reason": "Empty input defaulted to normal_qa."
        }

    # Fast heuristic check for obvious presentation keywords
    lower_query = cleaned_query.lower()
    ppt_triggers = [
        "generate this", "generate slide", "generate presentation", "present on",
        "do it in ppt", "build a deck", "make a presentation", "create a slide",
        "create presentation", "in ppt", "into ppt", "ppt format", "slide deck"
    ]
    if any(trigger in lower_query for trigger in ppt_triggers):
        return {
            "decision": "agent",
            "reason": "Identified explicit presentation generation command keywords."
        }

    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Decision prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    populated_prompt = prompt_template.replace("{{user_query}}", cleaned_query)

    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

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
        "temperature": 0.0
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_bytes = resp.read()
            resp_json = json.loads(resp_bytes.decode("utf-8"))
            raw_content = resp_json["choices"][0]["message"]["content"]
            usage = resp_json.get("usage", {})

            # Log interaction to workflow logger
            try:
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name="Node: Query Decision",
                    agent_name="Query Decision Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging decision agent interaction: {log_err}")

            cleaned_json = _clean_json_response(raw_content)
            result = json.loads(cleaned_json)
            decision = str(result.get("decision", "normal_qa")).lower().strip()
            reason = result.get("reason", "Query decision classified successfully.")

            if decision not in ["normal_qa", "agent"]:
                decision = "normal_qa"

            return {
                "decision": decision,
                "reason": reason
            }

    except Exception as err:
        print(f"[!] Warning in QueryDecisionAgent: {err}. Defaulting to normal_qa.")
        return {
            "decision": "normal_qa",
            "reason": f"Fallback decision due to exception: {str(err)}"
        }
