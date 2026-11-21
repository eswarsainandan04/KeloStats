import os
import sys
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, text
from app.services.connectors import app_db_engine as engine
from app.services.agents.models import get_agent_config

# Query Decision Agent - Classification Models
class SQLRequirementResponse(BaseModel):
    sql_required: bool = Field(default=True, description="Whether SQL execution is required")
    reason: Optional[str] = Field(default=None, description="Reason for decision")

    @field_validator("sql_required", mode="before")
    @classmethod
    def normalize_sql_required(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean_str = value.strip().lower()
            if clean_str in ("false", "no", "0"):
                return False
            if clean_str in ("true", "yes", "1"):
                return True
        return True


class RAGRequirementResponse(BaseModel):
    rag_required: bool = Field(default=True, description="Whether RAG document retrieval is required")
    reason: Optional[str] = Field(default=None, description="Reason for decision")

    @field_validator("rag_required", mode="before")
    @classmethod
    def normalize_rag_required(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean_str = value.strip().lower()
            if clean_str in ("false", "no", "0"):
                return False
            if clean_str in ("true", "yes", "1"):
                return True
        return True


class TaskClassifyResult(dict):
    """
    Dictionary response containing classification key ('sql_required' OR 'rag_required', and 'reason')
    that also evaluates as a boolean for backwards compatibility.
    """
    def __init__(self, is_required: bool, field_name: str, reason: Optional[str] = None):
        super().__init__({
            field_name: is_required,
            "reason": reason or "",
            "is_required": is_required
        })
        self.is_required = is_required
        self.field_name = field_name
        self.reason = reason or ""
        setattr(self, field_name, is_required)

    def __bool__(self) -> bool:
        return bool(self.is_required)


def _call_llm(
    prompt: str,
    node_name: str,
    agent_name: str,
    json_mode: bool = False,
    temperature: float = 0.0
) -> str:
    """
    Internal helper to call Groq/OpenAI-compatible LLM endpoint and log interaction.
    """
    llm_cfg = get_agent_config(agent_name or "query_decision_agent")
    base_url = str(llm_cfg.get("BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
    api_key = str(llm_cfg.get("API_KEY") or "")
    model = str(llm_cfg.get("MODEL_NAME") or "openai/gpt-oss-120b")
    effective_temp = temperature if temperature is not None else float(llm_cfg.get("TEMPERATURE", 0.0))

    if not api_key:
        raise ValueError(f"LLM_API_KEY is not set for {agent_name}.")

    endpoint_url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

    request_data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": effective_temp
    }
    if json_mode:
        request_data["response_format"] = {"type": "json_object"}

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

    with urllib.request.urlopen(req, timeout=30) as resp:
        resp_bytes = resp.read()
        resp_json = json.loads(resp_bytes.decode("utf-8"))
        raw_content = resp_json["choices"][0]["message"]["content"].strip()
        usage = resp_json.get("usage", {})

        try:
            from app.logs.llm_logger import log_agent_call
            log_agent_call(
                node_name=node_name,
                agent_name=agent_name,
                llm_input=prompt,
                llm_output=raw_content,
                usage=usage
            )
        except Exception as log_err:
            print(f"[!] Warning logging agent call for {agent_name}: {log_err}")

        return raw_content


def get_workspace_metadata(project_id: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Retrieves the 'source' and 'response_mode' directly from the workspace table in PostgreSQL
    for a given project_id.
    """
    if not project_id or not str(project_id).strip():
        return {"source": None, "response_mode": None}
    clean_pid = str(project_id).strip()
    try:
        with engine.connect() as conn:
            try:
                stmt = text("SELECT source, response_mode FROM workspace WHERE project_id = :project_id LIMIT 1;")
                row = conn.execute(stmt, {"project_id": clean_pid}).mappings().first()
                if row:
                    return {
                        "source": str(row["source"]).strip().lower() if row.get("source") else None,
                        "response_mode": str(row["response_mode"]).strip().lower() if row.get("response_mode") else None
                    }
            except Exception:
                stmt = text("SELECT source, request_mode FROM workspace WHERE project_id = :project_id LIMIT 1;")
                row = conn.execute(stmt, {"project_id": clean_pid}).mappings().first()
                if row:
                    return {
                        "source": str(row["source"]).strip().lower() if row.get("source") else None,
                        "response_mode": str(row["request_mode"]).strip().lower() if row.get("request_mode") else None
                    }
    except Exception as exc:
        print(f"[!] Warning fetching workspace metadata for project '{project_id}': {exc}")
    return {"source": None, "response_mode": None}


def get_source_from_workspace(project_id: Optional[str]) -> Optional[str]:
    """
    Retrieves the 'source' column ('database', 'documents') from the workspace table.
    """
    meta = get_workspace_metadata(project_id)
    return meta.get("source")


def router_agent(source: Optional[str] = "database", user_query: Optional[str] = None, **kwargs: Any) -> str:
    """Pass-through for source without LLM decision."""
    s = (source or "database").strip().lower()
    return "documents" if s in ("documents", "document", "docs") else "database"


def QueryDecisionClassifyAgent(
    user_query: str,
    source: str = "database",
    **kwargs: Any
) -> TaskClassifyResult:
    """
    PPT Task Classification Agent:
    - If source == 'database':
      Evaluates whether a presentation request requires querying the database via the SQL pipeline (sql_required: true)
      or is a direct visual/textual EDIT on an existing slide canvas without database data (sql_required: false).
    - If source == 'documents':
      Evaluates whether a presentation request requires retrieving information from documents via RAG (rag_required: true)
      or is a direct visual/textual EDIT on an existing slide canvas without document retrieval (rag_required: false).

    :param user_query: User query string
    :param source: 'database' or 'documents'
    :return: TaskClassifyResult (behaves as dict and bool)
    """
    cleaned_query = (user_query or "").strip()
    clean_source = (source or "database").strip().lower()

    if not cleaned_query:
        field_name = "sql_required" if clean_source == "database" else "rag_required"
        return TaskClassifyResult(is_required=False, field_name=field_name, reason="Empty query defaulted to false.")

    if clean_source == "database":
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
        Respond in JSON format:
        {{"sql_required": true, "reason": "short explanation"}}

        User Query:
        "{cleaned_query}"
        """
        try:
            raw_content = _call_llm(
                prompt=prompt,
                node_name="Node: Query Decision Classify",
                agent_name="Query Decision Classify Agent (Database)",
                json_mode=True,
                temperature=0.0
            )
            try:
                parsed = SQLRequirementResponse.model_validate_json(raw_content)
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
                parsed = SQLRequirementResponse.model_validate_json(stripped)

            return TaskClassifyResult(is_required=parsed.sql_required, field_name="sql_required", reason=parsed.reason)
        except Exception as err:
            print(f"[!] Warning in QueryDecisionClassifyAgent (Database): {err}. Defaulting to True.")
            return TaskClassifyResult(is_required=True, field_name="sql_required", reason="Fallback default due to error.")

    else:
        # Documents / PDFs
        prompt = f"""
        You are the PPT Task Classification Agent for KeloStats, an enterprise AI analytics platform connected to a knowledge base of uploaded documents and PDFs.
        Your job is to determine whether a presentation request requires retrieving information from documents via the RAG pipeline (rag_required: true) or is a direct visual/textual EDIT on an existing slide canvas without document retrieval (rag_required: false).

        RULES:
        1. rag_required: true (DEFAULT for presentation creation and document analysis):
            - Any command to create, generate, analyze, discuss, summarize, or present topics, policies, documentation, reports, or research from documents/PDFs (e.g., 'disscuss document summary in PPT', 'generate slide on contract terms', 'create presentation from PDF', 'build deck on compliance handbook', 'present section highlights').
            - Even high-level executive summaries or business analyses MUST retrieve document context to ground the slide in factual document contents.

        2. rag_required: false (ONLY for direct slide styling, layout adjustment, or simple edits):
            - The user is asking to modify the visual appearance, styling, or existing wording of the currently open slide canvas.
            - Examples: 'change title to...', 'make background dark navy', 'restyle cards with purple border', 'increase font size', 'change button color', 'remove second card', 'edit this slide to fix typo'.

        Output:
        Respond in JSON format:
        {{"rag_required": true, "reason": "short explanation"}}

        User Query:
        "{cleaned_query}"
        """
        try:
            raw_content = _call_llm(
                prompt=prompt,
                node_name="Node: Query Decision Classify",
                agent_name="Query Decision Classify Agent (Documents)",
                json_mode=True,
                temperature=0.0
            )
            try:
                parsed = RAGRequirementResponse.model_validate_json(raw_content)
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
                parsed = RAGRequirementResponse.model_validate_json(stripped)

            return TaskClassifyResult(is_required=parsed.rag_required, field_name="rag_required", reason=parsed.reason)
        except Exception as err:
            print(f"[!] Warning in QueryDecisionClassifyAgent (Documents): {err}. Defaulting to True.")
            return TaskClassifyResult(is_required=True, field_name="rag_required", reason="Fallback default due to error.")


def QueryDecisionAgent(
    user_query: str,
    source: Optional[str] = None,
    project_id: Optional[str] = None,
    response_mode: Optional[str] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Query Decision Agent:
    - Pure database retrieval for 'source' and 'response_mode' from workspace table (no LLM decision).
    - If response_mode == 'ask' -> decision = 'normal_qa'
    - If response_mode == 'agent' -> decision = 'agent'
    - Source: 'database' or 'documents' retrieved from workspace table.
    - Only QueryDecisionClassifyAgent() is invoked as an LLM agent to evaluate:
        * sql_required: true / false (if source == 'database')
        * rag_required: true / false (if source == 'documents')
    """
    cleaned_query = (user_query or "").strip()
    pid = project_id or kwargs.get("project_id")

    # 1. Database retrieval of workspace metadata (source, response_mode)
    ws_meta = get_workspace_metadata(pid) if pid else {}

    # 2. Resolve source from DB column (or argument if explicitly supplied)
    raw_source = source or kwargs.get("source") or ws_meta.get("source") or "database"
    clean_src = str(raw_source).strip().lower()
    if clean_src in ("documents", "document", "docs", "pdf", "pdfs"):
        resolved_source = "documents"
    else:
        resolved_source = "database"

    # 3. Resolve response_mode from DB column (or argument if explicitly supplied)
    raw_mode = (
        response_mode
        or kwargs.get("response_mode")
        or kwargs.get("request_mode")
        or ws_meta.get("response_mode")
        or "agent"
    )
    clean_mode = str(raw_mode).strip().lower()
    if clean_mode not in ("ask", "agent"):
        clean_mode = "agent"

    # 4. Map response_mode to decision: 'ask' -> 'normal_qa', 'agent' -> 'agent'
    if clean_mode == "ask":
        decision = "normal_qa"
    else:
        decision = "agent"

    # 5. Requirement evaluation via QueryDecisionClassifyAgent (the ONLY agent calling LLM)
    if resolved_source == "database":
        if decision == "agent":
            if not cleaned_query:
                return {
                    "decision": "agent",
                    "sql_required": False,
                    "reason": "Empty query defaulted to false.",
                    "source": "database",
                    "response_mode": clean_mode
                }
            classify_res = QueryDecisionClassifyAgent(user_query=cleaned_query, source="database")
            sql_required = classify_res.get("sql_required", True)
            reason = classify_res.get("reason") or "Slide generation evaluated for database requirement."
            return {
                "decision": "agent",
                "sql_required": sql_required,
                "reason": reason,
                "source": "database",
                "response_mode": clean_mode
            }
        else:
            return {
                "decision": "normal_qa",
                "sql_required": bool(cleaned_query),
                "reason": "Direct Q&A mode from database.",
                "source": "database",
                "response_mode": clean_mode
            }
    else:
        # Documents
        if decision == "agent":
            if not cleaned_query:
                return {
                    "decision": "agent",
                    "rag_required": False,
                    "reason": "Empty query defaulted to false.",
                    "source": "documents",
                    "response_mode": clean_mode
                }
            classify_res = QueryDecisionClassifyAgent(user_query=cleaned_query, source="documents")
            rag_required = classify_res.get("rag_required", True)
            reason = classify_res.get("reason") or "Slide generation evaluated for document requirement."
            return {
                "decision": "agent",
                "rag_required": rag_required,
                "reason": reason,
                "source": "documents",
                "response_mode": clean_mode
            }
        else:
            return {
                "decision": "normal_qa",
                "rag_required": bool(cleaned_query),
                "reason": "Direct Q&A mode from documents.",
                "source": "documents",
                "response_mode": clean_mode
            }


def router_type(source: str, user_query: str, response_mode: str = "agent", **kwargs: Any) -> Dict[str, Any]:
    """Helper alias for backwards compatibility."""
    return QueryDecisionAgent(user_query=user_query, source=source, response_mode=response_mode, **kwargs)
    