import os
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv

# Ensure .env is loaded
env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# ==============================================================================
# Default LLM Credentials from .env
# ==============================================================================
DEFAULT_API_KEY = os.getenv("LLM_API_KEY", "")
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
DEFAULT_MODEL_NAME = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

# Specialized Overrides (if specified in .env)
PPT_BASE_URL = os.getenv("PPT_GENERATION_LLM_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
PPT_MODEL = os.getenv("PPT_GENERATION_LLM_MODEL", "z-ai/glm-5.3-flash")
PPT_API_KEY = os.getenv("PPT_GENERATION_LLM_API_KEY", DEFAULT_API_KEY)

PLANNING_BASE_URL = os.getenv("PLANNING_LLM_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
PLANNING_MODEL = os.getenv("PLANNING_LLM_MODEL", "z-ai/glm-5.3-flash")
PLANNING_API_KEY = os.getenv("PLANNING_LLM_API_KEY", DEFAULT_API_KEY)


# ==============================================================================
# Agent Model Mapping Dictionary
# ==============================================================================
AGENT_MODELS: Dict[str, Dict[str, Any]] = {
    # 1. Classification & Intent Guard
    "query_classification_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.0,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 2. Decision & Architecture Routing
    "query_decision_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.0,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 3. Query Reformulation & Ambiguity Resolution
    "query_reformulate_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.2,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 4. Schema Verification & Column Matching
    "query_verification_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.0,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 5. Entity Value Retrieval (ILike/Fuzzy Value Finder)
    "retrieval_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.1,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 6. SQL Query Generation
    "sql_writer_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.1,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 7. SQL Error Correction & Self-Healing
    "sql_repair_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.1,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 8. General Q&A / Conversational Answer Generator
    "answer_generator_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.3,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 9. Document RAG & Knowledge Synthesizer
    "knowledge_answer_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.3,
        "API_KEY": DEFAULT_API_KEY,
    },

    # 10. Presentation Slide Layout & Canvas Planner
    "slide_planning_agent": {
        "BASE_URL": PLANNING_BASE_URL,
        "MODEL_NAME": PLANNING_MODEL,
        "TEMPERATURE": 0.2,
        "API_KEY": PLANNING_API_KEY,
    },

    # 11. Document RAG Slide Canvas Planner
    "rag_planner_agent": {
        "BASE_URL": PLANNING_BASE_URL,
        "MODEL_NAME": PLANNING_MODEL,
        "TEMPERATURE": 0.2,
        "API_KEY": PLANNING_API_KEY,
    },

    # 12. Full SVG Slide Deck Generator
    "ppt_generation_agent": {
        "BASE_URL": PPT_BASE_URL,
        "MODEL_NAME": PPT_MODEL,
        "TEMPERATURE": 0.2,
        "API_KEY": PPT_API_KEY,
    },

    # 13. Slide Validation & Syntax Guard
    "validate_slide_code_agent": {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.1,
        "API_KEY": DEFAULT_API_KEY,
    },
}


# ==============================================================================
# Helper Resolver Function
# ==============================================================================
def get_agent_config(agent_name: str) -> Dict[str, Any]:
    """
    Retrieves the LLM configuration (BASE_URL, MODEL_NAME, TEMPERATURE, API_KEY)
    for a given agent name.

    Supports exact filename keys (e.g. 'sql_writer_agent'), shortened keys ('sql_writer'),
    or display names ('SQL Writer Agent').
    """
    if not agent_name:
        return {
            "BASE_URL": DEFAULT_BASE_URL,
            "MODEL_NAME": DEFAULT_MODEL_NAME,
            "TEMPERATURE": 0.2,
            "API_KEY": DEFAULT_API_KEY,
        }

    # 1. Exact match check
    if agent_name in AGENT_MODELS:
        return AGENT_MODELS[agent_name]

    # 2. Normalized lowercase underscore matching
    normalized = agent_name.lower().strip().replace(" ", "_").replace("-", "_")
    if normalized in AGENT_MODELS:
        return AGENT_MODELS[normalized]

    # 3. Add '_agent' suffix if omitted (e.g. 'sql_writer' -> 'sql_writer_agent')
    with_suffix = f"{normalized}_agent" if not normalized.endswith("_agent") else normalized
    if with_suffix in AGENT_MODELS:
        return AGENT_MODELS[with_suffix]

    # 4. Fallback to default credentials from .env
    return {
        "BASE_URL": DEFAULT_BASE_URL,
        "MODEL_NAME": DEFAULT_MODEL_NAME,
        "TEMPERATURE": 0.2,
        "API_KEY": DEFAULT_API_KEY,
    }


__all__ = [
    "AGENT_MODELS",
    "get_agent_config",
    "DEFAULT_API_KEY",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL_NAME",
]
