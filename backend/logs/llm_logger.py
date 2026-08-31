import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import contextvars

# Ensure logs/llm_logs directory exists
LOGS_DIR = Path(__file__).resolve().parent / "llm_logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Context variable to track the active logger session per workflow execution
_active_workflow_session: contextvars.ContextVar[Optional["WorkflowLoggerSession"]] = contextvars.ContextVar(
    "_active_workflow_session", default=None
)


class WorkflowLoggerSession:
    """
    Session container for recording agent LLM interactions during a single workflow query.
    Writes logs to: logs/llm_logs/workflow Log {timestamp}.txt
    """
    def __init__(self, session_id: Optional[str] = None):
        self.timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_id = session_id or self.timestamp_str
        self.log_file_name = f"workflow Log {self.timestamp_str}.txt"
        self.file_path = LOGS_DIR / self.log_file_name
        self.entries: List[str] = []
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cumulative_tokens: int = 0
        self._lock = threading.Lock()

    def _render_full_content(self) -> str:
        """
        Combines all agent log entries and appends the TOTAL TOKENS summary section at the end.
        """
        summary_block = (
            "=======================================\n"
            "TOTAL TOKENS\n"
            "======================================\n"
            f" INPUT TOKENS : {self.total_input_tokens}\n"
            f"OUTPUT TOKENS : {self.total_output_tokens}\n"
            f"TOTAL         : {self.total_cumulative_tokens}\n"
            "=======================================\n"
        )
        return "".join(self.entries) + "\n" + summary_block

    def log_node(
        self,
        node_name: str,
        agent_name: str,
        llm_input: str,
        llm_output: str,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Appends a formatted agent LLM interaction block and updates cumulative token counts.
        """
        usage_dict = usage or {}
        input_tokens = usage_dict.get("prompt_tokens")
        output_tokens = usage_dict.get("completion_tokens")
        total_tokens = usage_dict.get("total_tokens")

        # Fallback token estimation if usage object is missing
        if input_tokens is None:
            input_tokens = max(1, len(str(llm_input)) // 4)
        if output_tokens is None:
            output_tokens = max(1, len(str(llm_output)) // 4)
        if total_tokens is None:
            total_tokens = input_tokens + output_tokens

        entry_text = (
            f"======================\n"
            f"{node_name} - {agent_name}\n"
            f"LLM INPUT:\n\n"
            f"{str(llm_input).strip()}\n\n"
            f"LLM OUTPUT:\n\n"
            f"{str(llm_output).strip()}\n\n"
            f"TOKEN COUNT:\n"
            f"input tokens: {input_tokens}\n"
            f"output tokens: {output_tokens}\n"
            f"total tokens: {total_tokens}\n"
            f"======================\n\n"
        )

        with self._lock:
            self.total_input_tokens += int(input_tokens)
            self.total_output_tokens += int(output_tokens)
            self.total_cumulative_tokens += int(total_tokens)
            self.entries.append(entry_text)
            
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(self._render_full_content())

        print(f"[+] [LLMLogger] Recorded log for '{node_name} - {agent_name}' in: {self.log_file_name}")

    def save(self) -> Path:
        """
        Finalizes and persists the log file with total tokens summary.
        """
        with self._lock:
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(self._render_full_content())
        return self.file_path


def start_workflow_logger(session_id: Optional[str] = None) -> WorkflowLoggerSession:
    """
    Initializes a new workflow log session and binds it to the current context.
    """
    session = WorkflowLoggerSession(session_id=session_id)
    _active_workflow_session.set(session)
    return session


def get_active_logger() -> Optional[WorkflowLoggerSession]:
    """
    Retrieves the active workflow logger for the current context.
    """
    return _active_workflow_session.get()


def log_agent_call(
    node_name: str,
    agent_name: str,
    llm_input: str,
    llm_output: str,
    usage: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Logs an agent LLM call to the active workflow session.
    """
    session = get_active_logger()
    if session:
        session.log_node(node_name, agent_name, llm_input, llm_output, usage)
    else:
        # If called standalone, create a single log session
        temp_session = WorkflowLoggerSession()
        temp_session.log_node(node_name, agent_name, llm_input, llm_output, usage)
