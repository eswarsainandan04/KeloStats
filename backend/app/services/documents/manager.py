import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text

from app.core.config import settings
from app.core.storage import get_storage
from app.services.connectors import app_db_engine as engine


# ==============================================================================
# Collection Management
# ==============================================================================

def create_collection(user_id: str, display_name: str) -> Dict[str, Any]:
    """
    Creates a new vectorized collection pool for a user:
    - Generates collection_id formatted as pool_{UUID}
    - Inserts a record into user_collections (display_name, documents=[], total_files=0)
    - Creates a storage folder placeholder: documents/{user_id}/{collection_id}/.keep
    """
    clean_user_id = str(user_id).strip()
    clean_name = str(display_name or "").strip()

    if not clean_user_id:
        raise ValueError("user_id is required to create a collection.")
    if not clean_name:
        raise ValueError("display_name is required to create a collection.")

    collection_id = f"pool_{uuid.uuid4()}"
    folder_prefix = f"documents/{clean_user_id}/{collection_id}/"

    # 1. Create storage folder placeholder via unified storage adapter
    try:
        storage = get_storage()
        storage.create(f"{folder_prefix}.keep", b"")
        print(f"[DocumentManager] [+] Created storage folder placeholder: {folder_prefix}.keep")
    except Exception as err:
        print(f"[DocumentManager] [!] Storage folder creation note: {err}")

    # 2. Insert record into user_collections table
    insert_sql = """
        INSERT INTO user_collections (
            collection_id,
            user_id,
            display_name,
            documents,
            total_files,
            created_at,
            updated_at
        ) VALUES (
            :collection_id,
            :user_id,
            :display_name,
            '[]'::jsonb,
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        );
    """

    try:
        print(f"[DocumentManager] Creating user_collections record '{collection_id}' ('{clean_name}') for user '{clean_user_id}'...")
        with engine.connect() as conn:
            conn.execute(
                text(insert_sql),
                {
                    "collection_id": collection_id,
                    "user_id": clean_user_id,
                    "display_name": clean_name,
                }
            )
            conn.commit()
            print(f"[DocumentManager] [+] Successfully created collection: {collection_id}")
    except Exception as db_err:
        print(f"[DocumentManager] [-] Database error creating user_collections: {db_err}", file=sys.stderr)
        raise RuntimeError(f"Failed to create collection in database: {str(db_err)}") from db_err

    return {
        "collection_id": collection_id,
        "user_id": clean_user_id,
        "display_name": clean_name,
        "total_files": 0,
        "documents": [],
        "storage_folder": folder_prefix,
        "s3_folder": folder_prefix,
    }


def get_collection(collection_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single user_collections row by collection_id (and optionally user_id).
    """
    clean_coll_id = str(collection_id).strip()
    select_sql = """
        SELECT collection_id, user_id, display_name, documents, total_files, created_at, updated_at
        FROM user_collections
        WHERE collection_id = :collection_id
    """
    params: Dict[str, Any] = {"collection_id": clean_coll_id}
    if user_id:
        select_sql += " AND user_id = :user_id"
        params["user_id"] = str(user_id).strip()

    with engine.connect() as conn:
        row = conn.execute(text(select_sql), params).mappings().first()
        return dict(row) if row else None


def update_collection_documents_registry(
    collection_id: str,
    document_id: str,
    file_name: str,
) -> None:
    """
    Appends a new document entry {document_id, file_name} to the user_collections.documents
    JSON array and increments total_files count.
    """
    clean_collection_id = str(collection_id).strip()
    doc_entry = json.dumps([{"document_id": document_id, "file_name": file_name}])

    update_sql = """
        UPDATE user_collections
        SET documents = COALESCE(documents, '[]'::jsonb) || CAST(:doc_entry AS jsonb),
            total_files = COALESCE(total_files, 0) + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE collection_id = :collection_id;
    """

    try:
        with engine.connect() as conn:
            conn.execute(
                text(update_sql),
                {
                    "collection_id": clean_collection_id,
                    "doc_entry": doc_entry,
                }
            )
            conn.commit()
            print(f"[DocumentManager] [+] Updated user_collections ({clean_collection_id}) registry with: {document_id} ({file_name})")
    except Exception as err:
        print(f"[DocumentManager] [-] Failed to update collection documents registry: {err}", file=sys.stderr)
        raise RuntimeError(f"Failed to update collection registry: {str(err)}") from err


# ==============================================================================
# Document Record & Chunk Management
# ==============================================================================

def save_document_record(
    user_id: str,
    file_name: str,
    file_bytes: bytes,
    collection_id: Optional[str] = None,
    file_type: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extracts metadata from file bytes, uploads to storage using the unified adapter,
    and inserts a record into users_documents.
    """
    clean_user_id = str(user_id).strip()
    clean_file_name = Path(file_name).name
    file_size = len(file_bytes)

    # Determine file type
    ext = Path(clean_file_name).suffix.lstrip(".").lower()
    inferred_type = file_type or ext or "pdf"

    print(f"[DocumentManager] Processing upload for file: '{clean_file_name}' ({file_size / 1024:.2f} KB, user_id: {clean_user_id})")

    # Extract total page count if PDF
    total_pages = 1
    if inferred_type == "pdf" or (content_type and "pdf" in content_type):
        try:
            import pymupdf
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
            total_pages = len(doc)
            doc.close()
        except Exception as e:
            print(f"[DocumentManager] [!] Warning extracting PDF pages: {e}")
            total_pages = 1

    # Generate document_id as doc_{UUID}
    document_id = f"doc_{uuid.uuid4()}"
    clean_coll_id = str(collection_id).strip() if collection_id else None

    # Determine storage key: documents/{user_id}/{collection_id}/{file_name}
    if clean_coll_id:
        storage_key = f"documents/{clean_user_id}/{clean_coll_id}/{clean_file_name}"
    else:
        storage_key = f"documents/{clean_user_id}/{clean_file_name}"

    # Upload using unified storage adapter
    try:
        storage = get_storage()
        ct = content_type or ("application/pdf" if inferred_type == "pdf" else "application/octet-stream")
        storage.create(key=storage_key, data=file_bytes, content_type=ct)
        print(f"[DocumentManager] [+] Successfully uploaded to storage: {storage_key}")
    except Exception as s_err:
        print(f"[DocumentManager] [-] Storage upload error: {s_err}", file=sys.stderr)
        raise RuntimeError(f"Failed to upload document to storage: {str(s_err)}") from s_err

    # Insert record into PostgreSQL users_documents table
    insert_sql = """
        INSERT INTO users_documents (
            document_id,
            user_id,
            file_name,
            file_type,
            file_size,
            total_pages,
            created_at,
            updated_at
        ) VALUES (
            :document_id,
            :user_id,
            :file_name,
            :file_type,
            :file_size,
            :total_pages,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        );
    """

    try:
        print(f"[DocumentManager] Inserting metadata into 'users_documents' table (document_id: {document_id})...")
        with engine.connect() as conn:
            conn.execute(
                text(insert_sql),
                {
                    "document_id": document_id,
                    "user_id": clean_user_id,
                    "file_name": clean_file_name,
                    "file_type": inferred_type,
                    "file_size": file_size,
                    "total_pages": total_pages,
                }
            )
            conn.commit()
            print(f"[DocumentManager] [+] Document record inserted into users_documents: {document_id}")
    except Exception as db_err:
        print(f"[DocumentManager] [-] Database insert error: {db_err}", file=sys.stderr)
        raise RuntimeError(f"Failed to record document in database: {str(db_err)}") from db_err

    return {
        "document_id": document_id,
        "user_id": clean_user_id,
        "collection_id": clean_coll_id,
        "file_name": clean_file_name,
        "file_type": inferred_type,
        "file_size": file_size,
        "total_pages": total_pages,
        "storage_path": storage_key,
        "s3_path": storage_key,
    }


def upsert_chunks(
    embedded_chunks: List[Dict[str, Any]],
    document_id: str,
    collection_id: Optional[str] = None,
) -> int:
    """
    Inserts each chunk and its vector embedding into the document_chunks table:
      chunk_id: UUID
      collection_id: pool_UUID (or null if standalone)
      document_id: doc_UUID
      chunk_index: int
      context: text
      embedding: vector
    """
    if not embedded_chunks:
        print(f"[DocumentManager] [!] No chunks provided to upsert for document_id: {document_id}")
        return 0

    print(f"[DocumentManager] Starting upsert of {len(embedded_chunks)} chunk(s) into 'document_chunks' table (collection_id: {collection_id}, document_id: {document_id})...")

    insert_sql = """
        INSERT INTO document_chunks (
            collection_id,
            document_id,
            chunk_index,
            context,
            embedding
        ) VALUES (
            :collection_id,
            :document_id,
            :chunk_index,
            :context,
            CAST(:embedding AS vector)
        );
    """

    clean_coll_id = str(collection_id).strip() if collection_id else None
    records = []
    for idx, item in enumerate(embedded_chunks):
        emb = item.get("embeddings") or item.get("embedding")
        context_text = item.get("context", "")

        # Format embedding vector as '[0.122, 0.234, ...]'
        if isinstance(emb, (list, tuple)):
            emb_str = "[" + ",".join(str(float(x)) for x in emb) + "]"
        elif isinstance(emb, str):
            emb_str = emb
        else:
            emb_str = str(emb)

        records.append({
            "collection_id": clean_coll_id,
            "document_id": str(document_id),
            "chunk_index": idx,
            "context": context_text,
            "embedding": emb_str,
        })

    try:
        with engine.connect() as conn:
            conn.execute(text(insert_sql), records)
            conn.commit()
        print(f"[DocumentManager] [+] Successfully inserted {len(records)} chunks for document: {document_id} (collection_id: {clean_coll_id})")
        return len(records)
    except Exception as db_err:
        print(f"[DocumentManager] [-] Database insert error into document_chunks: {db_err}", file=sys.stderr)
        raise RuntimeError(f"Failed to record document chunks in database: {str(db_err)}") from db_err


# ==============================================================================
# Queries & Deletions
# ==============================================================================

def list_user_collections(user_id: str) -> List[Dict[str, Any]]:
    """
    Lists all collections for the user with enriched document metadata manifests.
    """
    clean_user_id = str(user_id).strip()
    if not clean_user_id:
        return []

    select_coll_sql = """
        SELECT collection_id, user_id, display_name, documents, total_files, created_at, updated_at
        FROM user_collections
        WHERE user_id = :user_id
        ORDER BY created_at DESC;
    """

    doc_info_sql = """
        SELECT document_id, file_name, file_type, file_size, total_pages, created_at
        FROM users_documents
        WHERE user_id = :user_id;
    """

    with engine.connect() as conn:
        coll_rows = conn.execute(text(select_coll_sql), {"user_id": clean_user_id}).mappings().all()
        doc_rows = conn.execute(text(doc_info_sql), {"user_id": clean_user_id}).mappings().all()

    # Build document lookup map
    doc_map: Dict[str, Dict[str, Any]] = {}
    for dr in doc_rows:
        doc_map[str(dr["document_id"])] = {
            "document_id": str(dr["document_id"]),
            "file_name": dr["file_name"],
            "file_type": dr["file_type"] or "pdf",
            "file_size": dr["file_size"],
            "total_pages": dr["total_pages"],
            "created_at": dr["created_at"].isoformat() if dr["created_at"] else None,
        }

    collections: List[Dict[str, Any]] = []
    for r in coll_rows:
        raw_docs = r["documents"] if r["documents"] is not None else []
        enriched_docs: List[Dict[str, Any]] = []
        for d in raw_docs:
            did = str(d.get("document_id") if isinstance(d, dict) else d)
            info = doc_map.get(did, {})
            enriched_docs.append({
                "document_id": did,
                "file_name": d.get("file_name") if isinstance(d, dict) and d.get("file_name") else info.get("file_name", "document.pdf"),
                "file_type": info.get("file_type", "pdf"),
                "file_size": info.get("file_size", 0),
                "total_pages": info.get("total_pages", 0),
                "created_at": info.get("created_at"),
            })

        collections.append({
            "collection_id": str(r["collection_id"]),
            "user_id": str(r["user_id"]),
            "display_name": r["display_name"],
            "documents": enriched_docs,
            "total_files": len(enriched_docs) if enriched_docs else (r["total_files"] or 0),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        })

    return collections


def delete_collection(collection_id: str, user_id: Optional[str] = None) -> bool:
    """
    Deletes a collection:
    1. Removes collection from user_collections and associated chunks from document_chunks.
    2. Deletes all collection files from storage under documents/{user_id}/{collection_id}/.
    """
    clean_coll_id = str(collection_id).strip()
    coll = get_collection(clean_coll_id, user_id=user_id)
    if not coll:
        return False

    eff_user_id = str(user_id or coll.get("user_id")).strip()

    # 1. Database deletion
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM document_chunks WHERE collection_id = :collection_id"),
            {"collection_id": clean_coll_id}
        )
        del_sql = "DELETE FROM user_collections WHERE collection_id = :collection_id"
        params: Dict[str, Any] = {"collection_id": clean_coll_id}
        if user_id:
            del_sql += " AND user_id = :user_id"
            params["user_id"] = eff_user_id

        conn.execute(text(del_sql), params)
        conn.commit()

    # 2. Storage cleanup
    try:
        storage = get_storage()
        prefix = f"documents/{eff_user_id}/{clean_coll_id}/"
        deleted = storage.delete_prefix(prefix)
        print(f"[DocumentManager] [+] Cleaned up {deleted} storage file(s) for collection: {clean_coll_id}")
    except Exception as st_err:
        print(f"[DocumentManager] [!] Note deleting storage prefix for {clean_coll_id}: {st_err}")

    return True


def delete_document(
    document_id: str,
    collection_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> bool:
    """
    Deletes an individual document from users_documents, document_chunks,
    removes it from user_collections.documents JSONB array, and deletes it from storage.
    """
    clean_doc_id = str(document_id).strip()
    clean_coll_id = str(collection_id).strip() if collection_id else None

    # Fetch document metadata first to know filename and user_id for storage deletion
    select_doc_sql = "SELECT document_id, user_id, file_name FROM users_documents WHERE document_id = :document_id"
    params: Dict[str, Any] = {"document_id": clean_doc_id}
    if user_id:
        select_doc_sql += " AND user_id = :user_id"
        params["user_id"] = str(user_id).strip()

    with engine.connect() as conn:
        doc_row = conn.execute(text(select_doc_sql), params).mappings().first()
        if not doc_row:
            return False

        # 1. Delete from users_documents and document_chunks
        conn.execute(text("DELETE FROM users_documents WHERE document_id = :document_id"), {"document_id": clean_doc_id})
        conn.execute(text("DELETE FROM document_chunks WHERE document_id = :document_id"), {"document_id": clean_doc_id})

        # 2. Update user_collections JSONB array
        if clean_coll_id:
            update_coll_sql = """
                UPDATE user_collections
                SET documents = (
                    SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                    FROM jsonb_array_elements(documents) AS elem
                    WHERE elem->>'document_id' != :document_id
                ),
                total_files = GREATEST(0, total_files - 1),
                updated_at = CURRENT_TIMESTAMP
                WHERE collection_id = :collection_id;
            """
            conn.execute(text(update_coll_sql), {"document_id": clean_doc_id, "collection_id": clean_coll_id})
        else:
            update_all_sql = """
                UPDATE user_collections
                SET documents = (
                    SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                    FROM jsonb_array_elements(documents) AS elem
                    WHERE elem->>'document_id' != :document_id
                ),
                total_files = GREATEST(0, total_files - 1),
                updated_at = CURRENT_TIMESTAMP
                WHERE documents @> jsonb_build_array(jsonb_build_object('document_id', :document_id));
            """
            conn.execute(text(update_all_sql), {"document_id": clean_doc_id})

        conn.commit()

    # 3. Delete from storage
    try:
        storage = get_storage()
        doc_user_id = str(user_id or doc_row["user_id"]).strip()
        doc_filename = str(doc_row["file_name"]).strip()
        if clean_coll_id:
            storage_key = f"documents/{doc_user_id}/{clean_coll_id}/{doc_filename}"
        else:
            storage_key = f"documents/{doc_user_id}/{doc_filename}"
        storage.delete(storage_key)
        print(f"[DocumentManager] [+] Deleted document file from storage: {storage_key}")
    except Exception as st_err:
        print(f"[DocumentManager] [!] Note deleting storage file for {clean_doc_id}: {st_err}")

    return True
