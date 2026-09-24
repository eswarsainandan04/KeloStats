import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, Union, List

from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import boto3
from botocore.config import Config

# Ensure backend root and documents directory are in sys.path
documents_dir = Path(__file__).resolve().parent
backend_dir = documents_dir.parent
for p in (str(backend_dir), str(documents_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from documents.document_processor import PDFProcessor
except ModuleNotFoundError:
    from document_processor import PDFProcessor

# Load environment variables
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

router = APIRouter(prefix="/api/documents", tags=["Documents"])


# ==============================================================================
# Supabase S3 Client Initialization & Folder Management
# ==============================================================================

def get_s3_client():
    """
    Returns an initialized boto3 S3 client configured for Supabase Storage.
    """
    endpoint = os.getenv("SUPABASE_S3_ENDPOINT")
    access_key = os.getenv("SUPABASE_S3_ACCESS_KEY_ID")
    secret_key = os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY")
    region = os.getenv("SUPABASE_S3_REGION") or "us-east-1"

    if not endpoint or not access_key or not secret_key:
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4")
    )


def create_s3_collection_folder(user_id: str, collection_id: str) -> str:
    """
    Creates an S3 folder placeholder in Supabase S3:
    documents/{user_id}/{collection_id}/
    """
    clean_user_id = str(user_id).strip()
    clean_collection_id = str(collection_id).strip()
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    folder_key = f"documents/{clean_user_id}/{clean_collection_id}/"

    s3_client = get_s3_client()
    if s3_client:
        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=folder_key,
                Body=b""
            )
            print(f"[DocumentUpload] [+] Created S3 collection folder: {bucket_name}/{folder_key}")
        except Exception as err:
            print(f"[DocumentUpload] [!] S3 folder creation note: {err}")
    return folder_key


# ==============================================================================
# Step 1: Create User Collection Logic
# ==============================================================================

def create_collection(user_id: str, display_name: str) -> Dict[str, Any]:
    """
    Step 1:
    - Generates collection_id as pool_{UUID}
    - Inserts record into user_collections (display_name, documents=[], total_files=0)
    - Creates S3 folder documents/{user_id}/{collection_id}/
    """
    clean_user_id = str(user_id).strip()
    clean_name = str(display_name or "").strip()

    if not clean_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required to create a collection."
        )

    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="display_name is required to create a collection."
        )

    # Generate collection_id formatted as pool_{UUID}
    collection_id = f"pool_{uuid.uuid4()}"

    # 1. Create S3 folder placeholder
    folder_key = create_s3_collection_folder(user_id=clean_user_id, collection_id=collection_id)

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
        print(f"[DocumentUpload] Creating user_collections record '{collection_id}' ('{clean_name}') for user '{clean_user_id}'...")
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
            print(f"[DocumentUpload] [+] Successfully created collection: {collection_id}")
    except Exception as db_err:
        print(f"[DocumentUpload] [-] Database error creating user_collections: {db_err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create collection in database: {str(db_err)}"
        )

    return {
        "collection_id": collection_id,
        "user_id": clean_user_id,
        "display_name": clean_name,
        "total_files": 0,
        "documents": [],
        "s3_folder": folder_key,
    }


def update_collection_documents_registry(
    collection_id: str,
    document_id: str,
    file_name: str
) -> None:
    """
    Step 2.2:
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
            print(f"[DocumentUpload] [+] Updated user_collections ({clean_collection_id}) registry with: {document_id} ({file_name})")
    except Exception as err:
        print(f"[DocumentUpload] [-] Failed to update collection documents registry: {err}", file=sys.stderr)


# ==============================================================================
# Document Storage & Upsert Logic
# ==============================================================================

def save_document_record(
    user_id: str,
    file_name: str,
    file_bytes: bytes,
    collection_id: Optional[str] = None,
    file_type: Optional[str] = None,
    content_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extracts metadata from file bytes, inserts record into users_documents,
    and uploads to Supabase S3 under:
      - If collection_id: documents/{user_id}/{collection_id}/{file_name}
      - Otherwise:        documents/{user_id}/{file_name}
    """
    clean_user_id = str(user_id).strip()
    clean_file_name = Path(file_name).name
    file_size = len(file_bytes)

    # Determine file type
    ext = Path(clean_file_name).suffix.lstrip(".").lower()
    inferred_type = file_type or ext or "pdf"

    print(f"[DocumentUpload] Processing upload for file: '{clean_file_name}' ({file_size / 1024:.2f} KB, user_id: {clean_user_id})")

    # Extract total page count if PDF
    total_pages = 0
    if inferred_type == "pdf" or (content_type and "pdf" in content_type):
        try:
            import pymupdf
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
            total_pages = len(doc)
            doc.close()
        except Exception as e:
            print(f"[DocumentUpload] [!] Warning extracting PDF pages: {e}")
            total_pages = 1
    else:
        total_pages = 1

    # Generate document_id as doc_{UUID}
    document_id = f"doc_{uuid.uuid4()}"
    print(f"[DocumentUpload] Generated Document ID: {document_id} (Total pages: {total_pages})")

    # Determine S3 destination key
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    if collection_id:
        s3_key = f"documents/{clean_user_id}/{str(collection_id).strip()}/{clean_file_name}"
    else:
        s3_key = f"documents/{clean_user_id}/{clean_file_name}"

    s3_client = get_s3_client()
    if s3_client:
        try:
            print(f"[DocumentUpload] Uploading to Supabase S3 ({bucket_name}/{s3_key})...")
            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=file_bytes,
                ContentType=content_type or ("application/pdf" if inferred_type == "pdf" else "application/octet-stream")
            )
            print(f"[DocumentUpload] [+] Successfully uploaded to Supabase S3: {bucket_name}/{s3_key}")
        except Exception as s3_err:
            print(f"[DocumentUpload] [-] Supabase S3 upload error: {s3_err}", file=sys.stderr)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload document to Supabase storage: {str(s3_err)}"
            )
    else:
        print(f"[DocumentUpload] [!] Supabase S3 client not configured; skipped storage push for {s3_key}")

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
        print(f"[DocumentUpload] Inserting metadata into 'users_documents' table (document_id: {document_id})...")
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
            print(f"[DocumentUpload] [+] Document record inserted into users_documents: {document_id}")
    except Exception as db_err:
        print(f"[DocumentUpload] [-] Database insert error: {db_err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record document in database: {str(db_err)}"
        )

    return {
        "document_id": document_id,
        "user_id": clean_user_id,
        "collection_id": collection_id,
        "file_name": clean_file_name,
        "file_type": inferred_type,
        "file_size": file_size,
        "total_pages": total_pages,
        "s3_path": s3_key,
    }


def upsert_chunks(
    embedded_chunks: List[Dict[str, Any]],
    document_id: str,
    collection_id: Optional[str] = None
) -> int:
    """
    Step 3:
    Inserts each chunk JSON into the document_chunks table:
      chunk_id: UUID
      collection_id: pool_UUID (or null if standalone)
      document_id: doc_UUID
      chunk_index: int
      context: text
      embedding: vector
    """
    if not embedded_chunks:
        print(f"[DocumentUpload] [!] No chunks provided to upsert for document_id: {document_id}")
        return 0

    print(f"[DocumentUpload] Starting upsert of {len(embedded_chunks)} chunk(s) into 'document_chunks' table (collection_id: {collection_id}, document_id: {document_id})...")

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
        print(f"[DocumentUpload] [+] Successfully inserted {len(records)} chunks for document: {document_id} (collection_id: {clean_coll_id})")
        return len(records)
    except Exception as db_err:
        print(f"[DocumentUpload] [-] Database insert error into document_chunks: {db_err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record document chunks in database: {str(db_err)}"
        )


# ==============================================================================
# Pydantic Request Models & FastAPI Endpoints
# ==============================================================================

class CreateCollectionRequest(BaseModel):
    user_id: Optional[str] = None
    display_name: str


@router.post("/create_collection", summary="Step 1: Create a new collection pool")
async def create_collection_endpoint(
    user_id: Optional[str] = Form(None),
    display_name: Optional[str] = Form(None),
    body: Optional[CreateCollectionRequest] = None,
    request: Request = None,
) -> Dict[str, Any]:
    """
    Step 1 Endpoint:
    Accepts user_id and display_name.
    Creates a new collection record in user_collections (pool_{UUID})
    and creates the S3 folder documents/{user_id}/{collection_id}/.
    """
    # Resolve user_id from form, json body, auth middleware, or query parameters
    effective_user_id = user_id or (body.user_id if body else None)
    if not effective_user_id and request:
        effective_user_id = getattr(request.state, "user_id", None)
        if not effective_user_id:
            effective_user_id = request.headers.get("x-user-id") or request.query_params.get("user_id")

    effective_display_name = display_name or (body.display_name if body else None)

    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required to create a collection."
        )

    if not effective_display_name or not str(effective_display_name).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="display_name is required to create a collection."
        )

    collection_data = create_collection(
        user_id=effective_user_id,
        display_name=effective_display_name
    )

    return {
        "status": "success",
        "message": f"Collection '{collection_data['display_name']}' created successfully.",
        "data": collection_data
    }


@router.post("/upload", summary="Upload and process files into a collection (Steps 1-3)")
async def document_upload(
    user_id: Optional[str] = Form(None),
    display_name: str = Form(...),
    file: List[UploadFile] = File(...),
    request: Request = None,
) -> Dict[str, Any]:
    """
    Unified Endpoint for Steps 1 - 3:
    1. Generates collection_id (pool_{UUID}) internally, creates S3 folder and user_collections record.
    2. Uploads all files to documents/{user_id}/{collection_id}/{filename} and updates documents JSON registry.
    3. Runs extraction, semantic chunking, embedding generation, and upserts chunks with collection_id.
    """
    # Resolve user_id from form, request state (auth middleware), headers, or query parameters
    effective_user_id = user_id
    if not effective_user_id and request:
        effective_user_id = getattr(request.state, "user_id", None)
        if not effective_user_id:
            effective_user_id = request.headers.get("x-user-id") or request.query_params.get("user_id")

    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required to upload documents."
        )

    clean_user_id = str(effective_user_id).strip()
    clean_display_name = str(display_name or "").strip()

    if not clean_display_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="display_name is required to create a collection pool."
        )

    # Filter valid files from the 'file' parameter (supports 1 or multiple files)
    uploaded_files = []
    if isinstance(file, list):
        for f in file:
            if hasattr(f, "filename") and f.filename:
                uploaded_files.append(f)
    elif hasattr(file, "filename") and file.filename:
        uploaded_files.append(file)

    if not uploaded_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file(s) provided. In Postman, ensure the form key is 'file' (type: File) and file(s) are selected."
        )

    # =========================================================================
    # Step 1: Create Collection Record & S3 Folder
    # =========================================================================
    print("\n" + "=" * 65)
    print(f"[DocumentUpload] >>> Initiating Collection Upload (Steps 1 - 3):")
    print(f"  - User ID: {clean_user_id}")
    print(f"  - Display Name: '{clean_display_name}'")
    print(f"  - Files to process: {len(uploaded_files)}")
    print("=" * 65)

    collection_data = create_collection(
        user_id=clean_user_id,
        display_name=clean_display_name
    )
    collection_id = collection_data["collection_id"]
    print(f"[DocumentUpload] [+] Step 1 Complete: Created collection_id: {collection_id}")

    processed_documents: List[Dict[str, Any]] = []

    # =========================================================================
    # Steps 2 & 3: Upload files and process extraction, chunking, embeddings
    # =========================================================================
    for idx, f in enumerate(uploaded_files, 1):
        if not f.filename:
            continue

        print(f"\n[DocumentUpload] --- Processing File {idx}/{len(uploaded_files)}: '{f.filename}' ---")

        # Read file bytes
        try:
            file_bytes = await f.read()
            print(f"[DocumentUpload] Read {len(file_bytes)} bytes ({len(file_bytes) / 1024:.2f} KB) from upload stream.")
        except Exception as read_err:
            print(f"[DocumentUpload] [-] Read error on '{f.filename}': {read_err}", file=sys.stderr)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to read uploaded file '{f.filename}': {str(read_err)}"
            )

        # Step 2.1: Save document in S3 under documents/{user_id}/{collection_id}/{filename} & record in users_documents
        print(f"[DocumentUpload] Step 2.1: Uploading to S3 and recording in users_documents...")
        doc_data = save_document_record(
            user_id=clean_user_id,
            file_name=f.filename,
            file_bytes=file_bytes,
            collection_id=collection_id,
            content_type=f.content_type
        )
        document_id = doc_data["document_id"]

        # Step 2.2: Update user_collections documents JSON registry one by one
        print(f"[DocumentUpload] Step 2.2: Appending '{document_id}' to user_collections documents registry...")
        update_collection_documents_registry(
            collection_id=collection_id,
            document_id=document_id,
            file_name=doc_data["file_name"]
        )

        # Step 3.1: Extract markdown text and chunk
        print(f"[DocumentUpload] Step 3.1: Running PDFProcessor extraction & chunking for '{f.filename}'...")
        ob = PDFProcessor(file_bytes)
        text_content = ob.document_extractor()
        chunks = ob.pdf_chunker(text_content)

        # Step 3.2: Generate embeddings
        print(f"[DocumentUpload] Step 3.2: Generating vector embeddings for {len(chunks)} chunk(s)...")
        embedded_chunks = ob.generate_embeddings(chunks)

        # Step 3.3: Upsert chunks into document_chunks tagged with collection_id
        print(f"[DocumentUpload] Step 3.3: Upserting chunks into document_chunks with collection_id: '{collection_id}'...")
        chunk_count = upsert_chunks(
            embedded_chunks=embedded_chunks,
            document_id=document_id,
            collection_id=collection_id
        )
        doc_data["chunks_count"] = chunk_count

        processed_documents.append(doc_data)
        print(f"[DocumentUpload] [+] Successfully completed: {doc_data['file_name']} (Chunks: {chunk_count})")

    print("\n" + "=" * 65)
    print(f"[DocumentUpload] [ALL COMPLETE] Successfully processed collection '{clean_display_name}' ({collection_id}) with {len(processed_documents)} document(s).")
    print("=" * 65 + "\n")

    return {
        "status": "success",
        "message": f"Successfully created collection '{clean_display_name}' and indexed {len(processed_documents)} file(s).",
        "collection_id": collection_id,
        "display_name": clean_display_name,
        "total_files": len(processed_documents),
        "documents": processed_documents,
        "s3_folder": f"documents/{clean_user_id}/{collection_id}/"
    }


@router.post("/modify", summary="Add new PDF documents to an existing collection")
async def modify_collection_endpoint(
    collection_id: str = Form(...),
    user_id: Optional[str] = Form(None),
    file: List[UploadFile] = File(...),
    request: Request = None,
) -> Dict[str, Any]:
    """
    Appends new PDF file(s) to an existing collection:
    1. Saves document binary to S3 under documents/{user_id}/{collection_id}/{filename}
    2. Records metadata in users_documents table
    3. Updates user_collections.documents JSONB registry and increments total_files
    4. Runs PDFProcessor extraction, chunking, and embedding generation
    5. Upserts chunks into document_chunks with collection_id
    """
    clean_coll_id = str(collection_id).strip()
    if not clean_coll_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="collection_id is required.")

    # Verify collection exists and retrieve its user_id
    select_sql = "SELECT collection_id, user_id, display_name FROM user_collections WHERE collection_id = :collection_id;"
    try:
        with engine.connect() as conn:
            coll_row = conn.execute(text(select_sql), {"collection_id": clean_coll_id}).mappings().first()
            if not coll_row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Collection '{clean_coll_id}' not found.")
    except HTTPException:
        raise
    except Exception as db_err:
        raise HTTPException(status_code=500, detail=f"Database error verifying collection: {str(db_err)}")

    # Resolve user_id
    effective_user_id = user_id or str(coll_row["user_id"])
    if not effective_user_id and request:
        effective_user_id = getattr(request.state, "user_id", None) or request.headers.get("x-user-id")
    clean_user_id = str(effective_user_id).strip()

    # Filter uploaded files
    uploaded_files = []
    if isinstance(file, list):
        for f in file:
            if hasattr(f, "filename") and f.filename:
                uploaded_files.append(f)
    elif hasattr(file, "filename") and file.filename:
        uploaded_files.append(file)

    if not uploaded_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No PDF file(s) provided. In form-data, use key 'file' with file(s) selected."
        )

    print("\n" + "=" * 65)
    print(f"[DocumentUpload:Modify] Adding {len(uploaded_files)} file(s) to Collection '{clean_coll_id}' (User: {clean_user_id})")
    print("=" * 65)

    added_documents: List[Dict[str, Any]] = []

    for idx, f in enumerate(uploaded_files, 1):
        if not f.filename:
            continue

        print(f"\n[DocumentUpload:Modify] Processing File {idx}/{len(uploaded_files)}: '{f.filename}'")

        try:
            file_bytes = await f.read()
        except Exception as read_err:
            raise HTTPException(status_code=400, detail=f"Failed to read file '{f.filename}': {str(read_err)}")

        # 1. Save document to S3 and users_documents
        doc_data = save_document_record(
            user_id=clean_user_id,
            file_name=f.filename,
            file_bytes=file_bytes,
            collection_id=clean_coll_id,
            content_type=f.content_type
        )
        document_id = doc_data["document_id"]

        # 2. Update user_collections documents JSON registry
        update_collection_documents_registry(
            collection_id=clean_coll_id,
            document_id=document_id,
            file_name=doc_data["file_name"]
        )

        # 3. Extract text and chunk
        ob = PDFProcessor(file_bytes)
        text_content = ob.document_extractor()
        chunks = ob.pdf_chunker(text_content)

        # 4. Generate embeddings
        embedded_chunks = ob.generate_embeddings(chunks)

        # 5. Upsert chunks into document_chunks
        chunk_count = upsert_chunks(
            embedded_chunks=embedded_chunks,
            document_id=document_id,
            collection_id=clean_coll_id
        )
        doc_data["chunks_count"] = chunk_count
        added_documents.append(doc_data)
        print(f"[DocumentUpload:Modify] [+] Successfully added: {doc_data['file_name']} (Chunks: {chunk_count})")

    print("=" * 65 + "\n")

    return {
        "status": "success",
        "message": f"Successfully added and indexed {len(added_documents)} document(s) in collection '{clean_coll_id}'.",
        "collection_id": clean_coll_id,
        "added_documents": added_documents,
        "count": len(added_documents)
    }



@router.get("/collections", summary="List all collections for a user")
async def list_collections_endpoint(
    user_id: Optional[str] = None,
    request: Request = None,
) -> Dict[str, Any]:
    """
    Lists all collections for the user with enriched document manifests.
    """
    effective_user_id = user_id
    if not effective_user_id and request:
        effective_user_id = getattr(request.state, "user_id", None)
        if not effective_user_id:
            effective_user_id = request.headers.get("x-user-id") or request.query_params.get("user_id")

    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required to fetch collections."
        )

    clean_user_id = str(effective_user_id).strip()

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

    try:
        with engine.connect() as conn:
            coll_rows = conn.execute(text(select_coll_sql), {"user_id": clean_user_id}).mappings().all()
            doc_rows = conn.execute(text(doc_info_sql), {"user_id": clean_user_id}).mappings().all()

        # Build document lookup map
        doc_map = {}
        for dr in doc_rows:
            doc_map[dr["document_id"]] = {
                "document_id": dr["document_id"],
                "file_name": dr["file_name"],
                "file_type": dr["file_type"] or "pdf",
                "file_size": dr["file_size"],
                "total_pages": dr["total_pages"],
                "created_at": dr["created_at"].isoformat() if dr["created_at"] else None,
            }

        collections = []
        for r in coll_rows:
            raw_docs = r["documents"] if r["documents"] is not None else []
            enriched_docs = []
            for d in raw_docs:
                did = d.get("document_id") if isinstance(d, dict) else str(d)
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
                "collection_id": r["collection_id"],
                "user_id": str(r["user_id"]),
                "display_name": r["display_name"],
                "documents": enriched_docs,
                "total_files": len(enriched_docs) if enriched_docs else (r["total_files"] or 0),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            })

        return {
            "status": "success",
            "collections": collections,
            "count": len(collections)
        }
    except Exception as db_err:
        print(f"[DocumentUpload] Error listing collections: {db_err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error listing collections: {str(db_err)}"
        )


@router.delete("/collections/{collection_id}", summary="Delete a collection")
async def delete_collection_endpoint(
    collection_id: str,
    user_id: Optional[str] = None,
    request: Request = None,
) -> Dict[str, Any]:
    """
    Deletes a collection and cascades to its chunks.
    """
    effective_user_id = user_id
    if not effective_user_id and request:
        effective_user_id = getattr(request.state, "user_id", None)
        if not effective_user_id:
            effective_user_id = request.headers.get("x-user-id") or request.query_params.get("user_id")

    clean_coll_id = str(collection_id).strip()
    delete_sql = "DELETE FROM user_collections WHERE collection_id = :collection_id"
    params = {"collection_id": clean_coll_id}
    if effective_user_id:
        delete_sql += " AND user_id = :user_id"
        params["user_id"] = str(effective_user_id).strip()

    try:
        with engine.connect() as conn:
            res = conn.execute(text(delete_sql), params)
            conn.commit()
            if res.rowcount == 0:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

        return {
            "status": "success",
            "message": f"Collection '{clean_coll_id}' deleted successfully."
        }
    except HTTPException:
        raise
    except Exception as db_err:
        print(f"[DocumentUpload] Error deleting collection: {db_err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete collection: {str(db_err)}"
        )


@router.delete("/document/{document_id}", summary="Delete an individual PDF document")
async def delete_document_endpoint(
    document_id: str,
    collection_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Deletes an individual document from users_documents (cascades to document_chunks)
    and removes it from user_collections.documents JSONB array.
    """
    clean_doc_id = str(document_id).strip()
    clean_coll_id = str(collection_id).strip() if collection_id else None

    try:
        with engine.connect() as conn:
            # 1. Delete from users_documents (cascades to document_chunks)
            del_doc_sql = "DELETE FROM users_documents WHERE document_id = :document_id"
            conn.execute(text(del_doc_sql), {"document_id": clean_doc_id})

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

        return {
            "status": "success",
            "message": f"Document '{clean_doc_id}' deleted successfully."
        }
    except Exception as db_err:
        print(f"[DocumentUpload] Error deleting document: {db_err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(db_err)}"
        )



