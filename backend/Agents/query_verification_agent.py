import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "query_verfication.txt"




def _clean_json_response(raw_response: str) -> str:
    """
    Strips markdown code blocks, reasoning <think> tags, and extracts clean JSON.
    """
    text = raw_response.strip()

    # Strip reasoning / thinking tags (e.g. <think>...</think>)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # Extract JSON inside ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # Find first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    return text


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
        "temperature": 0.1
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

            cleaned_json = _clean_json_response(raw_content)
            verification_result = json.loads(cleaned_json)
    except urllib.error.HTTPError as http_err:
        err_msg = http_err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API Error ({http_err.code}): {err_msg}") from http_err
    except Exception as err:
        print(f"[!] Warning parsing verification result: {err}. Defaulting to SCHEMA_MATCH.")
        return {
            "status": "SCHEMA_MATCH",
            "reason": f"Fallback due to verification parse warning: {str(err)}"
        }

    status = (verification_result.get("status") or "").upper().strip()
    if status != "RETRIEVAL_REQUIRED":
        status = "SCHEMA_MATCH"
    reason = verification_result.get("reason", "No reason provided.")

    return {
        "status": status,
        "reason": reason
    }


if __name__ == "__main__":
    sample_schema = """

DATABASE SCHEMA

Database: kelostats
Dialect: PostgreSQL
Schema: store

TABLE: global_superstore
Rows: 51290

Columns:
- row_id | INTEGER | PK | not_null | range: 1-51290 | samples: 32298, 26341, 25330, 13524, 47221
- order_id | VARCHAR(100) | categorical | unique: 48.81% | distinct: 25035 | categories: "CA-2014-100111", "TO-2014-9950", "MX-2014-166541", "IN-2013-42311", "IN-2012-41261",..+25030
- order_date | DATE | unique: 2.79% | range: "2011-01-01"-"2014-12-31" | samples: "2012-07-31", "2013-02-05", "2013-10-17", "2013-01-28", "2013-11-05"
- ship_date | DATE | unique: 2.85% | range: "2011-01-03"-"2015-01-07" | samples: "2012-07-31", "2013-02-07", "2013-10-18", "2013-01-30", "2013-11-06"
- ship_mode | VARCHAR(50) | categorical | unique: 0.01% | distinct: 4 | categories: "Standard Class", "Second Class", "First Class", "Same Day"
- customer_id | VARCHAR(50) | categorical | unique: 3.1% | distinct: 1590 | categories: "PO-18850", "BE-11335", "JG-15805", "SW-20755", "EM-13960",..+1585
- customer_name | VARCHAR(255) | categorical | unique: 1.55% | distinct: 795 | categories: "Muhammed Yedwab", "Steven Ward", "Gary Hwang", "Bill Eplett", "Patrick O'Brill",..+790
- segment | VARCHAR(50) | categorical | unique: 0.01% | distinct: 3 | categories: "Consumer", "Corporate", "Home Office"
- city | VARCHAR(150) | categorical | unique: 7.09% | distinct: 3636 | categories: "New York City", "Los Angeles", "Philadelphia", "San Francisco", "Santo Domingo",..+3631
- state | VARCHAR(150) | categorical | unique: 2.13% | distinct: 1094 | categories: "California", "England", "New York", "Texas", "Ile-de-France",..+1089
- country | VARCHAR(150) | categorical | unique: 0.29% | distinct: 147 | categories: "United States", "Australia", "France", "Mexico", "Germany",..+142
- postal_code | VARCHAR(50) | unique: 1.23% | range: 10009.0-99301.0 | samples: "10024.0", "95823.0", "28027.0", "22304.0", "42420.0"
- market | VARCHAR(50) | categorical | unique: 0.01% | distinct: 7 | categories: "APAC", "LATAM", "EU", "US", "EMEA",..+2
- region | VARCHAR(100) | categorical | unique: 0.03% | distinct: 13 | categories: "Central", "South", "EMEA", "North", "Africa",..+8
- product_id | VARCHAR(100) | categorical | unique: 20.07% | distinct: 10292 | categories: "OFF-AR-10003651", "OFF-AR-10003829", "OFF-BI-10003708", "OFF-BI-10002799", "FUR-CH-10003354",..+10287
- category | VARCHAR(100) | categorical | unique: 0.01% | distinct: 3 | categories: "Office Supplies", "Technology", "Furniture"
- sub_category | VARCHAR(100) | categorical | unique: 0.03% | distinct: 17 | categories: "Binders", "Storage", "Art", "Paper", "Chairs",..+12
- product_name | TEXT | categorical | unique: 7.39% | distinct: 3788 | categories: "Staples", "Cardinal Index Tab, Clear", "Eldon File Cart, Single Width", "Rogers File Cart, Single Width", "Ibico Index Tab, Clear",..+3783
- sales | NUMERIC(12,4) | unique: 44.83% | range: 0.444-22638.48 | samples: 2309.65, 3709.395, 5175.171, 2892.51, 2832.96
- quantity | INTEGER | unique: 0.03% | range: 1-14 | samples: 7, 9, 9, 5, 8
- discount | NUMERIC(6,4) | unique: 0.05% | range: 0-0.85 | samples: 0, 0.1, 0.1, 0.1, 0
- profit | NUMERIC(12,4) | unique: 47.91% | range: -6599.978-8399.976 | samples: 762.1845, -288.765, 919.971, -96.54, 311.52
- shipping_cost | NUMERIC(12,4) | unique: 19.57% | range: 0-933.57 | samples: 933.57, 923.63, 915.49, 910.16, 903.04
- order_priority | VARCHAR(50) | categorical | unique: 0.01% | distinct: 4 | categories: "Medium", "High", "Critical", "Low"

"""
    db_id = "db_4edfa948-8f02-4508-a3fc-7605da52caf1"


    question = "show the total orders for product cisco phone"
    res2 = QueryVerifyAgent(user_query=question, llm_prompt_text=sample_schema, database_id=db_id)
    print(res2)
