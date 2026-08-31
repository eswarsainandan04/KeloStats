import os
import sys
import json
from pathlib import Path
from typing import TypedDict, Optional, Dict, Any, Union, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from langgraph.graph import StateGraph, END

# Ensure backend root is in sys.path for direct script execution and package imports
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# 1. Observe and import required modules
from Agents.retrival_agent import RetrievalAgent
from Agents.sql_writer_agent import SQLWriterAgent, _execute_and_save_master_data
from Agents.query_verification_agent import QueryVerifyAgent
from Agents.sql_repair_agent import SQLRepairAgent
from databases.schema_extraction import schema_input
from databases.tools.get_db_info import fetch_database_info
from databases.tools.postgres_exe_tool import execute_postgres_tool
from databases.tools.mysql_exe_tool import execute_mysql_tool
from databases.tools.oracle_sql_exe_tool import execute_oracle_tool
from logs.llm_logger import start_workflow_logger

# ==========================================
# 2. Define LangGraph Typed State
# ==========================================
class KelostatsGraphState(TypedDict):
    """
    State passed across LangGraph nodes.
    """
    user_query: str
    database_id: str
    llm_prompt_text: Optional[str]
    verification_status: Optional[str]  # "SCHEMA_MATCH", "RETRIEVAL_REQUIRED", "UNRELATED"
    verification_reason: Optional[str]
    retrieved_markdown_table: Optional[str]  # Markdown table of retrieved entity values
    generated_sql: Optional[str]
    sql_error: Optional[str]
    final_output: Optional[str]
    status: Optional[str]


# ==========================================
# 3. Node Implementations
# ==========================================

def schema_input_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 1: schema_input
    Extracts schema JSON for the specified database_id and converts it to formatted LLM prompt text.
    """
    db_id = state["database_id"]
    print(f"\n[LangGraph - Node 1: Schema Input] Extracting schema for database: '{db_id}'...")

    try:
        # Converts schema JSON to formatted LLM text prompt
        llm_prompt_text = schema_input._schema_to_llm(database_id=db_id)
        return {
            "llm_prompt_text": llm_prompt_text,
            "status": "SCHEMA_EXTRACTED"
        }
    except Exception as err:
        print(f"[!] Error in schema_input_node: {err}")
        # Fallback to empty prompt or raise
        raise RuntimeError(f"Failed to extract schema for database '{db_id}': {str(err)}") from err


def verification_agent_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 2: verification_agent
    Receives extracted schema text and user query, calls verification LLM,
    and classifies query as SCHEMA_MATCH, RETRIEVAL_REQUIRED, or UNRELATED.
    """
    print("\n[LangGraph - Node 2: Verification Agent] Verifying user query against schema context...")
    user_query = state["user_query"]
    llm_prompt_text = state.get("llm_prompt_text") or ""
    db_id = state.get("database_id")

    verification = QueryVerifyAgent(
        user_query=user_query,
        llm_prompt_text=llm_prompt_text,
        database_id=db_id
    )

    status_val = (verification.get("status") or "SCHEMA_MATCH").upper().strip()
    reason_val = verification.get("reason", "No reason provided.")

    print(f"[*] Verification Classification: {status_val} | Reason: {reason_val}")

    return {
        "verification_status": status_val,
        "verification_reason": reason_val,
        "status": f"VERIFIED_{status_val}"
    }


def sql_writer_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 3A: SQLWriterAgent
    Triggered when verification_status == "SCHEMA_MATCH" OR routed from retrieval_agent (with markdown table).
    Translates user query into executable SQL using schema, database dialect, and any retrieved keywords table.
    Executes the query and saves data rows to data/{timestamp}.json.
    If execution fails, sets status to 'REPAIR_REQUIRED' for routing to sql_repair_node in LangGraph.
    """
    print("\n[LangGraph - Node 3A: SQL Writer Node] Generating master SQL query...")
    sql_query = SQLWriterAgent(
        user_query=state["user_query"],
        llm_prompt_text=state.get("llm_prompt_text") or "",
        database_id=state["database_id"],
        retrieved_markdown_table=state.get("retrieved_markdown_table")
    )

    db_id = state.get("database_id")
    if db_id:
        try:
            db_info = fetch_database_info(db_id)
            print(f"[*] [LangGraph - SQL Writer Node] Executing query on {db_info.get('database_type', 'DB')} & saving rows...")
            _execute_and_save_master_data(db_info, sql_query)
            print("[+] [LangGraph - SQL Writer Node] Master SQL query executed and saved data successfully!")
            return {
                "generated_sql": sql_query,
                "final_output": sql_query,
                "status": "SUCCESS_SQL_GENERATED"
            }
        except Exception as exec_err:
            print(f"[!] [LangGraph - SQL Writer Node] SQL Execution failed: {exec_err}")
            print("[*] [LangGraph - SQL Writer Node] Routing to SQLRepairAgent node in LangGraph...")
            return {
                "generated_sql": sql_query,
                "sql_error": str(exec_err),
                "status": "REPAIR_REQUIRED"
            }

    return {
        "generated_sql": sql_query,
        "final_output": sql_query,
        "status": "SUCCESS_SQL_GENERATED"
    }


def sql_repair_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 4: SQLRepairAgent (LangGraph Node)
    Triggered when either master SQL execution or retrieval search SQL execution fails.
    Receives user_query, generated_sql, sql_error, schema, and database_id.
    Attempts up to 3 repair cycles to correct syntax, join, column, or dialect issues.
    """
    print("\n[LangGraph - Node 4: SQL Repair Node] Invoking SQLRepairAgent to auto-repair failed query...")
    db_id = state.get("database_id")
    user_query = state["user_query"]
    sql_query = state.get("generated_sql") or ""
    sql_error = state.get("sql_error") or "Unknown execution error"
    schema_text = state.get("llm_prompt_text")
    is_retrieval_repair = (state.get("status") == "RETRIEVAL_REPAIR_REQUIRED")

    try:
        repaired_sql = SQLRepairAgent(
            user_query=user_query,
            sql_query=sql_query,
            error=sql_error,
            schema=schema_text,
            database_id=db_id,
            max_attempts=3
        )

        if not db_id:
            return {
                "generated_sql": repaired_sql,
                "final_output": repaired_sql,
                "status": "SUCCESS_SQL_REPAIRED"
            }

        db_info = fetch_database_info(db_id)

        # Case A: Retrieval repair -> re-execute search SQL and format markdown table
        if is_retrieval_repair:
            from Agents.retrival_agent import _execute_by_database_type, _format_rows_as_markdown_table, _extract_search_keyword
            print(f"[*] [LangGraph - SQL Repair Node] Executing repaired retrieval search query...")
            retrieved_rows = _execute_by_database_type(db_info, repaired_sql)
            if not retrieved_rows:
                searched_word = _extract_search_keyword(repaired_sql, user_query=user_query)
                fallback_msg = f"the {searched_word} not found in your database"
                return {
                    "final_output": fallback_msg,
                    "retrieved_markdown_table": None,
                    "status": "NOT_FOUND"
                }
            md_table = _format_rows_as_markdown_table(retrieved_rows)
            return {
                "retrieved_markdown_table": md_table,
                "status": "RETRIEVAL_SUCCESS"
            }

        # Case B: Master SQL repair -> re-execute and save data rows to data/{timestamp}.json
        print(f"[*] [LangGraph - SQL Repair Node] Executing repaired master SQL & saving data rows...")
        _execute_and_save_master_data(db_info, repaired_sql)
        print("[+] [LangGraph - SQL Repair Node] Repaired SQL executed and saved data successfully!")

        return {
            "generated_sql": repaired_sql,
            "final_output": repaired_sql,
            "status": "SUCCESS_SQL_REPAIRED"
        }
    except Exception as repair_err:
        print(f"[!] [LangGraph - SQL Repair Node] SQL Repair failed after retries: {repair_err}")
        return {
            "final_output": f"SQL Execution & Repair Failed: {str(repair_err)}",
            "status": "SQL_EXECUTION_FAILED"
        }


def retrieval_agent_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 3B: RetrievalAgent
    Triggered when verification_status == "RETRIEVAL_REQUIRED".
    Handles lookups for specific entities/category values.
    - If execution error occurs: sets status to RETRIEVAL_REPAIR_REQUIRED to route to sql_repair
    - If 0 rows returned: returns fallback NOT_FOUND message
    - If >0 rows returned: captures markdown table and prepares state for sql_writer
    """
    print("\n[LangGraph - Node 3B: Retrieval Agent] Performing entity/value retrieval...")
    retrieval_response = RetrievalAgent(
        user_query=state["user_query"],
        llm_prompt_text=state.get("llm_prompt_text") or "",
        database_id=state["database_id"],
        reason=state.get("verification_reason") or ""
    )

    # 1. Handle SQL execution error -> route to SQLRepairAgent in LangGraph
    if isinstance(retrieval_response, dict) and retrieval_response.get("status") == "EXECUTION_ERROR":
        print("[*] [LangGraph - Retrieval Node] Search SQL error detected. Routing to SQLRepairAgent in LangGraph...")
        return {
            "generated_sql": retrieval_response.get("search_sql"),
            "sql_error": retrieval_response.get("error"),
            "status": "RETRIEVAL_REPAIR_REQUIRED"
        }

    # 2. Handle true 0-row result (clean execution, but entity not present in database)
    if isinstance(retrieval_response, dict) and retrieval_response.get("status") == "NOT_FOUND":
        return {
            "final_output": retrieval_response.get("message", "the requested item not found in your database"),
            "retrieved_markdown_table": None,
            "status": "NOT_FOUND"
        }

    # 3. Extract formatted markdown table for >0 rows
    md_table = ""
    if isinstance(retrieval_response, dict):
        md_table = retrieval_response.get("retrieved_markdown_table") or ""

    print(f"[*] [LangGraph - Retrieval Node] Formatted retrieved values into Markdown table:\n{md_table}")

    return {
        "retrieved_markdown_table": md_table,
        "status": "RETRIEVAL_SUCCESS"
    }


def unrelated_query_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 3C: Fallback / Rejection
    Triggered when verification_status == "UNRELATED" or unresolvable.
    Returns explanation of why the query cannot be processed.
    """
    print("\n[LangGraph - Node 3C: Rejection Fallback] Query unrelated or unresolvable with schema.")
    reason = state.get("verification_reason", "The query does not match the database schema.")
    rejection_message = (
        f"Query Verification Failed: The requested query cannot be processed with the available database schema.\n"
        f"Reason: {reason}"
    )

    return {
        "final_output": rejection_message,
        "status": "REJECTED_UNRELATED"
    }


# ==========================================
# 4. Conditional Edge Routers
# ==========================================

def decide_verification_route(state: KelostatsGraphState) -> str:
    """
    Decides the next node based on verification_status.
    """
    status_val = (state.get("verification_status") or "").upper().strip()

    if status_val == "SCHEMA_MATCH":
        return "sql_writer"
    elif status_val == "RETRIEVAL_REQUIRED":
        return "retrieval_agent"
    else:
        return "unrelated_query"


def decide_retrieval_route(state: KelostatsGraphState) -> str:
    """
    Decides the route after retrieval_agent_node:
    - If execution error occurred: routes to sql_repair
    - If 0 rows were found (status == "NOT_FOUND"): ends graph with fallback message
    - If rows were found (>0 rows): routes to sql_writer node to generate master SQL query
    """
    status_val = (state.get("status") or "").upper().strip()
    if status_val == "RETRIEVAL_REPAIR_REQUIRED":
        return "sql_repair"
    elif status_val == "NOT_FOUND":
        return "end"
    return "sql_writer"


def decide_sql_writer_route(state: KelostatsGraphState) -> str:
    """
    Decides the route after sql_writer_node:
    - If execution failed (status == "REPAIR_REQUIRED"): routes to sql_repair node in LangGraph
    - If execution succeeded: routes to END
    """
    status_val = (state.get("status") or "").upper().strip()
    if status_val == "REPAIR_REQUIRED":
        return "sql_repair"
    return "end"


def decide_sql_repair_route(state: KelostatsGraphState) -> str:
    """
    Decides the route after sql_repair_node:
    - If repaired from retrieval (status == "RETRIEVAL_SUCCESS"): routes to sql_writer
    - Otherwise (master SQL repaired or failed): routes to END
    """
    status_val = (state.get("status") or "").upper().strip()
    if status_val == "RETRIEVAL_SUCCESS":
        return "sql_writer"
    return "end"


# ==========================================
# 5. Build and Compile LangGraph Workflow
# ==========================================

def build_kelostats_workflow():
    """
    Assembles the StateGraph with:
    1. schema_input (extracts schema.json to text)
    2. verification_agent (verifies query vs schema)
    3. Conditional Branch:
       - SCHEMA_MATCH -> sql_writer
       - RETRIEVAL_REQUIRED -> retrieval_agent
           - Execution error -> sql_repair -> sql_writer (or END if 0 rows)
           - 0 rows (NOT_FOUND) -> END (fallback message)
           - >0 rows -> sql_writer (with markdown table)
       - UNRELATED / Other -> unrelated_query -> END
    4. sql_writer:
       - If execution succeeds -> END
       - If execution fails (REPAIR_REQUIRED) -> sql_repair -> END
    """
    workflow = StateGraph(KelostatsGraphState)

    # 1. Add all nodes
    workflow.add_node("schema_input", schema_input_node)
    workflow.add_node("verification_agent", verification_agent_node)
    workflow.add_node("sql_writer", sql_writer_node)
    workflow.add_node("retrieval_agent", retrieval_agent_node)
    workflow.add_node("sql_repair", sql_repair_node)
    workflow.add_node("unrelated_query", unrelated_query_node)

    # 2. Set entry point
    workflow.set_entry_point("schema_input")

    # 3. Connect schema_input to verification_agent
    workflow.add_edge("schema_input", "verification_agent")

    # 4. Add conditional routing edges from verification_agent
    workflow.add_conditional_edges(
        "verification_agent",
        decide_verification_route,
        {
            "sql_writer": "sql_writer",
            "retrieval_agent": "retrieval_agent",
            "unrelated_query": "unrelated_query"
        }
    )

    # 5. Add conditional routing edges from retrieval_agent:
    workflow.add_conditional_edges(
        "retrieval_agent",
        decide_retrieval_route,
        {
            "sql_repair": "sql_repair",
            "sql_writer": "sql_writer",
            "end": END
        }
    )

    # 6. Add conditional routing edges from sql_writer:
    workflow.add_conditional_edges(
        "sql_writer",
        decide_sql_writer_route,
        {
            "sql_repair": "sql_repair",
            "end": END
        }
    )

    # 7. Add conditional routing edges from sql_repair:
    workflow.add_conditional_edges(
        "sql_repair",
        decide_sql_repair_route,
        {
            "sql_writer": "sql_writer",
            "end": END
        }
    )

    workflow.add_edge("unrelated_query", END)

    return workflow.compile()


# Compile graph instance
kelostats_graph = build_kelostats_workflow()


def run_orchestrator(user_query: str, database_id: str) -> Dict[str, Any]:
    """
    Programmatic entry point to invoke the LangGraph orchestrator.
    Starts a workflow log session to record each agent interaction to logs/llm_logs/workflow Log {timestamp}.txt
    """
    logger_session = start_workflow_logger()

    initial_state: KelostatsGraphState = {
        "user_query": user_query,
        "database_id": database_id,
        "llm_prompt_text": None,
        "verification_status": None,
        "verification_reason": None,
        "retrieved_markdown_table": None,
        "final_output": None,
        "status": "INITIALIZED"
    }

    try:
        result = kelostats_graph.invoke(initial_state)
        return result
    finally:
        log_file = logger_session.save()
        print(f"[+] [LangGraph Orchestrator] Workflow log saved to: {log_file}")


# ==========================================
# 6. FastAPI Router for API Integration
# ==========================================
router = APIRouter(tags=["LangGraph Orchestrator"])


class QueryWorkflowRequest(BaseModel):
    user_query: str
    database_id: Optional[str] = None
    db_id: Optional[str] = None


@router.post("/api/workflow/query", summary="Run LangGraph workflow for user query and database")
def workflow_query_endpoint(payload: QueryWorkflowRequest):
    """
    POST /api/workflow/query
    Runs LangGraph:
    1. schema_input: extracts schema.json -> text
    2. verification_agent: verifies query
    3. Branches to SQLWriterAgent, RetrievalAgent, or rejection.
    """
    target_db_id = payload.database_id or payload.db_id
    if not target_db_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required field 'database_id' in request payload."
        )

    if not payload.user_query or not payload.user_query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required field 'user_query' in request payload."
        )

    try:
        graph_result = run_orchestrator(
            user_query=payload.user_query,
            database_id=target_db_id
        )

        return {
            "status": graph_result.get("status"),
            "verification_status": graph_result.get("verification_status"),
            "verification_reason": graph_result.get("verification_reason"),
            "output": graph_result.get("final_output"),
            "database_id": target_db_id
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LangGraph execution failed: {str(exc)}"
        )


# ==========================================
# 7. Direct Script Test
# ==========================================
if __name__ == "__main__":
    test_db_id = "db_4edfa948-8f02-4508-a3fc-7605da52caf1"
    test_query = "show me total sales by city"

    print("=" * 60)
    print("Testing Kelostats LangGraph Orchestrator")
    print(f"Database ID: {test_db_id}")
    print(f"User Query:  {test_query}")
    print("=" * 60)

    try:
        output_state = run_orchestrator(
            user_query=test_query,
            database_id=test_db_id
        )
        print("\n" + "=" * 60)
        print("LangGraph Execution Completed Successfully!")
        print(f"Final Status:       {output_state.get('status')}")
        print(f"Verification:       {output_state.get('verification_status')}")
        print(f"Verification Note:  {output_state.get('verification_reason')}")
        print("Final Output:")
        print(output_state.get("final_output"))
        print("=" * 60)
    except Exception as test_err:
        print(f"\n[!] Test Execution Notice: {test_err}")
