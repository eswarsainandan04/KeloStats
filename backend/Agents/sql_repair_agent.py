import os
import sys
import re
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Import schema extractor and database execution tools
from databases.schema_extraction import schema_input
from databases.tools.get_db_info import fetch_database_info
from databases.tools.postgres_exe_tool import execute_postgres_tool
from databases.tools.mysql_exe_tool import execute_mysql_tool
from databases.tools.oracle_sql_exe_tool import execute_oracle_tool

# Load environment variables
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "sql_repair_agent.txt"


def _clean_sql_query(raw_response: str) -> str:
    """
    Strips markdown code blocks, backticks, reasoning <think> tags, or extraneous wrappers
    to return only the clean executable SQL query.
    """
    text = raw_response.strip()

    # Strip reasoning / thinking tags (e.g. <think>...</think>)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # Extract content inside ```sql ... ``` or ``` ... ``` if present
    match = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # Strip surrounding backticks and whitespace
    text = text.strip("`").strip()

    # Ensure it starts with SELECT or WITH
    select_idx = text.upper().find("SELECT")
    with_idx = text.upper().find("WITH")

    start_idx = -1
    if select_idx != -1 and with_idx != -1:
        start_idx = min(select_idx, with_idx)
    elif select_idx != -1:
        start_idx = select_idx
    elif with_idx != -1:
        start_idx = with_idx

    if start_idx != -1:
        text = text[start_idx:]

    return text


def _execute_sql(db_info: Dict[str, Any], sql_query: str) -> List[Any]:
    """
    Executes the repaired SQL query against the target database tool based on database_type.
    """
    db_type = (db_info.get("database_type") or "").lower().strip()

    if db_type in ["postgres", "postgresql"]:
        return execute_postgres_tool(db_info, sql_query)
    elif db_type in ["mysql", "mariadb"]:
        return execute_mysql_tool(db_info, sql_query)
    elif db_type in ["oracle", "oracle_sql"]:
        return execute_oracle_tool(db_info, sql_query)
    else:
        raise ValueError(f"Unsupported database_type '{db_type}' for execution.")


def SQLRepairAgent(
    user_query: str,
    sql_query: str,
    error: str,
    schema: Optional[Union[str, Dict[str, Any]]] = None,
    database_id: Optional[str] = None,
    max_attempts: int = 3,
) -> str:
    """
    SQL Repair Agent:
    - Called when execution of a generated SQL query fails.
    - Receives user_query, sql_query, error, and schema (or database_id).
    - If schema is not provided, extracts schema details using schema_input._schema_to_llm(database_id).
    - Fixes syntax errors, column/table mismatches, invalid joins, missing GROUP BY, dialect quirks,
      or markdown/thinking artifacts.
    - Attempts up to `max_attempts` (default: 3) times until the repaired query executes successfully against the database.
    - Returns the corrected, executable SQL query string.

    :param user_query: Original user natural language request
    :param sql_query: The failed SQL query that triggered the error
    :param error: Error message or traceback caused during execution
    :param schema: Database schema text context or schema dictionary
    :param database_id: Target database ID (used to fetch schema and execute query)
    :param max_attempts: Maximum repair and execution attempts (default: 3)
    :return: Clean, repaired, and executable SQL query string
    """
    print(f"\n[*] [SQLRepairAgent] Initiating repair for failed SQL query...")
    print(f"[*] [SQLRepairAgent] Initial Error: {error}")

    # 1. Resolve Schema Context
    schema_context = ""
    if schema:
        if isinstance(schema, dict):
            schema_context = schema_input.json_to_llm_text(schema)
        else:
            schema_context = str(schema).strip()
    elif database_id:
        try:
            schema_context = schema_input._schema_to_llm(database_id=database_id)
        except Exception as schema_err:
            print(f"[!] [SQLRepairAgent] Warning fetching schema: {schema_err}")
            schema_context = f"Schema Context Unavailable for database_id: {database_id}"
    else:
        schema_context = "No database schema provided."

    # 2. Resolve Database Connection Info
    db_info = None
    database_type = "SQL"
    if database_id:
        try:
            db_info = fetch_database_info(database_id)
            database_type = (db_info.get("database_type") or "SQL").upper()
        except Exception as db_err:
            print(f"[!] [SQLRepairAgent] Warning fetching db_info: {db_err}")

    # 3. Read Prompt Template
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"SQL Repair prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # 4. Read LLM configuration from environment (.env)
    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError("LLM_API_KEY is not set in environment or .env file.")

    if not base_url.endswith("/chat/completions"):
        endpoint_url = f"{base_url}/chat/completions"
    else:
        endpoint_url = base_url

    current_sql = sql_query
    current_error = str(error)
    repaired_sql = current_sql

    # 5. Iterative Repair Loop (Max Attempts)
    for attempt in range(1, max_attempts + 1):
        print(f"\n[*] [SQLRepairAgent] --- Repair Attempt {attempt}/{max_attempts} ---")

        populated_prompt = (
            prompt_template
            .replace("{{database_type}}", database_type)
            .replace("{{schema_context}}", schema_context)
            .replace("{{user_query}}", user_query)
            .replace("{{failed_sql}}", current_sql)
            .replace("{{error_message}}", current_error)
        )

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
                "User-Agent": "Kelostats-SQLRepairAgent/1.0"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_bytes = resp.read()
                resp_json = json.loads(resp_bytes.decode("utf-8"))
                raw_response = resp_json["choices"][0]["message"]["content"]
                usage = resp_json.get("usage", {})

                # Log interaction to active workflow logger
                try:
                    from logs.llm_logger import log_agent_call
                    log_agent_call(
                        node_name=f"Node 4 - Repair Attempt {attempt}",
                        agent_name="SQL Repair Agent",
                        llm_input=populated_prompt,
                        llm_output=raw_response,
                        usage=usage
                    )
                except Exception as log_err:
                    print(f"[!] Warning logging SQL repair interaction: {log_err}")
        except urllib.error.HTTPError as http_err:
            err_msg = http_err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as net_err:
            raise RuntimeError(f"LLM Network Error: {str(net_err)}") from net_err

        # Clean and extract repaired SQL
        repaired_sql = _clean_sql_query(raw_response)
        print(f"[*] [SQLRepairAgent] Attempt {attempt} Repaired SQL:\n{repaired_sql}")

        # If database connection is available, validate by executing the repaired SQL
        if db_info:
            try:
                _execute_sql(db_info, repaired_sql)
                print(f"[+] [SQLRepairAgent] Attempt {attempt}: Repaired SQL executed successfully on {database_type}!")
                return repaired_sql
            except Exception as exe_err:
                current_error = str(exe_err)
                current_sql = repaired_sql
                print(f"[!] [SQLRepairAgent] Attempt {attempt} execution failed: {current_error}")
        else:
            # If no target DB info is supplied, return the repaired SQL directly
            print(f"[+] [SQLRepairAgent] Attempt {attempt}: SQL repaired successfully (Execution skipped - no DB connection).")
            return repaired_sql

    # If all attempts exhausted and still failing
    raise RuntimeError(
        f"SQLRepairAgent failed to repair SQL after {max_attempts} attempts.\n"
        f"Final Repaired SQL: {repaired_sql}\n"
        f"Last Error: {current_error}"
    )


# Alias for alternative spelling
SQLRepairAgennt = SQLRepairAgent


# ==========================================
# Direct Script Test
# ==========================================
if __name__ == "__main__":
    test_db_id = "db_4edfa948-8f02-4508-a3fc-7605da52caf1"
    test_user_query = "show total sales by city"
    test_broken_sql = "SELECT city, SUM(sales_amount) FROM store.global_superstore GROUP BY city"
    test_error = 'column "sales_amount" does not exist'

    print("=" * 60)
    print("Testing SQLRepairAgent")
    print("=" * 60)

    try:
        fixed_sql = SQLRepairAgent(
            user_query=test_user_query,
            sql_query=test_broken_sql,
            error=test_error,
            database_id=test_db_id,
            max_attempts=3
        )
        print("\n" + "=" * 60)
        print("Final Repaired & Verified SQL:")
        print(fixed_sql)
        print("=" * 60)
    except Exception as e:
        print(f"[!] Test execution error: {e}")
