import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Union

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "answer_generator_prompt.txt"


def _clean_text_response(raw_response: str) -> str:
    """
    Strips reasoning tags and extra surrounding fences if present.
    """
    text = raw_response.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # If the entire response is wrapped in markdown code blocks, unwrap it
    match = re.match(r"^```(?:markdown|text)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    return text


def AnswerGeneratorAgent(retrieved_rows: Union[Dict[str, Any], List[Any], str], user_query: str) -> str:
    """
    Answer Generator Agent:
    - Receives user query and retrieved database records in JSON format.
    - Synthesizes a natural, concise answer (simple paragraph or bullet points).
    
    :param retrieved_rows: Dict with {"columns": [...], "rows": [...]} or list of dict records
    :param user_query: Original user query string
    :return: Clean text response answering the user query from the database rows
    """
    cleaned_query = (user_query or "").strip()

    # 1. Format retrieved_rows to JSON string
    if isinstance(retrieved_rows, (dict, list)):
        # Limit rows preview if extremely large to stay comfortably in context window
        if isinstance(retrieved_rows, dict) and "rows" in retrieved_rows:
            all_rows = retrieved_rows.get("rows") or []
            if len(all_rows) > 50:
                truncated_payload = {
                    "columns": retrieved_rows.get("columns", []),
                    "total_rows_count": len(all_rows),
                    "showing_first_50_rows": all_rows[:50]
                }
                data_str = json.dumps(truncated_payload, indent=2, default=str)
            else:
                data_str = json.dumps(retrieved_rows, indent=2, default=str)
        elif isinstance(retrieved_rows, list) and len(retrieved_rows) > 50:
            data_str = json.dumps({
                "total_rows_count": len(retrieved_rows),
                "showing_first_50_rows": retrieved_rows[:50]
            }, indent=2, default=str)
        else:
            data_str = json.dumps(retrieved_rows, indent=2, default=str)
    else:
        data_str = str(retrieved_rows)

    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Answer generator prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    populated_prompt = (
        prompt_template
        .replace("{{retrieved_data}}", data_str)
        .replace("{{user_query}}", cleaned_query)
    )

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
        "temperature": 0.2
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
        with urllib.request.urlopen(req, timeout=45) as resp:
            resp_bytes = resp.read()
            resp_json = json.loads(resp_bytes.decode("utf-8"))
            raw_content = resp_json["choices"][0]["message"]["content"]
            usage = resp_json.get("usage", {})

            # Log interaction to workflow logger
            try:
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name="Node: Answer Generator",
                    agent_name="Answer Generator Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging answer generator interaction: {log_err}")

            answer = _clean_text_response(raw_content)
            return answer

    except Exception as err:
        print(f"[!] Warning in AnswerGeneratorAgent: {err}. Falling back to raw summary.")
        return f"Based on the retrieved data for query '{cleaned_query}':\n{data_str}"
