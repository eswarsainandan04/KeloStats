import os
import sys
import json
import re
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
from Agents.query_classication_agent import (
    QueryClassificationAgent,
    handle_greet,
    handle_out_of_scope
)
from Agents.quey_decision_agent import QueryDecisionAgent
from Agents.answer_generator_agent import AnswerGeneratorAgent
from Agents.ppt_generation_agent import (
    PPTGenerationAgent,
    GetHTMLCode,
    is_empty_slide,
    save_slide_to_s3
)
from Agents.validate_html_code_agent import ValidateHTMLCodeAgent
from workspace.chat import save_chat_message
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
    database_id: Optional[str]
    project_id: Optional[str]
    user_id: Optional[str]
    slide_number: Optional[int]
    classification_intent: Optional[str]  # "greet" | "out_of_scope" | "in_scope"
    classification_reason: Optional[str]
    decision: Optional[str]               # "normal_qa" | "agent"
    decision_reason: Optional[str]
    llm_prompt_text: Optional[str]
    verification_status: Optional[str]  # "SCHEMA_MATCH" | "RETRIEVAL_REQUIRED"
    verification_reason: Optional[str]
    retrieved_markdown_table: Optional[str]  # Markdown table of retrieved entity values
    generated_sql: Optional[str]
    sql_error: Optional[str]
    retrieved_data: Optional[Dict[str, Any]]
    retrieved_rows_count: Optional[int]
    generated_slide_html: Optional[str]
    final_output: Optional[str]
    status: Optional[str]


# ==========================================
# 3. Node Implementations
# ==========================================

def save_user_message_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Initial Node: Saves user query to chat_messages table (role: 'User') before classification.
    """
    project_id = state.get("project_id")
    user_query = state.get("user_query") or ""
    print(f"\n[LangGraph - Entry: Save User Message] Persisting User message for project '{project_id}'...")

    if project_id:
        save_chat_message(project_id=project_id, role="User", message=user_query)

    return {
        "status": "USER_MESSAGE_RECORDED"
    }


def query_classification_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 0A: QueryClassificationAgent
    Classifies the user query as 'greet', 'out_of_scope', or 'in_scope'.
    """
    user_query = state.get("user_query") or ""
    print(f"\n[LangGraph - Node 0A: Query Classification] Classifying intent for query: '{user_query}'...")

    classification = QueryClassificationAgent(user_query=user_query)
    intent = classification.get("intent", "in_scope").lower().strip()
    reason = classification.get("reason", "")
    print(f"[*] [LangGraph - Node 0A] Classification Result: intent='{intent}' | reason='{reason}'")

    return {
        "classification_intent": intent,
        "classification_reason": reason,
        "status": f"INTENT_{intent.upper()}"
    }


def handle_greet_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Handles greeting intent and returns a welcoming Copilot response generated dynamically by LLM.
    """
    user_query = state.get("user_query") or ""
    print(f"\n[LangGraph - Greeting Handler] Generating dynamic greeting response for query: '{user_query}'...")
    greeting_message = handle_greet(user_query=user_query)
    return {
        "final_output": greeting_message,
        "status": "GREETING_COMPLETED"
    }


def handle_out_of_scope_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Handles out-of-scope queries by explaining domain boundaries dynamically via LLM.
    """
    user_query = state.get("user_query") or ""
    print(f"\n[LangGraph - Out of Scope Handler] Generating dynamic out-of-scope response for query: '{user_query}'...")
    out_of_scope_message = handle_out_of_scope(user_query=user_query)
    return {
        "final_output": out_of_scope_message,
        "status": "OUT_OF_SCOPE_REJECTED"
    }


def query_decision_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 0B: QueryDecisionAgent
    Classifies in-scope query into:
    - 'normal_qa': Direct question/inquiry asking for numbers or metrics
    - 'agent': Action command or directive to create/generate presentation slides
    """
    user_query = state.get("user_query") or ""
    print(f"\n[LangGraph - Node 0B: Query Decision] Classifying task type (normal_qa vs agent)...")

    decision_res = QueryDecisionAgent(user_query=user_query)
    decision = decision_res.get("decision", "normal_qa").lower().strip()
    reason = decision_res.get("reason", "")
    print(f"[*] [LangGraph - Node 0B] Decision Result: decision='{decision}' | reason='{reason}'")

    return {
        "decision": decision,
        "decision_reason": reason,
        "status": f"DECISION_{decision.upper()}"
    }


def schema_input_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 1: schema_input
    Extracts schema JSON for the specified database_id and converts it to formatted LLM prompt text.
    """
    db_id = state.get("database_id")
    if not db_id:
        raise RuntimeError("Missing required field 'database_id' to extract schema for in-scope queries.")

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
            data_payload = _execute_and_save_master_data(db_info, sql_query)
            rows_count = len(data_payload.get("rows", [])) if isinstance(data_payload, dict) else 0
            print(f"[+] [LangGraph - SQL Writer Node] Master SQL query executed and saved {rows_count} data rows successfully!")
            return {
                "generated_sql": sql_query,
                "final_output": sql_query,
                "retrieved_data": data_payload,
                "retrieved_rows_count": rows_count,
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
        "retrieved_data": None,
        "retrieved_rows_count": 0,
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
        data_payload = _execute_and_save_master_data(db_info, repaired_sql)
        rows_count = len(data_payload.get("rows", [])) if isinstance(data_payload, dict) else 0
        print(f"[+] [LangGraph - SQL Repair Node] Repaired SQL executed and saved {rows_count} data rows successfully!")

        return {
            "generated_sql": repaired_sql,
            "final_output": repaired_sql,
            "retrieved_data": data_payload,
            "retrieved_rows_count": rows_count,
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


def answer_generator_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 5: AnswerGeneratorAgent
    Triggered when decision == 'normal_qa' and retrieved_rows_count > 0.
    Generates a concise paragraph or bullet points answering user query based strictly on retrieved SQL rows.
    """
    print("\n[LangGraph - Node 5: Answer Generator Node] Synthesizing natural answer from retrieved data...")
    retrieved_data = state.get("retrieved_data") or {}
    user_query = state.get("user_query") or ""

    answer_text = AnswerGeneratorAgent(
        retrieved_rows=retrieved_data,
        user_query=user_query
    )
    print("[+] [LangGraph - Answer Generator Node] Natural answer generated successfully!")

    return {
        "final_output": answer_text,
        "status": "SUCCESS_ANSWER_GENERATED"
    }


def ppt_generation_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 6: PPTGenerationAgent
    Triggered when decision == 'agent'.
    1. Existing SQL workflow has already executed and populated state['retrieved_data'].
    2. Calls GetHTMLCode(project_id, slide_number, user_id) from S3: workspace/{user_id}/{project_id}/slides/slide_{slide_number:02d}.html
       - Case 1 (Empty Slide): If current slide is empty ppt slide (no content in canvas),
         retrieves previous slide code (slide_{slide_number - 1:02d}.html) and sends it as template to LLM.
       - Case 2 (Slide with Content): If current slide has content,
         sends current slide code (slide_{slide_number:02d}.html) as template to LLM.
    3. Invokes PPTGenerationAgent(user_query, retrieved_rows, slide_number, project_id, user_id)
       to generate HTML slide and replaces the existing code at:
       workspace/{user_id}/{project_id}/slides/slide_{slide_number:02d}.html in Supabase S3.
    4. Sets final_output to a friendly chat confirmation (DO NOT return raw HTML code in chat!).
    """
    user_query = state.get("user_query") or ""
    retrieved_data = state.get("retrieved_data") or {}
    slide_number = int(state.get("slide_number") or 1)
    project_id = state.get("project_id")
    user_id = state.get("user_id")

    print(f"\n[LangGraph - Node 6: PPT Generation Node] Processing Slide {slide_number}...")

    # 1. Retrieve current slide code from S3
    current_html = GetHTMLCode(project_id=project_id, slide_number=slide_number, user_id=user_id) if project_id else ""

    # 2. Check if current slide is empty (Case 1 vs Case 2)
    if is_empty_slide(current_html):
        print(f"[*] [Case 1 - Empty Slide] Slide {slide_number} is empty.")
        if slide_number > 1 and project_id:
            prev_num = slide_number - 1
            prev_html = GetHTMLCode(project_id=project_id, slide_number=prev_num, user_id=user_id)
            if prev_html and not is_empty_slide(prev_html):
                template_html = prev_html
                print(f"[*] [Case 1] Found previous slide {prev_num} with content. Sending to LLM as template.")
            else:
                template_html = prev_html or current_html
        else:
            template_html = current_html
    else:
        print(f"[*] [Case 2 - Content Slide] Slide {slide_number} has existing content. Sending current slide to LLM as template.")
        template_html = current_html

    # 3. Generate new slide HTML and replace existing code in S3
    generated_html = PPTGenerationAgent(
        user_query=user_query,
        retrived_rows=retrieved_data,
        slide_number=slide_number,
        project_id=project_id,
        user_id=user_id,
        html_code=template_html
    )
    print(f"[+] [LangGraph - PPT Generation Node] Presentation slide {slide_number} generated successfully!")

    # Chat message for the user - Clean conversational response, NEVER raw HTML code!
    chat_confirmation = (
        f"✨ I've designed Slide {slide_number} based on your data and updated your presentation canvas."
    )

    return {
        "generated_slide_html": generated_html,
        "slide_number": slide_number,
        "final_output": chat_confirmation,
        "status": "SUCCESS_PPT_GENERATED"
    }


def validate_html_code_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Node 7: HTML Code Validation Agent
    Passes ONLY the HTML code to the validation agent.
    - Inspects and rewrites code if broken UI or overlapping elements exist.
    - Rewrites code if not proper alignment of the PPT slide frame (16:9 aspect ratio).
    - Rewrites code if any syntax errors, missing tags, or JS/Chart.js errors (e.g. calc() inside JS) exist.
    - Returns the proper, working HTML code and replaces the slide file in Supabase S3.
    """
    generated_html = state.get("generated_slide_html") or ""
    slide_number = int(state.get("slide_number") or 1)
    project_id = state.get("project_id")
    user_id = state.get("user_id")

    print(f"\n[LangGraph - Node 7: HTML Code Validation Node] Validating Slide {slide_number}...")

    if not generated_html:
        print("[!] No generated slide HTML found in state to validate; skipping validation.")
        return {
            "status": "VALIDATION_SKIPPED"
        }

    # Pass only the HTML code to the validation agent
    validated_html = ValidateHTMLCodeAgent(html_code=generated_html)
    print(f"[+] [LangGraph - Node 7] HTML code validated and repaired successfully for Slide {slide_number}!")

    # Persist validated HTML to S3 replacing preliminary slide code
    if project_id:
        save_slide_to_s3(
            project_id=project_id,
            slide_number=slide_number,
            html_code=validated_html,
            user_id=user_id
        )
        print(f"[+] [LangGraph - Node 7] Saved validated HTML to S3 for Slide {slide_number} via manifest")

    return {
        "generated_slide_html": validated_html,
        "status": "SUCCESS_HTML_VALIDATED"
    }


def save_ai_response_node(state: KelostatsGraphState) -> Dict[str, Any]:
    """
    Terminal Node: Persists final generated response/output to chat_messages table (role: 'AI')
    before the workflow completes.
    """
    project_id = state.get("project_id")
    final_output = state.get("final_output") or ""
    print(f"\n[LangGraph - Exit: Save AI Response] Persisting AI message for project '{project_id}'...")

    if project_id and final_output:
        save_chat_message(project_id=project_id, role="AI", message=final_output)

    return {
        "status": state.get("status") or "COMPLETED"
    }


# ==========================================
# 4. Conditional Edge Routers
# ==========================================

def decide_classification_route(state: KelostatsGraphState) -> str:
    """
    Decides routing from query_classification_node:
    - 'greet' -> handle_greet -> save_ai_response -> END
    - 'out_of_scope' -> handle_out_of_scope -> save_ai_response -> END
    - 'in_scope' -> query_decision -> schema_input -> ...
    """
    intent = (state.get("classification_intent") or "in_scope").lower().strip()
    if intent == "greet":
        return "handle_greet"
    elif intent == "out_of_scope":
        return "handle_out_of_scope"
    return "query_decision"


def decide_verification_route(state: KelostatsGraphState) -> str:
    """
    Decides the next node based on verification_status:
    - RETRIEVAL_REQUIRED -> retrieval_agent
    - SCHEMA_MATCH (default) -> sql_writer
    """
    status_val = (state.get("verification_status") or "").upper().strip()

    if status_val == "RETRIEVAL_REQUIRED":
        return "retrieval_agent"
    return "sql_writer"


def decide_retrieval_route(state: KelostatsGraphState) -> str:
    """
    Decides the route after retrieval_agent_node:
    - If execution error occurred: routes to sql_repair
    - If 0 rows were found (status == "NOT_FOUND"): routes to save_ai_response -> END
    - If rows were found (>0 rows): routes to sql_writer node to generate master SQL query
    """
    status_val = (state.get("status") or "").upper().strip()
    if status_val == "RETRIEVAL_REPAIR_REQUIRED":
        return "sql_repair"
    elif status_val == "NOT_FOUND":
        return "save_ai_response"
    return "sql_writer"


def decide_sql_writer_route(state: KelostatsGraphState) -> str:
    """
    Decides the route after sql_writer_node:
    - If execution failed (status == "REPAIR_REQUIRED"): routes to sql_repair node in LangGraph
    - If decision == "agent": routes to ppt_generation
    - If decision == "normal_qa":
        - if retrieved_rows_count > 0: routes to answer_generator
        - otherwise: routes to save_ai_response -> END
    """
    status_val = (state.get("status") or "").upper().strip()
    if status_val == "REPAIR_REQUIRED":
        return "sql_repair"

    decision = (state.get("decision") or "normal_qa").lower().strip()
    rows_count = state.get("retrieved_rows_count") or 0

    if decision == "agent":
        return "ppt_generation"

    if decision == "normal_qa" and rows_count > 0:
        return "answer_generator"

    return "save_ai_response"


def decide_sql_repair_route(state: KelostatsGraphState) -> str:
    """
    Decides the route after sql_repair_node:
    - If repaired from retrieval (status == "RETRIEVAL_SUCCESS"): routes to sql_writer
    - If repaired master SQL:
        - If decision == "agent": routes to ppt_generation
        - If decision == "normal_qa" and retrieved_rows_count > 0: routes to answer_generator
    - Otherwise: routes to save_ai_response -> END
    """
    status_val = (state.get("status") or "").upper().strip()
    if status_val == "RETRIEVAL_SUCCESS":
        return "sql_writer"

    decision = (state.get("decision") or "normal_qa").lower().strip()
    rows_count = state.get("retrieved_rows_count") or 0

    if status_val == "SUCCESS_SQL_REPAIRED":
        if decision == "agent":
            return "ppt_generation"
        elif decision == "normal_qa" and rows_count > 0:
            return "answer_generator"

    return "save_ai_response"


# ==========================================
# 5. Build and Compile LangGraph Workflow
# ==========================================

def build_kelostats_workflow():
    """
    Assembles the StateGraph with:
    1. save_user_message (persists incoming user query with role='User')
    2. query_classification (Classifies greet | out_of_scope | in_scope)
       - greet -> handle_greet -> save_ai_response -> END
       - out_of_scope -> handle_out_of_scope -> save_ai_response -> END
       - in_scope -> query_decision
    3. query_decision (Classifies normal_qa | agent) -> schema_input
    4. schema_input (extracts schema.json to text) -> verification_agent
    5. verification_agent (verifies query vs schema):
       - SCHEMA_MATCH -> sql_writer
       - RETRIEVAL_REQUIRED -> retrieval_agent
           - Execution error -> sql_repair -> sql_writer
           - 0 rows (NOT_FOUND) -> save_ai_response -> END
           - >0 rows -> sql_writer (with markdown table)
       - UNRELATED -> unrelated_query -> save_ai_response -> END
    6. sql_writer:
       - If execution fails (REPAIR_REQUIRED) -> sql_repair
       - If decision == "agent" -> ppt_generation -> validate_html_code -> save_ai_response -> END
       - If decision == "normal_qa" and retrieved_rows > 0 -> answer_generator -> save_ai_response -> END
       - Else -> save_ai_response -> END
    7. validate_html_code (Node 7: Validates & fixes HTML slide code, saves to S3) -> save_ai_response
    8. save_ai_response (persists AI response with role='AI') -> END
    """
    workflow = StateGraph(KelostatsGraphState)

    # 1. Add all nodes
    workflow.add_node("save_user_message", save_user_message_node)
    workflow.add_node("query_classification", query_classification_node)
    workflow.add_node("handle_greet", handle_greet_node)
    workflow.add_node("handle_out_of_scope", handle_out_of_scope_node)
    workflow.add_node("query_decision", query_decision_node)
    workflow.add_node("schema_input", schema_input_node)
    workflow.add_node("verification_agent", verification_agent_node)
    workflow.add_node("sql_writer", sql_writer_node)
    workflow.add_node("retrieval_agent", retrieval_agent_node)
    workflow.add_node("sql_repair", sql_repair_node)
    workflow.add_node("answer_generator", answer_generator_node)
    workflow.add_node("ppt_generation", ppt_generation_node)
    workflow.add_node("validate_html_code", validate_html_code_node)
    workflow.add_node("save_ai_response", save_ai_response_node)

    # 2. Set entry point to save_user_message, then proceed to query_classification
    workflow.set_entry_point("save_user_message")
    workflow.add_edge("save_user_message", "query_classification")

    # 3. Conditional routing from query_classification
    workflow.add_conditional_edges(
        "query_classification",
        decide_classification_route,
        {
            "handle_greet": "handle_greet",
            "handle_out_of_scope": "handle_out_of_scope",
            "query_decision": "query_decision"
        }
    )

    # 4. Greet and Out-of-Scope terminate at save_ai_response
    workflow.add_edge("handle_greet", "save_ai_response")
    workflow.add_edge("handle_out_of_scope", "save_ai_response")

    # 5. Connect query_decision to schema_input
    workflow.add_edge("query_decision", "schema_input")

    # 6. Connect schema_input to verification_agent
    workflow.add_edge("schema_input", "verification_agent")

    # 7. Add conditional routing edges from verification_agent
    workflow.add_conditional_edges(
        "verification_agent",
        decide_verification_route,
        {
            "sql_writer": "sql_writer",
            "retrieval_agent": "retrieval_agent"
        }
    )

    # 8. Add conditional routing edges from retrieval_agent:
    workflow.add_conditional_edges(
        "retrieval_agent",
        decide_retrieval_route,
        {
            "sql_repair": "sql_repair",
            "sql_writer": "sql_writer",
            "save_ai_response": "save_ai_response"
        }
    )

    # 9. Add conditional routing edges from sql_writer:
    workflow.add_conditional_edges(
        "sql_writer",
        decide_sql_writer_route,
        {
            "sql_repair": "sql_repair",
            "ppt_generation": "ppt_generation",
            "answer_generator": "answer_generator",
            "save_ai_response": "save_ai_response"
        }
    )

    # 10. Add conditional routing edges from sql_repair:
    workflow.add_conditional_edges(
        "sql_repair",
        decide_sql_repair_route,
        {
            "sql_writer": "sql_writer",
            "ppt_generation": "ppt_generation",
            "answer_generator": "answer_generator",
            "save_ai_response": "save_ai_response"
        }
    )

    # 11. Route remaining terminal nodes into save_ai_response, then to END
    workflow.add_edge("answer_generator", "save_ai_response")
    workflow.add_edge("ppt_generation", "validate_html_code")
    workflow.add_edge("validate_html_code", "save_ai_response")
    workflow.add_edge("save_ai_response", END)

    return workflow.compile()



# Compile graph instance
kelostats_graph = build_kelostats_workflow()


def run_orchestrator(
    user_query: str,
    database_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    slide_number: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Programmatic entry point to invoke the LangGraph orchestrator.
    Starts a workflow log session to record each agent interaction to logs/llm_logs/workflow Log {timestamp}.txt
    """
    logger_session = start_workflow_logger()

    initial_state: KelostatsGraphState = {
        "user_query": user_query,
        "database_id": database_id,
        "project_id": project_id,
        "user_id": user_id,
        "slide_number": slide_number or 1,
        "classification_intent": None,
        "classification_reason": None,
        "decision": None,
        "decision_reason": None,
        "llm_prompt_text": None,
        "verification_status": None,
        "verification_reason": None,
        "retrieved_markdown_table": None,
        "generated_sql": None,
        "sql_error": None,
        "retrieved_data": None,
        "retrieved_rows_count": None,
        "generated_slide_html": None,
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
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    slide_number: Optional[Union[int, str]] = 1
    slide_filename: Optional[str] = None


@router.post("/api/workflow/query", summary="Run LangGraph workflow for user query, database, and project")
def workflow_query_endpoint(payload: QueryWorkflowRequest):
    """
    POST /api/workflow/query
    Runs LangGraph:
    1. QueryClassificationAgent: classifies intent as 'greet' | 'out_of_scope' | 'in_scope'
    2. If greet -> handle_greet -> END
    3. If out_of_scope -> handle_out_of_scope -> END
    4. If in_scope -> QueryDecisionAgent: classifies decision as 'normal_qa' | 'agent'
    5. Proceeds to schema_input -> verification_agent -> sql_writer / retrieval_agent -> SQL execution.
    6. If decision == 'normal_qa' and retrieved_rows > 0 -> AnswerGeneratorAgent -> END.
    7. If decision == 'agent' -> PPTGenerationAgent -> generates slide HTML and updates S3 -> END.
    """
    target_db_id = payload.database_id or payload.db_id
    target_project_id = payload.project_id
    target_user_id = payload.user_id

    # Resolve target slide number from slide_filename (e.g. 'slide_04.html') or slide_number
    target_slide_number = 1
    if payload.slide_filename:
        m = re.search(r"slide_0*(\d+)", payload.slide_filename, re.IGNORECASE)
        if m:
            target_slide_number = int(m.group(1))
    elif payload.slide_number is not None:
        try:
            target_slide_number = int(payload.slide_number)
        except (ValueError, TypeError):
            m = re.search(r"\d+", str(payload.slide_number))
            target_slide_number = int(m.group(0)) if m else 1

    if target_slide_number < 1:
        target_slide_number = 1

    if not payload.user_query or not payload.user_query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required field 'user_query' in request payload."
        )

    try:
        graph_result = run_orchestrator(
            user_query=payload.user_query,
            database_id=target_db_id,
            project_id=target_project_id,
            user_id=target_user_id,
            slide_number=target_slide_number
        )

        slide_num_result = graph_result.get("slide_number") or target_slide_number

        return {
            "status": graph_result.get("status"),
            "intent": graph_result.get("classification_intent"),
            "decision": graph_result.get("decision"),
            "verification_status": graph_result.get("verification_status"),
            "verification_reason": graph_result.get("verification_reason"),
            "generated_sql": graph_result.get("generated_sql"),
            "retrieved_rows_count": graph_result.get("retrieved_rows_count"),
            "output": graph_result.get("final_output"),
            "slide_html": graph_result.get("generated_slide_html"),
            "slide_number": slide_num_result,
            "slide_filename": f"slide_{slide_num_result:02d}.html",
            "database_id": target_db_id,
            "project_id": target_project_id
        }
    except RuntimeError as run_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(run_err)
        )
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
