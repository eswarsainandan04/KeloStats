import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_TEMPLATE_PATH = PROMPTS_DIR / "query_reformulation_prompt.txt"
if not PROMPT_TEMPLATE_PATH.exists():
    ALT_PATH = PROMPTS_DIR / "query_reformulation_ptompt.txt"
    if ALT_PATH.exists():
        PROMPT_TEMPLATE_PATH = ALT_PATH


def _clean_json_response(raw_response: str) -> str:
    """
    Strips markdown code blocks, reasoning tags (<think>...</think>), and extracts clean JSON.
    """
    text = raw_response.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    return text


def _clean_text_response(raw_response: str) -> str:
    """
    Strips reasoning tags and extra surrounding fences or quotes if present.
    """
    text = raw_response.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    match = re.match(r"^```(?:markdown|text)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    if len(text) >= 2 and ((text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'"))):
        text = text[1:-1].strip()

    return text


def _execute_llm_call(prompt: str, node_name: str, agent_name: str, temperature: float = 0.2) -> str:
    """
    Helper to execute chat completion requests and log them to workflow logger.
    """
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
                "content": prompt
            }
        ],
        "temperature": temperature
    }

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
        raw_content = resp_json["choices"][0]["message"]["content"]
        usage = resp_json.get("usage", {})

        # Log interaction to workflow logger
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
            print(f"[!] Warning logging {agent_name} interaction: {log_err}")

        return raw_content


def init_reformulation(user_query: str) -> bool:
    """
    Init_reformulation:
    Analyzes whether the user query contains referential pronouns ("it's", "that", "those", "this",
    "these", "it", "they", "them", etc.) without an explicit standalone topic name,
    signaling that it requires past conversation context to be understood.

    :param user_query: Raw user query string
    :return: True if reformulation is required, False otherwise.
    """
    cleaned_query = (user_query or "").strip()
    if not cleaned_query:
        return False

    # Fast check: simple greetings don't need reformulation
    lower = cleaned_query.lower().rstrip("!?. ")
    simple_greetings = {"hi", "hello", "hey", "hola", "good morning", "good afternoon", "good evening", "how are you"}
    if lower in simple_greetings:
        return False

    prompt = f"""You are a query analysis agent.
    Determine whether the user query contains ambiguous pronouns or referential phrases without an explicit standalone topic name.

    Rules:
    - If user query contains pronouns such as: "it's", "it", "that", "those", "this", "these", "they", "them", "its", "their", "the same", "above" or elliptical follow-ups without an explicit standalone topic/entity name, then is_reformulation = "True".
        Examples needing reformulation:
        - "what it's advantages" -> True
        - "what are its benefits?" -> True
        - "show that in a chart" -> True
        - "tell me more about those" -> True
        - "compare it with last month" -> True
        - "why is that happening?" -> True
        - "can you put this on a slide?" -> True

    - Else (if the user query already contains an explicit standalone topic, is self-contained, or does not rely on past conversation context), then is_reformulation = "False".
        Examples NOT needing reformulation:
        - "what is machine learning" -> False
        - "show total revenue by region in 2024" -> False
        - "list top 5 customers by sales" -> False
        - "generate 5 slides on renewable energy" -> False
        - "hello" -> False

    USER QUERY:
    "{cleaned_query}"

    RESPONSE FORMAT:
    Respond ONLY with valid JSON:
    {{
        "is_reformulation": "True" | "False",
        "reason": "<short explanation>"
    }}
    
    """

    try:
        raw_output = _execute_llm_call(
            prompt=prompt,
            node_name="Node 0: Init Reformulation Check",
            agent_name="Init Reformulation Agent",
            temperature=0.0
        )
        cleaned_json_str = _clean_json_response(raw_output)
        data = json.loads(cleaned_json_str)
        val = data.get("is_reformulation", "False")

        if isinstance(val, bool):
            return val
        str_val = str(val).strip().lower()
        return str_val in ("true", "yes", "1")
    except Exception as err:
        print(f"[!] Warning in init_reformulation: {err}. Falling back to heuristic check.")
        # Heuristic fallback if LLM call fails
        pronoun_pattern = r"\b(it's|its|it|that|those|this|these|they|them|their)\b"
        return bool(re.search(pronoun_pattern, cleaned_query, re.IGNORECASE))


# Alias matching alternative casing/naming
Init_reformulation = init_reformulation


def QueryReformulateAgent(
    user_query: str,
    project_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Query Reformulation Agent:
    1. Evaluates user_query with init_reformulation().
    2. If is_reformulation is True:
       - Loads the past 5 recent conversations (5 User + 5 AI messages) from the chat_messages table.
       - If conversation context exists, rewrites the query using query_reformulation_prompt.txt.
       - Returns {"reformulated_query": ..., "is_reformulated": True, "reason": ...}
    3. If is_reformulation is False or no history exists:
       - Returns {"reformulated_query": user_query, "is_reformulated": False, "reason": ...}

    :param user_query: Raw user query
    :param project_id: Workspace project ID to query chat_messages
    :param chat_history: Optional explicit list of message dicts [{"role": "User"|"AI", "message": "..."}]
    :return: Dict containing reformulated_query, is_reformulated, and reason.
    """
    cleaned_query = (user_query or "").strip()
    if not cleaned_query:
        return {
            "reformulated_query": cleaned_query,
            "is_reformulated": False,
            "reason": "Empty query."
        }

    # Step 1: Check if query contains pronouns requiring past context
    needs_reformulation = init_reformulation(cleaned_query)
    print(f"[*] [QueryReformulateAgent] init_reformulation returned: {needs_reformulation} for query: '{cleaned_query}'")

    if not needs_reformulation:
        return {
            "reformulated_query": cleaned_query,
            "is_reformulated": False,
            "reason": "Query is standalone and contains no ambiguous referential pronouns."
        }

    # Step 2: Retrieve past 5 recent conversations (5 user + 5 AI) from chat_messages
    history_messages: List[Dict[str, str]] = []
    if chat_history is not None:
        history_messages = chat_history
    elif project_id:
        try:
            from workspace.chat import get_recent_conversations
            history_messages = get_recent_conversations(
                project_id=project_id,
                limit_user=5,
                limit_ai=5,
                exclude_last_user_query=cleaned_query
            )
        except Exception as db_err:
            print(f"[!] Warning fetching recent conversations: {db_err}")

    if not history_messages:
        print("[*] [QueryReformulateAgent] No past conversation history found in chat_messages. Proceeding with original query.")
        return {
            "reformulated_query": cleaned_query,
            "is_reformulated": False,
            "reason": "No prior conversation history available to resolve pronouns."
        }

    # Step 3: Format conversation history for prompt template
    formatted_history_lines = []
    for msg in history_messages:
        role = msg.get("role", "User").strip().capitalize()
        text_content = msg.get("message", "").strip()
        formatted_history_lines.append(f"{role}: {text_content}")

    chat_history_str = "\n".join(formatted_history_lines)

    # Step 4: Load prompt template
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Reformulation prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    formatted_prompt = prompt_template.replace("{{chat_history}}", chat_history_str).replace("{{user_query}}", cleaned_query)

    try:
        raw_output = _execute_llm_call(
            prompt=formatted_prompt,
            node_name="Node 0: Query Reformulation",
            agent_name="Query Reformulation Agent",
            temperature=0.2
        )
        cleaned_json_str = _clean_json_response(raw_output)
        result_json = json.loads(cleaned_json_str)

        rewritten = result_json.get("reformulated_query", "").strip()
        reason = result_json.get("reason", "").strip()

        if rewritten:
            print(f"[+] [QueryReformulateAgent] Reformulated: '{cleaned_query}' -> '{rewritten}' (Reason: {reason})")
            return {
                "reformulated_query": rewritten,
                "is_reformulated": True,
                "reason": reason
            }
        else:
            return {
                "reformulated_query": cleaned_query,
                "is_reformulated": False,
                "reason": "Reformulation output empty, defaulted to original."
            }
    except Exception as err:
        print(f"[!] Warning in QueryReformulateAgent: {err}. Falling back to original query.")
        return {
            "reformulated_query": cleaned_query,
            "is_reformulated": False,
            "reason": f"Exception during reformulation: {err}"
        }


# Typo alias matching user's exact specification "QueeryReformulateAgent"
QueeryReformulateAgent = QueryReformulateAgent
