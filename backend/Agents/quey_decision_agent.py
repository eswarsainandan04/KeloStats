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
        sql_required = QueryDecisionClassifyAgent(user_query=cleaned_query)
        return {
            "decision": "agent",
            "sql_required": sql_required,
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

            sql_required = True
            if decision == "agent":
                sql_required = QueryDecisionClassifyAgent(user_query=cleaned_query)

            return {
                "decision": decision,
                "sql_required": sql_required,
                "reason": reason
            }

    except Exception as err:
        print(f"[!] Warning in QueryDecisionAgent: {err}. Defaulting to normal_qa.")
        return {
            "decision": "normal_qa",
            "sql_required": True,
            "reason": f"Fallback decision due to exception: {str(err)}"
        }


def QueryDecisionClassifyAgent(user_query: str) -> bool:
    """
    Classifies an 'agent' request to determine whether SQL execution is required.
    - If user query is a simple request for editing, styling, designing, or improving content in the PPT without SQL -> sql_required: False
    - Else (requires database records or metrics) -> sql_required: True

    :param user_query: User query string
    :return: bool (True if SQL is required, False if SQL pipeline should be skipped)
    """
    cleaned_query = (user_query or "").strip()
    if not cleaned_query:
        return False

    prompt = f"""
        You are the PPT Task Classification Agent for KeloStats, an enterprise AI analytics platform connected to an enterprise relational database.
        Your job is to determine whether a presentation request requires querying the database via the SQL pipeline (sql_required: true) or is a direct visual/textual EDIT on an existing slide canvas without database data (sql_required: false).

        RULES:
        1. sql_required: true (DEFAULT for presentation creation and data analysis):
            - Any command to create, generate, analyze, discuss, summarize, or present business topics, performance, trends, or insights (e.g., 'disscuss a trend analysis summary in PPT', 'generate slide on top products', 'create presentation for Q3 churn', 'build a deck on revenue', 'present category breakdown').
            - Even high-level executive summaries or business analyses (like SWOT, market trends, performance reviews) MUST query the database to ground the slide in real business facts and metrics.

        2. sql_required: false (ONLY for direct slide styling, layout adjustment, or simple edits):
            - The user is asking to modify the visual appearance, styling, or existing wording of the currently open slide canvas.
            - Examples: 'change title to...', 'make background dark navy', 'restyle cards with purple border', 'increase font size', 'change button color', 'remove second card', 'edit this slide to fix typo'.

        Output:
        just return true or false, nothing else.

        User Query:
        "{cleaned_query}"
    """

    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        print("[!] Warning: LLM_API_KEY is not set in QueryDecisionClassifyAgent. Defaulting to True.")
        return True

    endpoint_url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

    request_data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt
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
            raw_content = resp_json["choices"][0]["message"]["content"].strip()
            usage = resp_json.get("usage", {})

            # Log interaction to workflow logger
            try:
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name="Node: Query Decision Classify",
                    agent_name="Query Decision Classify Agent",
                    llm_input=prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging classify agent interaction: {log_err}")

            raw_lower = raw_content.lower()
            if "false" in raw_lower:
                return False
            return True

    except Exception as err:
        print(f"[!] Warning in QueryDecisionClassifyAgent: {err}. Defaulting to True.")
        return True