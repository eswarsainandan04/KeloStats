import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "query_classification_prompt.txt"


def _clean_json_response(raw_response: str) -> str:
    """
    Strips markdown code blocks, reasoning tags, and extracts clean JSON.
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

    # If the entire response is wrapped in markdown code blocks, unwrap it
    match = re.match(r"^```(?:markdown|text)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # Strip surrounding quotes if model enclosed response in quotes
    if len(text) >= 2 and ((text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'"))):
        text = text[1:-1].strip()

    return text


def _execute_llm_call(prompt: str, node_name: str, agent_name: str, temperature: float = 0.3) -> str:
    """
    Helper to execute chat completion requests for text responses and log them to workflow logger.
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

        return _clean_text_response(raw_content)


def handle_greet(user_query: str) -> str:
    """
    Handles user greetings dynamically using an LLM prompt.
    Greets the user warmly and introduces KeloStats capabilities (database analytics & presentation decks).

    :param user_query: The greeting query from the user (e.g., 'hi', 'hello', 'good morning')
    :return: AI greeting response string
    """
    cleaned_query = (user_query or "").strip() or "Hello"

    prompt = f"""You are KeloStats AI Copilot, an enterprise-grade AI analytics and business intelligence assistant.

        The user sent this greeting:
        "{cleaned_query}"

        Task:
        Generate a warm, professional, and courteous greeting response directly addressing the user.
        Briefly explain how you can help them:
        1. Querying and analyzing their connected database (PostgreSQL, MySQL, Oracle SQL) for business metrics and data insights.
        2. Generating boardroom-ready executive presentation slide decks.
        Invite them to ask a data question or request a presentation.

        Guidelines:
        - Keep the response concise, engaging, and professional (2 to 3 sentences max).
        - Do NOT wrap your response in markdown code blocks or quotation marks.
        - Respond directly with the greeting message.
    """

    try:
        return _execute_llm_call(
            prompt=prompt,
            node_name="Node: Handle Greet",
            agent_name="Greeting Handler Agent",
            temperature=0.5
        )
    except Exception as err:
        print(f"[!] Warning in handle_greet: {err}. Falling back to default greeting.")
        return (
            "Hello! I am your KeloStats AI Copilot. I can help you analyze your connected database, "
            "answer analytical questions, or generate executive boardroom presentation decks. "
            "What would you like to explore today?"
        )


def handle_out_of_scope(user_query: str) -> str:
    """
    Handles out-of-scope queries dynamically using an LLM prompt.
    Politely informs the user that the query falls outside KeloStats domain boundaries and guides them back.

    :param user_query: The out-of-scope query from the user
    :return: AI response string explaining domain scope
    """
    cleaned_query = (user_query or "").strip() or "General inquiry"

    prompt = f"""You are KeloStats AI Copilot, an enterprise-grade AI analytics and business intelligence assistant.

        The user asked the following question:
        "{cleaned_query}"

        Context:
        This query is classified as OUT OF SCOPE. KeloStats Copilot specializes strictly in:
        1. Querying and analyzing connected databases (PostgreSQL, MySQL, Oracle SQL) for metrics, reports, and data insights.
        2. Generating boardroom-ready executive presentation slide decks.
        It does not handle unrelated topics such as general trivia, creative writing, programming tutorials, weather, personal advice, or non-business topics.

        Task:
        Politely and professionally inform the user that their request falls outside your domain of expertise.
        Remind them of what you can assist with (analyzing database data or creating presentation decks), and invite them to ask a question related to their database.

        Guidelines:
        - Maintain a courteous, professional, and helpful tone.
        - Do NOT answer the out-of-scope question itself.
        - Keep the response concise (2 to 3 sentences max).
        - Do NOT wrap your response in markdown code blocks or quotation marks.
        - Respond directly with the message text.
    """

    try:
        return _execute_llm_call(
            prompt=prompt,
            node_name="Node: Handle Out Of Scope",
            agent_name="Out of Scope Handler Agent",
            temperature=0.3
        )
    except Exception as err:
        print(f"[!] Warning in handle_out_of_scope: {err}. Falling back to default out-of-scope response.")
        return (
            "I specialize in analyzing your connected database, delivering business insights, and creating "
            "boardroom-ready PowerPoint presentations. Your request appears to be outside this domain. "
            "Please ask a question related to your database or request a presentation slide deck."
        )


def QueryClassificationAgent(user_query: str) -> Dict[str, str]:
    """
    Query Classification Agent:
    - Classifies incoming user query into one of three intents:
      1. 'greet': Simple greeting or polite icebreaker
      2. 'out_of_scope': Irrelevant topic, trivia, entertainment, outside business/data
      3. 'in_scope': Business queries, metrics, reports, presentations, slide decks
    
    :param user_query: Raw user query string
    :return: Dict with 'intent' ("greet" | "out_of_scope" | "in_scope") and 'reason'
    """
    cleaned_query = (user_query or "").strip()
    if not cleaned_query:
        return {
            "intent": "greet",
            "reason": "Empty input defaulted to greeting."
        }

    # Fast heuristic check for simple 1-2 word greetings
    lower_query = cleaned_query.lower()
    simple_greetings = {"hi", "hello", "hey", "hola", "good morning", "good afternoon", "good evening", "how are you"}
    if lower_query in simple_greetings or lower_query.rstrip("!?.") in simple_greetings:
        return {
            "intent": "greet",
            "reason": "Recognized direct greeting phrase."
        }

    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Classification prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    populated_prompt = prompt_template.replace("{{user_query}}", cleaned_query)

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
                "content": populated_prompt
            }
        ],
        "temperature": 0.0
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

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_bytes = resp.read()
            resp_json = json.loads(resp_bytes.decode("utf-8"))
            raw_content = resp_json["choices"][0]["message"]["content"]
            usage = resp_json.get("usage", {})

            # Log interaction to workflow logger
            try:
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name="Node: Query Classification",
                    agent_name="Query Classification Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging classification agent interaction: {log_err}")

            cleaned_json = _clean_json_response(raw_content)
            result = json.loads(cleaned_json)
            intent = str(result.get("intent", "in_scope")).lower().strip()
            reason = result.get("reason", "Query classified successfully.")

            if intent not in ["greet", "out_of_scope", "in_scope"]:
                intent = "in_scope"

            return {
                "intent": intent,
                "reason": reason
            }

    except Exception as err:
        print(f"[!] Warning in QueryClassificationAgent: {err}. Defaulting to in_scope.")
        return {
            "intent": "in_scope",
            "reason": f"Fallback classification due to exception: {str(err)}"
        }
