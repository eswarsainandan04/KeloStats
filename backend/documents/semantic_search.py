import html
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Ensure backend root and documents directory are in sys.path
documents_dir = Path(__file__).resolve().parent
backend_dir = documents_dir.parent
for p in (str(backend_dir), str(documents_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load environment variables
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Module-level model cache to avoid reloading model weights
_MODEL_CACHE: Dict[str, Any] = {}

# Default search parameters
relevant_filter = 0.30
top_k = 5


def generate_query_embeddings(
    query: str,
    embedding_model: Optional[str] = None,
) -> List[float]:
    """Generates a dense vector embedding for a search query.

    Args:
        query: The user search query string.
        embedding_model: Optional model name (defaults to EMBEDDING_MODEL in .env or 'all-MiniLM-L6-v2').

    Returns:
        embedded_query: List of floats representing the query vector.
    """
    if not query or not str(query).strip():
        print("[SemanticSearch] [!] Empty query provided; returning empty embedding.")
        return []

    # Resolve model name from argument or .env
    model_name = (
        embedding_model.strip()
        if (embedding_model and str(embedding_model).strip())
        else os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )

    clean_query = str(query).strip()
    print(f"[SemanticSearch] Generating query embedding for: '{clean_query[:60]}...'")

    if model_name not in _MODEL_CACHE:
        print(f"[SemanticSearch] Loading embedding model '{model_name}' into memory...")
        from sentence_transformers import SentenceTransformer
        _MODEL_CACHE[model_name] = SentenceTransformer(model_name)
        print(f"[SemanticSearch] [+] Embedding model '{model_name}' loaded successfully.")
    else:
        print(f"[SemanticSearch] Using cached embedding model '{model_name}'.")

    model = _MODEL_CACHE[model_name]

    # Generate query embedding vector
    emb = model.encode(clean_query, show_progress_bar=False, convert_to_numpy=True)
    embedded_query: List[float] = (
        emb.tolist() if hasattr(emb, "tolist") else [float(x) for x in emb]
    )

    print(f"[SemanticSearch] [+] Query embedding generated (dimension: {len(embedded_query)}).")
    return embedded_query


def semantic_search(
    embedded_query: Union[List[float], Any],
    collection_id: Optional[str] = None,
    document_id: Optional[str] = None,
    top_k: int = top_k,
    relevant_filter: float = relevant_filter,
) -> List[Dict[str, Any]]:
    """Searches and retrieves the most relevant chunks for a collection_id or document_id.

    Rules:
    - If collection_id is provided, searches across all documents belonging to that collection pool.
    - If document_id is provided, scopes the search to that specific document.
    - If the 2nd positional argument starts with 'doc_', it automatically maps to document_id for backwards compatibility.
    - If relevance score is 0% or lower (similarity <= relevant_filter), chunk is not retrieved.
    - Retrieves up to top_k chunks, ordered by cosine similarity score descending.

    Args:
        embedded_query: The query vector (list of floats).
        collection_id: Target collection ID (pool_UUID) to search across.
        document_id: Optional target document ID (doc_UUID).
        top_k: Maximum number of chunks to return (default: 10).
        relevant_filter: Minimum similarity threshold (> relevant_filter, default: 0.0).

    Returns:
        retrieved_chunks: List of retrieved chunks with metadata and similarity score.
    """
    if not embedded_query:
        print("[SemanticSearch] [!] No query embedding provided.")
        return []

    # Automatic disambiguation if 2nd positional argument was passed
    resolved_collection_id = str(collection_id).strip() if collection_id else None
    resolved_document_id = str(document_id).strip() if document_id else None

    if resolved_collection_id and resolved_collection_id.startswith("doc_") and not resolved_document_id:
        # Handled backwards-compatibility: 2nd argument was a document_id
        resolved_document_id = resolved_collection_id
        resolved_collection_id = None

    if not resolved_collection_id and not resolved_document_id:
        print("[SemanticSearch] [!] Neither collection_id nor document_id provided for scoped semantic search.")
        return []

    # Format vector into pgvector string representation: '[0.123, -0.045, ...]'
    if isinstance(embedded_query, (list, tuple)):
        vector_str = "[" + ",".join(str(float(x)) for x in embedded_query) + "]"
    elif isinstance(embedded_query, str):
        vector_str = embedded_query
    else:
        vector_str = str(embedded_query)

    where_clauses = ["(1 - (embedding <=> CAST(:query_vector AS vector))) > :relevant_filter"]
    params: Dict[str, Any] = {
        "query_vector": vector_str,
        "relevant_filter": float(relevant_filter),
        "top_k": int(top_k),
    }

    if resolved_collection_id:
        where_clauses.append("collection_id = :collection_id")
        params["collection_id"] = resolved_collection_id
        print(f"[SemanticSearch] Searching document_chunks for collection_id: '{resolved_collection_id}'")

    if resolved_document_id:
        where_clauses.append("document_id = :document_id")
        params["document_id"] = resolved_document_id
        print(f"[SemanticSearch] Searching document_chunks for document_id: '{resolved_document_id}'")

    print(f"[SemanticSearch] Constraints: top_k={top_k}, relevant_filter={relevant_filter} (>0% relevance)")

    query_sql = f"""
        SELECT 
            chunk_id,
            collection_id,
            document_id,
            chunk_index,
            context,
            (1 - (embedding <=> CAST(:query_vector AS vector))) AS similarity_score
        FROM document_chunks
        WHERE {' AND '.join(where_clauses)}
        ORDER BY similarity_score DESC
        LIMIT :top_k;
    """

    try:
        with engine.connect() as conn:
            results = conn.execute(
                text(query_sql),
                params
            ).mappings().fetchall()

        retrieved_chunks: List[Dict[str, Any]] = []
        for row in results:
            score = float(row["similarity_score"])
            retrieved_chunks.append({
                "chunk_id": str(row["chunk_id"]),
                "collection_id": str(row["collection_id"]) if row.get("collection_id") else None,
                "document_id": str(row["document_id"]),
                "chunk_index": row["chunk_index"],
                "context": row["context"],
                "similarity_score": round(score, 4),
            })

        print(f"[SemanticSearch] [+] Retrieved {len(retrieved_chunks)} relevant chunk(s).")
        if retrieved_chunks:
            top_score = retrieved_chunks[0]["similarity_score"]
            lowest_score = retrieved_chunks[-1]["similarity_score"]
            print(f"[SemanticSearch] Score range: {top_score:.4f} (best) down to {lowest_score:.4f}")

        return retrieved_chunks

    except Exception as err:
        print(f"[SemanticSearch] [-] Database search error: {err}", file=sys.stderr)
        raise err


def hybrid_search(
    query_text: str,
    embedded_query: Union[List[float], Any],
    collection_id: Optional[str] = None,
    document_id: Optional[str] = None,
    top_k: int = top_k,
    relevant_filter: float = relevant_filter,
) -> List[Dict[str, Any]]:
    """Hybrid search: exact keyword chunks first, then vector chunks appended.

    Strategy:
      1. EXACT KEYWORD SEARCH — find chunks that contain the actual query words
         using Postgres full-text (tsvector). These rank FIRST because they have
         the exact topic/heading you're looking for (e.g. "Leave Policy").
         Sorted by how many query words match (ts_rank descending).

      2. VECTOR SEARCH — find semantically similar chunks via cosine similarity.
         These are appended AFTER the exact matches, skipping any already found
         in step 1 (no duplicates).

    Result = [exact_keyword_chunks...] + [vector_only_chunks...]
    Total capped at top_k.

    Args:
        query_text: Raw user query string (used for exact keyword matching).
        embedded_query: Dense vector of the query (used for semantic search).
        collection_id: Scope search to this collection.
        document_id: Scope search to this specific document.
        top_k: Max total chunks to return.
        relevant_filter: Min cosine similarity threshold for vector candidates.

    Returns:
        List of chunks — exact keyword matches first, then vector matches.
    """
    if not query_text or not embedded_query:
        print("[HybridSearch] [!] Missing query text or embedding — falling back to semantic_search.")
        return semantic_search(
            embedded_query=embedded_query,
            collection_id=collection_id,
            document_id=document_id,
            top_k=top_k,
            relevant_filter=relevant_filter,
        )

    # ── Resolve scope ──────────────────────────────────────────────────────────
    resolved_collection_id = str(collection_id).strip() if collection_id else None
    resolved_document_id = str(document_id).strip() if document_id else None

    if resolved_collection_id and resolved_collection_id.startswith("doc_") and not resolved_document_id:
        resolved_document_id = resolved_collection_id
        resolved_collection_id = None

    if not resolved_collection_id and not resolved_document_id:
        print("[HybridSearch] [!] No collection_id or document_id provided.")
        return []

    # Shared scope WHERE + params
    scope_clauses: List[str] = []
    scope_params: Dict[str, Any] = {}
    if resolved_collection_id:
        scope_clauses.append("collection_id = :collection_id")
        scope_params["collection_id"] = resolved_collection_id
    if resolved_document_id:
        scope_clauses.append("document_id = :document_id")
        scope_params["document_id"] = resolved_document_id
    scope_where = (" AND " + " AND ".join(scope_clauses)) if scope_clauses else ""

    # Format embedding vector
    if isinstance(embedded_query, (list, tuple)):
        vector_str = "[" + ",".join(str(float(x)) for x in embedded_query) + "]"
    else:
        vector_str = str(embedded_query)

    clean_query = str(query_text).strip()
    print(f"[HybridSearch] Query: '{clean_query[:80]}'")

    # ── STEP 1: Exact keyword search ───────────────────────────────────────────
    # Find chunks that literally contain the query words.
    # plainto_tsquery handles multi-word: "Leave Policy" → 'leave' & 'policy'
    # phraseto_tsquery would require exact phrase order — plainto_tsquery is more flexible.
    exact_sql = f"""
        SELECT
            chunk_id,
            collection_id,
            document_id,
            chunk_index,
            context,
            ts_rank(
                to_tsvector('english', context),
                plainto_tsquery('english', :query_text)
            ) AS text_score
        FROM document_chunks
        WHERE to_tsvector('english', context) @@ plainto_tsquery('english', :query_text)
        {scope_where}
        ORDER BY text_score DESC
        LIMIT :top_k;
    """
    exact_params = {"query_text": clean_query, "top_k": top_k, **scope_params}

    # ── STEP 2: Vector search ─────────────────────────────────────────────────
    vector_sql = f"""
        SELECT
            chunk_id,
            collection_id,
            document_id,
            chunk_index,
            context,
            (1 - (embedding <=> CAST(:query_vector AS vector))) AS vector_score
        FROM document_chunks
        WHERE (1 - (embedding <=> CAST(:query_vector AS vector))) > :relevant_filter
        {scope_where}
        ORDER BY vector_score DESC
        LIMIT :top_k;
    """
    vector_params = {
        "query_vector": vector_str,
        "relevant_filter": float(relevant_filter),
        "top_k": top_k,
        **scope_params,
    }

    exact_rows: List[Dict[str, Any]] = []
    vector_rows: List[Dict[str, Any]] = []

    try:
        with engine.connect() as conn:
            e_results = conn.execute(text(exact_sql), exact_params).mappings().fetchall()
            exact_rows = [dict(row) for row in e_results]
            print(f"[HybridSearch] Exact keyword matches → {len(exact_rows)} chunk(s)")

            v_results = conn.execute(text(vector_sql), vector_params).mappings().fetchall()
            vector_rows = [dict(row) for row in v_results]
            print(f"[HybridSearch] Vector matches       → {len(vector_rows)} chunk(s)")

    except Exception as err:
        print(f"[HybridSearch] [-] DB error: {err} — falling back to semantic_search.", file=sys.stderr)
        return semantic_search(
            embedded_query=embedded_query,
            collection_id=collection_id,
            document_id=document_id,
            top_k=top_k,
            relevant_filter=relevant_filter,
        )

    # ── STEP 3: Merge — exact keyword first, then append vector (no duplicates) ─
    seen_ids: set = set()
    merged: List[Dict[str, Any]] = []

    # Priority 1: exact keyword chunks (contain the actual query words)
    for row in exact_rows:
        cid = str(row["chunk_id"])
        if cid not in seen_ids:
            seen_ids.add(cid)
            merged.append({
                "chunk_id": cid,
                "collection_id": str(row["collection_id"]) if row.get("collection_id") else None,
                "document_id": str(row["document_id"]),
                "chunk_index": row["chunk_index"],
                "context": row["context"],
                "similarity_score": round(float(row["text_score"]), 6),
                "match_type": "exact_keyword",
            })

    # Priority 2: vector chunks — append only if NOT already in exact results
    for row in vector_rows:
        cid = str(row["chunk_id"])
        if cid not in seen_ids:
            seen_ids.add(cid)
            merged.append({
                "chunk_id": cid,
                "collection_id": str(row["collection_id"]) if row.get("collection_id") else None,
                "document_id": str(row["document_id"]),
                "chunk_index": row["chunk_index"],
                "context": row["context"],
                "similarity_score": round(float(row["vector_score"]), 4),
                "match_type": "vector",
            })

    # Cap at top_k
    result = merged[:top_k]

    print(f"[HybridSearch] [+] Final: {len(result)} chunk(s) "
          f"({sum(1 for c in result if c['match_type'] == 'exact_keyword')} exact + "
          f"{sum(1 for c in result if c['match_type'] == 'vector')} vector)")

    return result




def context_parser(retrieved_chunks: Union[List[Dict[str, Any]], Dict[str, Any], Any]) -> str:
    """Parses retrieved chunks into clean, pure markdown text format.

    - Strips all HTML tags (e.g., <mark>, <span>, etc.) and unescapes HTML entities.
    - Eliminates raw escaped newlines (e.g., '\\n') and standardizes line breaks.
    - Preserves pure Markdown formatting.
    - Formats each chunk under a 'chunk no:' header.
    - Separates consecutive chunks with '------------------------------------'.

    Args:
        retrieved_chunks: A list of chunk dicts, a single chunk dict, or raw chunks.

    Returns:
        Clean formatted Markdown string ready to be passed to LLM agents.
    """
    if not retrieved_chunks:
        return ""

    if isinstance(retrieved_chunks, dict):
        chunks_list = [retrieved_chunks]
    elif isinstance(retrieved_chunks, (list, tuple)):
        chunks_list = list(retrieved_chunks)
    elif isinstance(retrieved_chunks, str):
        return retrieved_chunks.strip()
    else:
        chunks_list = list(retrieved_chunks)

    formatted_chunks: List[str] = []

    for chunk in chunks_list:
        if isinstance(chunk, dict):
            raw_text = chunk.get("context") or chunk.get("text") or ""
        else:
            raw_text = str(chunk)

        if not raw_text or not str(raw_text).strip():
            continue

        # Convert literal escaped newline characters and carriage returns
        text_content = (
            str(raw_text)
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )

        # Unescape HTML entities (e.g. &amp; -> &, &lt; -> <)
        text_content = html.unescape(text_content)

        # Strip all HTML tags (e.g. <mark>, </mark>, <div>, etc.)
        text_content = re.sub(r"<[^>]+>", "", text_content)

        # Normalize line endings and whitespace per line
        lines = [line.strip() for line in text_content.split("\n")]

        # Collapse excessive consecutive blank lines into at most one blank line
        cleaned_lines: List[str] = []
        for line in lines:
            if line:
                cleaned_lines.append(line)
            elif cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")

        clean_markdown = "\n".join(cleaned_lines).strip()
        if clean_markdown:
            formatted_chunks.append(f"chunk:\n{clean_markdown}")

    separator = "\n------------------------------------\n"
    return separator.join(formatted_chunks)


if __name__ == "__main__":
    sample_retrieved = [
        {
            "chunk_id": "942736fe-bbaf-4289-84f5-eb309959b345",
            "document_id": "doc_8d62303d-a418-4c7e-a8d8-10893dffa9c9",
            "chunk_index": 101,
            "context": "**Example for Cardinality – Many-to-One (M :1)**\n\nIt is the reverse of the One to Many relationship. employee works in organization\n\n<mark>One employee works in only one organization But one organization can have many employees. Hence it is a</mark>\nM:1 relationship and cardinality is Many-to-One (M :1)\n\nIn ER modeling, this can be mentioned using notations as given below.",
            "similarity_score": 0.432,
        }
    ]
    print("[SemanticSearch] Context Parser Output:\n")
    print(context_parser(sample_retrieved))
