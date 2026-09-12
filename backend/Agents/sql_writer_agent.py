import os
import sys
import json
import re
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, Any, List

from sqlalchemy import create_engine, text

from dotenv import load_dotenv

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Import database execution tools
from databases.tools.postgres_exe_tool import execute_postgres_tool
from databases.tools.mysql_exe_tool import execute_mysql_tool
from databases.tools.oracle_sql_exe_tool import execute_oracle_tool

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
app_db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "sql_writer_prompt.txt"


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

    # Strip surrounding backticks if any
    text = text.strip("`").strip()
    return text


def _extract_datababase_type(database_id: str) -> str:
    """
    Fetches the database dialect from the user_databases table using database_id.
    """
    if not database_id or not str(database_id).strip():
        raise ValueError("database_id is required to extract database_type.")

    clean_id = str(database_id).strip()
    formatted_id = clean_id if clean_id.startswith("db_") else f"db_{clean_id}"
    
    query = text("""
        SELECT database_type FROM user_databases 
        WHERE db_id = :db_id OR db_id = :raw_id 
        LIMIT 1;
    """)
    
    with app_db_engine.connect() as conn:
        result = conn.execute(query, {"db_id": formatted_id, "raw_id": clean_id}).scalar()
        if result:
            return str(result).strip()

    raise ValueError(f"Database with id '{database_id}' not found in user_databases.")


FORBIDDEN_SQL_KEYWORDS = [
    "DELETE", "DROP", "ALTER", "TRUNCATE", "INSERT", "UPDATE",
    "CREATE", "REPLACE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "MERGE", "UPSERT", "ATTACH", "DETACH"
]


def _validate_sql_guardrail(sql_query: str) -> tuple[bool, str]:
    """
    Guardrail: Validates that the generated SQL query is strictly read-only (SELECT / WITH).
    Rejects any query containing mutating/destructive keywords (DELETE, DROP, ALTER, INSERT, UPDATE, etc.).
    """
    if not sql_query or not sql_query.strip():
        return False, "Generated SQL query is empty."

    # 1. Remove comments (-- and /* */)
    clean_text = re.sub(r"--.*", "", sql_query)
    clean_text = re.sub(r"/\*[\s\S]*?\*/", "", clean_text).strip()

    # 2. Must start with SELECT or WITH
    upper_query = clean_text.upper()
    if not (upper_query.startswith("SELECT") or upper_query.startswith("WITH")):
        return False, "Query must strictly begin with a SELECT or WITH statement."

    # 3. Strip string literals ('...') before checking keywords to avoid false positives on values
    text_without_literals = re.sub(r"'[^']*'", "''", clean_text)

    # 4. Check for forbidden mutating keywords as whole tokens
    for kw in FORBIDDEN_SQL_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, text_without_literals, re.IGNORECASE):
            return False, f"Forbidden mutating keyword '{kw}' detected. Only read-only SELECT queries are allowed."

    return True, ""


def _execute_by_database_type(db_info: Dict[str, Any], sql_query: str) -> List[Any]:
    """
    Routes execution to the correct database execution tool in databases/tools/.
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


def _execute_and_save_master_data(db_info: Dict[str, Any], sql_query: str) -> Dict[str, Any]:
    """
    Executes the master SQL query against the target database using the execution tools,
    formats the retrieved rows as a dictionary with 'columns' and 'rows' list of dicts,
    and saves it to: backend/data/{timestamp}.json
    """
    raw_records = _execute_by_database_type(db_info, sql_query)

    dict_rows = []
    for record in raw_records:
        if isinstance(record, dict):
            clean_dict = {}
            for col, val in record.items():
                if hasattr(val, "isoformat"):
                    clean_dict[col] = val.isoformat()
                elif isinstance(val, Decimal):
                    clean_dict[col] = float(val)
                else:
                    clean_dict[col] = val
            dict_rows.append(clean_dict)
        elif isinstance(record, (list, tuple)):
            row_dict = {}
            for idx, val in enumerate(record):
                col_name = f"col_{idx}"
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                elif isinstance(val, Decimal):
                    val = float(val)
                row_dict[col_name] = val
            dict_rows.append(row_dict)
        else:
            val = record
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            elif isinstance(val, Decimal):
                val = float(val)
            dict_rows.append({"value": val})

    columns = list(dict_rows[0].keys()) if dict_rows else []

    # Save to backend/data/{timestamp}.json
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    json_path = data_dir / f"{timestamp_str}.json"

    data_payload = {
        "columns": columns,
        "rows": dict_rows
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data_payload, f, indent=2, default=str)

    print(f"[+] [SQLWriterAgent] Saved {len(dict_rows)} retrieved data rows to: data/{timestamp_str}.json")
    return data_payload


def SQLWriterAgent(
    user_query: str,
    llm_prompt_text: str,
    database_id: str,
    retrieved_markdown_table: Optional[str] = None,
    max_attempts: int = 3,
) -> str:
    """
    SQL Writer Agent:
    - Loads prompt from prompts/sql_writer_prompt.txt
    - Formats prompt with retrieved schema context, user query, database dialect,
      and any retrieved search keywords markdown table
    - Calls the LLM configured in .env (e.g., Groq LPU API)
    - Applies a strict read-only Guardrail: rejects DELETE, ALTER, DROP, INSERT, UPDATE, etc.
    - If guardrail fails, re-attempts generation up to `max_attempts` (default: 3) times.
    - Executes the verified query on the database and saves retrieved rows to data/{timestamp}.json
    - Returns only the verified, clean executable master SQL query string.

    :param user_query: User's natural language request (e.g. 'Show total sales by month')
    :param llm_prompt_text: Extracted database schema text representation
    :param database_id: Target database ID to look up database_type
    :param retrieved_markdown_table: Optional markdown table of verified entity values from retrieval agent
    :param max_attempts: Maximum retry attempts if guardrail validation fails (default: 3)
    :return: Clean executable master SQL query string
    """
    database_type = _extract_datababase_type(database_id)

    # 1. Read prompt template
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Prompt template file not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # 2. Build retrieved values section if markdown table is available
    if retrieved_markdown_table and str(retrieved_markdown_table).strip():
        retrieved_section = (
            "\nRetrieved Search Keywords Table:\n"
            "The following table contains verified matching search keywords retrieved directly from the database table. "
            "This table is used in WHERE condition because those search keywords are available in the db table "
            "and are supportable to write a master SQL query:\n\n"
            f"{str(retrieved_markdown_table).strip()}\n"
        )
    else:
        retrieved_section = ""

    # 3. Read LLM configuration from environment (.env)
    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError("LLM_API_KEY is not set in environment or .env file.")

    # Normalize endpoint URL to OpenAI-compatible /chat/completions
    if not base_url.endswith("/chat/completions"):
        endpoint_url = f"{base_url}/chat/completions"
    else:
        endpoint_url = base_url

    prompt_warning = ""

    # 4. Generate with Guardrail & Re-attempt Loop
    for attempt in range(1, max_attempts + 1):
        populated_prompt = (
            prompt_template
            .replace("{{database_type}}", database_type)
            .replace("{{llm_prompt_text}}", llm_prompt_text)
            .replace("{{retrieved_values_section}}", retrieved_section)
            .replace("{{user_query}}", user_query)
        )
        if prompt_warning:
            populated_prompt += f"\n\n{prompt_warning}"

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
                raw_sql = resp_json["choices"][0]["message"]["content"]
                usage = resp_json.get("usage", {})

                # Log interaction to active workflow logger
                try:
                    from logs.llm_logger import log_agent_call
                    node_label = f"Node 3A (Attempt {attempt})" if attempt > 1 else "Node 3A"
                    log_agent_call(
                        node_name=node_label,
                        agent_name="SQL Writer Agent",
                        llm_input=populated_prompt,
                        llm_output=raw_sql,
                        usage=usage
                    )
                except Exception as log_err:
                    print(f"[!] Warning logging SQL writer interaction: {log_err}")

                sql_query = _clean_sql_query(raw_sql)

        except urllib.error.HTTPError as http_err:
            err_msg = http_err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as err:
            raise RuntimeError(f"Failed to generate SQL query: {str(err)}") from err

        # 5. Apply Strict Read-Only Guardrail
        is_safe, violation_reason = _validate_sql_guardrail(sql_query)
        if is_safe:
            print(f"[+] [SQLWriterAgent] Guardrail check PASSED on attempt {attempt}: SQL is strictly read-only.")
            return sql_query
        else:
            print(f"[!] [SQLWriterAgent] Guardrail VIOLATION on attempt {attempt}: {violation_reason}")
            print(f"    Rejected Query: {sql_query}")
            if attempt < max_attempts:
                print(f"[*] [SQLWriterAgent] Re-attempting SQL generation ({attempt + 1}/{max_attempts})...")
                prompt_warning = (
                    f"CRITICAL GUARDRAIL ERROR: Your previous SQL query was REJECTED because: {violation_reason}\n"
                    f"You MUST generate ONLY a safe, read-only SELECT query. "
                    f"Do NOT include DELETE, ALTER, DROP, INSERT, UPDATE, TRUNCATE, or any mutating statements."
                )

    raise ValueError(f"SQL Guardrail check failed after {max_attempts} attempts: {violation_reason}")

if __name__ == "__main__":
    sample_schema = """

    """
    user_query = "how many products are there for name Cisco Phone ?"
    
    try:
        sql = SQLWriterAgent(
            user_query=user_query,
            llm_prompt_text=sample_schema,
            database_id="db_4edfa948-8f02-4508-a3fc-7605da52caf1"
        )
        print("Generated SQL Query:")
        print("--------------------")
        print(sql)
    except Exception as e:
        print(f"Error: {e}")



