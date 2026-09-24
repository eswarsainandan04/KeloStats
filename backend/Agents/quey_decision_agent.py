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
from dotenv import load_dotenv

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "query_decision_prompt.txt"


class DecisionType(str, Enum):
    NORMAL_QA = "normal_qa"
    AGENT = "agent"


class QueryDecisionResponse(BaseModel):
    decision: DecisionType = Field(default=DecisionType.NORMAL_QA, description="Decision type")
    reason: str = Field(default="Query decision classified successfully.", description="Reason for decision")

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: Any) -> DecisionType:
        if isinstance(value, str):
            clean_val = value.strip().lower()
            for item in DecisionType:
                if item.value == clean_val:
                    return item
        return DecisionType.NORMAL_QA


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
    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

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
        "temperature": temperature
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
            from logs.llm_logger import log_agent_call
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


def get_source_from_workspace(project_id: Optional[str]) -> Optional[str]:
    """
    Retrieves the 'source' column ('database', 'documents', 'auto') from the workspace table
    for a given project_id.
    """
    if not project_id or not str(project_id).strip():
        return None
    try:
        with engine.connect() as conn:
            stmt = text("SELECT source FROM workspace WHERE project_id = :project_id LIMIT 1;")
            row = conn.execute(stmt, {"project_id": str(project_id).strip()}).fetchone()
            if row and row[0]:
                return str(row[0]).strip().lower()
    except Exception as exc:
        print(f"[!] Warning fetching source from workspace table for project '{project_id}': {exc}")
    return None


def router_agent(
    source: Optional[str] = "auto",
    user_query: Optional[str] = None,
    **kwargs: Any
) -> str:
    """
    Router Agent:
    Based on the user query, decides whether the question is based on pdfs/docs or SQL database.
    Returns: 'database' or 'documents'.
    """
    # Flexibility for argument ordering if called as router_agent(user_query) or router_agent(source, user_query)
    q = user_query
    s = source
    if q is None and s is not None and (" " in s or len(s) > 20):
        q = s
        s = "auto"
    elif q is None:
        q = kwargs.get("user_query", "")

    cleaned_query = (q or "").strip()
    clean_source = (s or "auto").strip().lower()

    if clean_source in ("database", "documents"):
        return clean_source

    prompt = f"""you are the router agent based on the user query you need to decide the question is based on pdfs/docs or SQL database 
just return simple word  "database"  or "documents"

User Query:
"{cleaned_query}"
"""
    try:
        raw_output = _call_llm(
            prompt=prompt,
            node_name="Node: Router Agent",
            agent_name="Router Agent",
            json_mode=False,
            temperature=0.0
        ).strip().lower()

        if "doc" in raw_output or "pdf" in raw_output:
            return "documents"
        return "database"
    except Exception as err:
        print(f"[!] Warning in router_agent: {err}. Defaulting to 'database'.")
        return "database"


def _classify_decision(user_query: str) -> Dict[str, str]:
    """
    Uses the query decision prompt to classify the user query into:
    - 'agent': directive/command to generate/present/create slides
    - 'normal_qa': factual/analytical inquiry asking for answers/metrics
    Purely driven by LLM prompt without hardcoded keyword lists.
    """
    cleaned_query = (user_query or "").strip()
    if not cleaned_query:
        return {"decision": "normal_qa", "reason": "Empty query defaulted to normal_qa."}

    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Decision prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    populated_prompt = prompt_template.replace("{{user_query}}", cleaned_query)

    try:
        raw_content = _call_llm(
            prompt=populated_prompt,
            node_name="Node: Query Decision",
            agent_name="Query Decision Agent",
            json_mode=True,
            temperature=0.0
        )

        try:
            parsed = QueryDecisionResponse.model_validate_json(raw_content)
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
            parsed = QueryDecisionResponse.model_validate_json(stripped)

        return {
            "decision": parsed.decision.value,
            "reason": parsed.reason
        }
    except Exception as err:
        print(f"[!] Warning in _classify_decision: {err}. Defaulting to normal_qa.")
        return {
            "decision": "normal_qa",
            "reason": f"Fallback decision due to exception: {str(err)}"
        }


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


def router_type(source: str, user_query: str) -> Dict[str, Any]:
    """
    Determines pipeline decision and requirements based on source and user query:

    if source == database:
      decision = agent | sql_required | reason or normal_qa | sql_required | reason
    elif source == documents:
      decision = agent | rag_required | reason or normal_qa | rag_required | reason
    """
    clean_source = (source or "database").strip().lower()
    cleaned_query = (user_query or "").strip()

    # Classify decision ('normal_qa' vs 'agent') without hardcoding
    decision_info = _classify_decision(cleaned_query)
    decision = decision_info.get("decision", "normal_qa")
    decision_reason = decision_info.get("reason", "Query decision classified successfully.")

    if clean_source == "database":
        if decision == "agent":
            classify_res = QueryDecisionClassifyAgent(user_query=cleaned_query, source="database")
            sql_required = classify_res.get("sql_required", True)
            reason = classify_res.get("reason") or decision_reason
            return {
                "decision": "agent",
                "sql_required": sql_required,
                "reason": reason,
                "source": "database"
            }
        else:
            return {
                "decision": "normal_qa",
                "sql_required": True,
                "reason": decision_reason,
                "source": "database"
            }
    elif clean_source in ("documents", "document", "docs"):
        if decision == "agent":
            classify_res = QueryDecisionClassifyAgent(user_query=cleaned_query, source="documents")
            rag_required = classify_res.get("rag_required", True)
            reason = classify_res.get("reason") or decision_reason
            return {
                "decision": "agent",
                "rag_required": rag_required,
                "reason": reason,
                "source": "documents"
            }
        else:
            return {
                "decision": "normal_qa",
                "rag_required": True,
                "reason": decision_reason,
                "source": "documents"
            }
    else:
        # Default / fallback to database
        if decision == "agent":
            classify_res = QueryDecisionClassifyAgent(user_query=cleaned_query, source="database")
            sql_required = classify_res.get("sql_required", True)
            reason = classify_res.get("reason") or decision_reason
            return {
                "decision": "agent",
                "sql_required": sql_required,
                "reason": reason,
                "source": "database"
            }
        else:
            return {
                "decision": "normal_qa",
                "sql_required": True,
                "reason": decision_reason,
                "source": "database"
            }


def QueryDecisionAgent(
    user_query: str,
    source: Optional[str] = None,
    project_id: Optional[str] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Query Decision Agent:
    - Resolves source from workspace table if project_id is provided and source is not given.
    - If source == 'auto', router_agent determines whether it's 'database' or 'documents'.
    - Calls router_type(source, user_query) to return the decision dict.
    """
    cleaned_query = (user_query or "").strip()
    if not cleaned_query:
        clean_src = (source or "database").strip().lower()
        if clean_src in ("documents", "document", "docs"):
            return {
                "decision": "normal_qa",
                "rag_required": False,
                "reason": "Empty input defaulted to normal_qa.",
                "source": "documents"
            }
        return {
            "decision": "normal_qa",
            "sql_required": False,
            "reason": "Empty input defaulted to normal_qa.",
            "source": "database"
        }

    # Resolve source
    resolved_source = source or kwargs.get("source")
    if not resolved_source and project_id:
        resolved_source = get_source_from_workspace(project_id)

    if not resolved_source:
        resolved_source = "auto"
    else:
        resolved_source = resolved_source.strip().lower()

    # If source is auto, invoke router_agent
    if resolved_source == "auto":
        resolved_source = router_agent(source=resolved_source, user_query=cleaned_query)

    return router_type(source=resolved_source, user_query=cleaned_query)
    