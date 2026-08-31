import os
import sys
import re
import json
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Import database tools
from databases.tools.get_db_info import fetch_database_info
from databases.tools.postgres_exe_tool import execute_postgres_tool
from databases.tools.mysql_exe_tool import execute_mysql_tool
from databases.tools.oracle_sql_exe_tool import execute_oracle_tool

# Load environment variables
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "retrival_agent.txt"


# ==========================================
# 2. SQL Cleaner
# ==========================================
def _clean_sql_query(raw_response: str) -> str:
    """
    Strips markdown code blocks, backticks, reasoning <think> tags,
    and returns a clean executable SQL query.
    """
    cleaned = raw_response.strip()

    # Strip thinking / reasoning tags (e.g. <think>...</think>)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE).strip()

    # Extract SQL inside ```sql ... ``` or ``` ... ```
    match = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if match:
        cleaned = match.group(1).strip()

    # Strip surrounding backticks and whitespace
    cleaned = cleaned.strip("`").strip()

    # Ensure it starts with SELECT
    select_idx = cleaned.upper().find("SELECT")
    if select_idx != -1:
        cleaned = cleaned[select_idx:]

    return cleaned


def _extract_search_keyword(search_sql: str, reason: str = "", user_query: str = "") -> str:
    """
    Extracts the searched keyword/entity from the generated search SQL,
    verification reason, or original user query.
    """
    # 1. Extract values inside LIKE / ILIKE clauses: '%value%'
    like_matches = re.findall(r"(?:ILIKE|LIKE)\s*'%?([^%'\"]+?)%?'", search_sql, flags=re.IGNORECASE)
    if like_matches:
        seen = set()
        unique_terms = []
        for term in like_matches:
            term = term.strip()
            if term and term not in seen:
                seen.add(term)
                unique_terms.append(term)
        if unique_terms:
            return " ".join(unique_terms)

    # 2. Extract quoted words from reason (e.g., 'cisco phone')
    quoted_in_reason = re.findall(r"['\"]([^'\"]+)['\"]", reason)
    if quoted_in_reason:
        return quoted_in_reason[0].strip()

    # 3. Extract quoted words from user query if present
    quoted_in_query = re.findall(r"['\"]([^'\"]+)['\"]", user_query)
    if quoted_in_query:
        return quoted_in_query[0].strip()

    # 4. Fallback to user query directly
    return user_query.strip()


# ==========================================
# 3. Database Execution Router
# ==========================================
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
        raise ValueError(f"Unsupported database_type '{db_type}' for retrieval execution.")


def _format_rows_as_markdown_table(rows: List[Any]) -> str:
    """
    Formats retrieved database records into a clean markdown table.
    """
    if not rows:
        return ""

    # Check if rows are single column/scalar values
    if all(not isinstance(r, (dict, list, tuple)) for r in rows):
        lines = [
            "| Retrieved Entity Value |",
            "| :--- |"
        ]
        for val in rows:
            lines.append(f"| {str(val).strip()} |")
        return "\n".join(lines)

    # Check if rows are dictionaries
    if isinstance(rows[0], dict):
        headers = list(rows[0].keys())
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join([":---"] * len(headers)) + " |"
        ]
        for row in rows:
            lines.append("| " + " | ".join([str(row.get(h, "")).strip() for h in headers]) + " |")
        return "\n".join(lines)

    # Check if rows are tuples/lists
    if isinstance(rows[0], (list, tuple)):
        num_cols = len(rows[0])
        headers = [f"Column {i+1}" for i in range(num_cols)]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join([":---"] * num_cols) + " |"
        ]
        for row in rows:
            lines.append("| " + " | ".join([str(c).strip() for c in row]) + " |")
        return "\n".join(lines)

    # Fallback
    lines = ["| Retrieved Value |", "| :--- |"]
    for r in rows:
        lines.append(f"| {str(r).strip()} |")
    return "\n".join(lines)


FORBIDDEN_SQL_KEYWORDS = [
    "DELETE", "DROP", "ALTER", "TRUNCATE", "INSERT", "UPDATE",
    "CREATE", "REPLACE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "MERGE", "UPSERT", "ATTACH", "DETACH"
]


def _validate_sql_guardrail(sql_query: str) -> tuple[bool, str]:
    """
    Guardrail: Validates that the generated search SQL query is strictly read-only (SELECT).
    Rejects any query containing mutating/destructive keywords (DELETE, DROP, ALTER, INSERT, UPDATE, etc.).
    """
    if not sql_query or not sql_query.strip():
        return False, "Generated search SQL query is empty."

    # 1. Remove comments (-- and /* */)
    clean_text = re.sub(r"--.*", "", sql_query)
    clean_text = re.sub(r"/\*[\s\S]*?\*/", "", clean_text).strip()

    # 2. Must start with SELECT
    upper_query = clean_text.upper()
    if not upper_query.startswith("SELECT"):
        return False, "Retrieval query must strictly begin with a SELECT statement."

    # 3. Strip string literals ('...') before checking keywords to avoid false positives on search terms
    text_without_literals = re.sub(r"'[^']*'", "''", clean_text)

    # 4. Check for forbidden mutating keywords as whole tokens
    for kw in FORBIDDEN_SQL_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, text_without_literals, re.IGNORECASE):
            return False, f"Forbidden mutating keyword '{kw}' detected in retrieval query. Only read-only SELECT queries are allowed."

    return True, ""


# ==========================================
# 4. Main RetrievalAgent Implementation
# ==========================================
def RetrievalAgent(
    user_query: str,
    llm_prompt_text: str,
    database_id: str,
    reason: str = "",
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """
    Retrieval Agent:
    - Analyzes verification reason and target column.
    - Generates and executes search SQL with strict read-only guardrails.
    - If guardrail fails, re-attempts generation up to `max_attempts` (default: 3) times.
    - Executes query via modular tools (Postgres, MySQL, Oracle).
    - If execution fails, uses SQLRepairAgent to self-heal.
    - If 0 rows returned: returns fallback message "the {word} not found in your database".
    - If >0 rows returned: formats into Markdown table and returns state for SQLWriterAgent.
    """
    print(f"\n[*] [RetrievalAgent] Initiating entity retrieval for query: '{user_query}'")

    # Fetch database type and connection info
    db_info = fetch_database_info(database_id)
    database_type = (db_info.get("database_type") or "SQL").upper()

    # Step 1: Read prompt template
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Prompt template file not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # Read LLM configuration from environment (.env)
    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError("LLM_API_KEY is not set in environment or .env file.")

    if not base_url.endswith("/chat/completions"):
        endpoint_url = f"{base_url}/chat/completions"
    else:
        endpoint_url = base_url

    prompt_warning = ""
    search_sql = ""

    # Step 2: Generate with Guardrail & Re-attempt Loop
    for attempt in range(1, max_attempts + 1):
        populated_prompt = (
            prompt_template
            .replace("{{database_type}}", database_type)
            .replace("{{llm_prompt_text}}", llm_prompt_text)
            .replace("{{reason}}", reason or "Entity/category lookup required.")
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
            "temperature": 0.0
        }

        req_body = json.dumps(request_data).encode("utf-8")
        req = urllib.request.Request(
            endpoint_url,
            data=req_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Kelostats-RetrievalAgent/1.0"
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
                    node_label = f"Node 3B (Attempt {attempt})" if attempt > 1 else "Node 3B"
                    log_agent_call(
                        node_name=node_label,
                        agent_name="Retrieval Agent",
                        llm_input=populated_prompt,
                        llm_output=raw_response,
                        usage=usage
                    )
                except Exception as log_err:
                    print(f"[!] Warning logging retrieval agent interaction: {log_err}")
        except urllib.error.HTTPError as http_err:
            err_msg = http_err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API Error ({http_err.code}): {err_msg}") from http_err

        # Clean and extract generated SQL query
        search_sql = _clean_sql_query(raw_response)
        print(f"[*] [RetrievalAgent] Generated Search SQL (Attempt {attempt}): {search_sql}")

        # Guardrail check
        is_safe, violation_reason = _validate_sql_guardrail(search_sql)
        if is_safe:
            print(f"[+] [RetrievalAgent] Guardrail check PASSED on attempt {attempt}: Search SQL is strictly read-only.")
            break
        else:
            print(f"[!] [RetrievalAgent] Guardrail VIOLATION on attempt {attempt}: {violation_reason}")
            print(f"    Rejected Search Query: {search_sql}")
            if attempt < max_attempts:
                print(f"[*] [RetrievalAgent] Re-attempting search SQL generation ({attempt + 1}/{max_attempts})...")
                prompt_warning = (
                    f"CRITICAL GUARDRAIL ERROR: Your previous search query was REJECTED because: {violation_reason}\n"
                    f"You MUST generate ONLY a safe, read-only SELECT search query. "
                    f"Do NOT include DELETE, ALTER, DROP, INSERT, UPDATE, TRUNCATE, or any mutating statements."
                )
            else:
                raise ValueError(f"Retrieval Guardrail check failed after {max_attempts} attempts: {violation_reason}")

    # Step 3: Execute query using tool based on database_type
    try:
        retrieved_rows = _execute_by_database_type(db_info, search_sql)
        print(f"[*] [RetrievalAgent] Successfully retrieved {len(retrieved_rows)} distinct records.")
    except Exception as db_err:
        print(f"[!] [RetrievalAgent] Database execution error: {db_err}")
        return {
            "status": "EXECUTION_ERROR",
            "error": str(db_err),
            "search_sql": search_sql,
            "database_type": database_type,
            "database_id": database_id
        }

    # Step 4: If execution succeeded with 0 rows, return NOT_FOUND fallback message
    if not retrieved_rows:
        searched_word = _extract_search_keyword(search_sql, reason=reason, user_query=user_query)
        fallback_message = f"the {searched_word} not found in your database"
        print(f"[*] [RetrievalAgent] 0 rows returned: {fallback_message}")
        return {
            "status": "NOT_FOUND",
            "message": fallback_message,
            "search_sql": search_sql,
            "retrieved_values": [],
            "retrieved_markdown_table": "",
            "database_type": database_type,
            "database_id": database_id
        }

    md_table = _format_rows_as_markdown_table(retrieved_rows)

    return {
        "status": "RETRIEVAL_SUCCESS",
        "search_sql": search_sql,
        "retrieved_values": retrieved_rows,
        "retrieved_markdown_table": md_table,
        "database_type": database_type,
        "database_id": database_id
    }


# ==========================================
# 5. Direct Script Test
# ==========================================
if __name__ == "__main__":
    sample_schema = """
DATABASE SCHEMA
Database: kelostats
Dialect: PostgreSQL
TABLE: global_superstore
Columns:
- product_name | TEXT | categorical | distinct: 3788 | samples: "Staples", "Eldon File Cart"
- customer_name | VARCHAR(255) | categorical | distinct: 795 | samples: "Muhammed Yedwab", "Steven Ward"
- sales | NUMERIC(12,4)
"""
    test_db_id = "db_4edfa948-8f02-4508-a3fc-7605da52caf1"
    test_query = "show the total orders for product cisco phone"
    test_reason = "The query asks for a specific product name ('cisco phone') that is not listed in the sample categories for product_name."

    try:
        result = RetrievalAgent(
            user_query=test_query,
            llm_prompt_text=sample_schema,
            database_id=test_db_id,
            reason=test_reason
        )
        print("\n--- RETRIEVAL AGENT RESULT ---")
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"[!] Test notice: {e}")
