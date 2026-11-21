import os
import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Union

from app.core.config import settings

# In-memory cache for local fallback models if sentence_transformers is ever used
_MODEL_CACHE: Dict[str, Any] = {}


def _embed_gemini_single(
    text_content: str,
    model_name: str = "gemini-embedding-2",
    api_key: Optional[str] = None
) -> List[float]:
    """Generates embedding for a single text using Google Gemini API embedContent."""
    key = api_key or os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None)
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")

    clean_model = model_name.removeprefix("models/").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:embedContent?key={key}"
    payload = {
        "content": {
            "parts": [{"text": str(text_content).strip()}]
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res.get("embedding", {}).get("values", [])


def _embed_gemini_batch(
    texts: List[str],
    model_name: str = "gemini-embedding-2",
    api_key: Optional[str] = None,
    batch_size: int = 50
) -> List[List[float]]:
    """Generates embeddings for multiple texts using Google Gemini API batchEmbedContents."""
    key = api_key or os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None)
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")

    clean_model = model_name.removeprefix("models/").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:batchEmbedContents?key={key}"

    all_embeddings: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        requests_list = [
            {
                "model": f"models/{clean_model}",
                "content": {"parts": [{"text": str(t)}]}
            }
            for t in batch
        ]
        payload = {"requests": requests_list}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            for item in res.get("embeddings", []):
                all_embeddings.append(item.get("values", []))

    return all_embeddings


def generate_embeddings(
    texts: Union[str, List[str]],
    embedding_model: Optional[str] = None,
    api_key: Optional[str] = None,
    batch_size: int = 50,
) -> Union[List[float], List[List[float]]]:
    """
    Universal embedding generator for KeloStats.
    - If `texts` is a single string: returns a single embedding vector `List[float]`.
    - If `texts` is a list of strings: returns `List[List[float]]`.

    By default uses cloud-native Google Gemini Embedding API (gemini-embedding-2)
    with zero PyTorch / sentence-transformers dependency.
    """
    if texts is None:
        return []

    is_single = isinstance(texts, str)
    text_list = [texts] if is_single else [str(t) for t in texts]

    if not text_list:
        return [] if not is_single else []

    # Handle empty single query
    if is_single and not text_list[0].strip():
        return []

    # Resolve model name
    model_name = (
        embedding_model.strip()
        if (embedding_model and str(embedding_model).strip())
        else (getattr(settings, "EMBEDDING_MODEL", None) or os.getenv("EMBEDDING_MODEL", "gemini-embedding-2"))
    )

    is_gemini = (
        "gemini" in model_name.lower()
        or "embedding-2" in model_name.lower()
        or "embedding-001" in model_name.lower()
        or "text-embedding" in model_name.lower()
    )

    if is_gemini:
        if is_single:
            return _embed_gemini_single(text_list[0], model_name=model_name, api_key=api_key)
        else:
            return _embed_gemini_batch(text_list, model_name=model_name, api_key=api_key, batch_size=batch_size)
    else:
        # Fallback to local model (SentenceTransformer) if explicitly configured
        if model_name not in _MODEL_CACHE:
            from sentence_transformers import SentenceTransformer
            _MODEL_CACHE[model_name] = SentenceTransformer(model_name)

        model = _MODEL_CACHE[model_name]
        if is_single:
            emb = model.encode(text_list[0], show_progress_bar=False, convert_to_numpy=True)
            return emb.tolist() if hasattr(emb, "tolist") else [float(x) for x in emb]
        else:
            raw_embs = model.encode(text_list, show_progress_bar=False, convert_to_numpy=True)
            return [
                (e.tolist() if hasattr(e, "tolist") else [float(x) for x in e])
                for e in raw_embs
            ]
