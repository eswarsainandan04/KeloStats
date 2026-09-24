import os
import sys
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Configure stdout encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment variables
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "rag_agent_prompt.txt"
SLIDE_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "rag_slide_content_prompt.txt"


def _clean_text_response(raw_response: str) -> str:
    """Strips reasoning tags and surrounding markdown code fences if present."""
    text = (raw_response or "").strip()

    # Strip thinking/reasoning tags (e.g. <think>...</think>)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # If the entire response is wrapped in markdown code blocks, unwrap it
    match = re.match(r"^```(?:markdown|text)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    return text


def KnowledgeAnswerAgent(
    user_query: Optional[str] = None,
    context: Optional[Union[str, List[Any], Dict[str, Any]]] = None,
    decision: str = "normal_qa",
    **kwargs: Any,
) -> str:
    """Knowledge Answer Agent (RAGAgent):
    Answers the user query strictly based on the provided context retrieved from document chunks.
    Adapts prompt dynamically based on decision ('normal_qa' vs 'agent').

    Args:
        user_query: The user query string (supports positional or keyword, including 'uswer_query').
        context: Clean formatted context text (or retrieved chunks list/dict) from documents.
        decision: Routing decision:
                  - 'normal_qa': standard factual markdown Q&A answer.
                  - 'agent': content generation formatted specifically for one PPT presentation slide.
        **kwargs: Additional parameters or alternative argument names.

    Returns:
        The generated answer text in clean Markdown.
    """
    # Support positional or keyword arguments, including typo 'uswer_query'
    query = user_query if user_query is not None else kwargs.get("uswer_query", "")
    ctx = context if context is not None else kwargs.get("context", "")
    dec = decision if decision is not None else kwargs.get("decision", "normal_qa")
    cleaned_decision = str(dec or "normal_qa").strip().lower()

    # If context is passed as a list or dict of chunks, parse it with context_parser
    if isinstance(ctx, (list, dict)):
        try:
            from documents.semantic_search import context_parser
            ctx = context_parser(ctx)
        except Exception:
            ctx = str(ctx)

    cleaned_query = str(query or "").strip()
    cleaned_context = str(ctx or "").strip()

    if not cleaned_query:
        return "Please provide a valid question to answer."

    # Select prompt template loaded strictly from prompts/*.txt
    if cleaned_decision == "agent":
        if not SLIDE_PROMPT_TEMPLATE_PATH.exists():
            raise FileNotFoundError(f"Slide prompt template not found at: {SLIDE_PROMPT_TEMPLATE_PATH}")

        with open(SLIDE_PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        node_name = "Node: Knowledge Answer Agent (Slide Content)"
        agent_name = "KnowledgeAnswerAgent"
    else:
        # Default: normal_qa
        if not PROMPT_TEMPLATE_PATH.exists():
            raise FileNotFoundError(f"RAG agent prompt template not found at: {PROMPT_TEMPLATE_PATH}")

        with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        node_name = "Node: Knowledge Answer Agent (Normal QA)"
        agent_name = "KnowledgeAnswerAgent"

    # Replace placeholders in prompt template
    populated_prompt = (
        prompt_template
        .replace("{{context}}", cleaned_context if cleaned_context else "No relevant context provided.")
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
                "content": populated_prompt,
            }
        ],
        "temperature": 0.2,
    }

    req = urllib.request.Request(
        endpoint_url,
        data=json.dumps(request_data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            resp_bytes = resp.read()
            resp_json = json.loads(resp_bytes.decode("utf-8"))
            raw_content = resp_json["choices"][0]["message"]["content"]
            usage = resp_json.get("usage", {})

            # Log interaction to workflow logger if available
            try:
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name=node_name,
                    agent_name=agent_name,
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage,
                )
            except Exception as log_err:
                print(f"[!] Warning logging knowledge answer interaction: {log_err}", file=sys.stderr)

            answer = _clean_text_response(raw_content)
            return answer

    except urllib.error.HTTPError as http_err:
        err_body = ""
        try:
            err_body = http_err.read().decode("utf-8")
        except Exception:
            pass
        error_msg = f"[!] HTTP error {http_err.code} in RAGAgent: {http_err.reason} - {err_body}"
        print(error_msg, file=sys.stderr)
        raise RuntimeError(error_msg) from http_err
    except Exception as err:
        print(f"[!] Error in RAGAgent: {err}", file=sys.stderr)
        raise err


# Backward-compatibility alias
RAGAgent = KnowledgeAnswerAgent


if __name__ == "__main__":
    from documents.semantic_search import context_parser,generate_query_embeddings,semantic_search
    import json

    query = "what are Knowledge Base Resources?"
    query_emmbeding = generate_query_embeddings(query)
    context = semantic_search(query_emmbeding,"pool_b6e2c960-cc7f-4fb1-b784-dc1b0bcd1218")
    cleaned_chunks = context_parser(context)
    print(cleaned_chunks)