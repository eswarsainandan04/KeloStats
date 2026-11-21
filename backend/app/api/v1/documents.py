import sys
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from app.core.auth import get_current_user_id
from app.services.documents import (
    PDFProcessor,
    create_collection,
    delete_collection,
    delete_document,
    get_collection,
    list_user_collections,
    save_document_record,
    update_collection_documents_registry,
    upsert_chunks,
)

router = APIRouter(prefix="/documents", tags=["Documents & Knowledge Pools"])


# ==============================================================================
# Pydantic Request Models
# ==============================================================================

class CreateCollectionRequest(BaseModel):
    display_name: str
    user_id: Optional[str] = None


# ==============================================================================
# Endpoints
# ==============================================================================

@router.post("/create_collection", summary="Step 1: Create a new collection pool")
async def create_collection_endpoint(
    request: Request,
    body: Optional[CreateCollectionRequest] = None,
    display_name: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Step 1 Endpoint:
    Accepts display_name and creates a new collection pool in user_collections (pool_{UUID})
    along with a storage folder placeholder.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id or (body.user_id if body else None)
    effective_display_name = (body.display_name if body else None) or display_name

    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id could not be resolved from authenticated token."
        )

    if not effective_display_name or not str(effective_display_name).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="display_name is required to create a collection pool."
        )

    try:
        collection_data = create_collection(
            user_id=effective_user_id,
            display_name=effective_display_name
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create collection: {str(e)}"
        )

    return {
        "status": "success",
        "message": f"Collection '{collection_data['display_name']}' created successfully.",
        "data": collection_data
    }


@router.post("/upload", summary="Upload and process files into a collection (Steps 1-3)")
async def document_upload(
    display_name: str = Form(...),
    file: List[UploadFile] = File(...),
    user_id: Optional[str] = Form(None),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Unified Endpoint for Steps 1 - 3:
    1. Creates collection pool record and storage folder.
    2. Uploads all files to documents/{user_id}/{collection_id}/{filename} via storage module.
    3. Runs PDF extraction, semantic chunking, embedding generation, and upserts chunks into document_chunks.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id
    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id could not be resolved from authenticated token."
        )

    clean_user_id = str(effective_user_id).strip()
    clean_display_name = str(display_name or "").strip()

    if not clean_display_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="display_name is required to create a collection pool."
        )

    # Filter valid files from upload stream
    uploaded_files: List[UploadFile] = []
    if isinstance(file, list):
        for f in file:
            if hasattr(f, "filename") and f.filename:
                uploaded_files.append(f)
    elif hasattr(file, "filename") and file.filename:
        uploaded_files.append(file)

    if not uploaded_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file(s) provided. In form-data, ensure the key is 'file' (type: File) with at least one file selected."
        )

    # Step 1: Create Collection Record & Storage Placeholder
    print("\n" + "=" * 65)
    print(f"[DocumentUpload] >>> Initiating Collection Upload (Steps 1 - 3):")
    print(f"  - User ID: {clean_user_id}")
    print(f"  - Display Name: '{clean_display_name}'")
    print(f"  - Files to process: {len(uploaded_files)}")
    print("=" * 65)

    try:
        collection_data = create_collection(
            user_id=clean_user_id,
            display_name=clean_display_name
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create collection: {str(e)}"
        )

    collection_id = collection_data["collection_id"]
    processed_documents: List[Dict[str, Any]] = []

    # Steps 2 & 3: Save file bytes, record in database, extract, chunk, embed, upsert
    for idx, f in enumerate(uploaded_files, 1):
        if not f.filename:
            continue

        print(f"\n[DocumentUpload] --- Processing File {idx}/{len(uploaded_files)}: '{f.filename}' ---")

        try:
            file_bytes = await f.read()
        except Exception as read_err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to read uploaded file '{f.filename}': {str(read_err)}"
            )

        try:
            # 2.1: Save document using storage module & record in users_documents
            doc_data = save_document_record(
                user_id=clean_user_id,
                file_name=f.filename,
                file_bytes=file_bytes,
                collection_id=collection_id,
                content_type=f.content_type
            )
            document_id = doc_data["document_id"]

            # 2.2: Update collection documents registry JSON
            update_collection_documents_registry(
                collection_id=collection_id,
                document_id=document_id,
                file_name=doc_data["file_name"]
            )

            # 3.1: Extract markdown text and chunk
            processor = PDFProcessor(file_bytes)
            text_content = processor.document_extractor()
            chunks = processor.pdf_chunker(text_content)

            # 3.2: Generate embeddings
            embedded_chunks = processor.generate_embeddings(chunks)

            # 3.3: Upsert chunks into document_chunks
            chunk_count = upsert_chunks(
                embedded_chunks=embedded_chunks,
                document_id=document_id,
                collection_id=collection_id
            )
            doc_data["chunks_count"] = chunk_count
            processed_documents.append(doc_data)
            print(f"[DocumentUpload] [+] Successfully indexed: {doc_data['file_name']} (Chunks: {chunk_count})")

        except Exception as proc_err:
            print(f"[DocumentUpload] [-] Error processing file '{f.filename}': {proc_err}", file=sys.stderr)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error processing file '{f.filename}': {str(proc_err)}"
            )

    print("\n" + "=" * 65)
    print(f"[DocumentUpload] [ALL COMPLETE] Successfully processed collection '{clean_display_name}' ({collection_id}) with {len(processed_documents)} document(s).")
    print("=" * 65 + "\n")

    storage_folder = f"documents/{clean_user_id}/{collection_id}/"

    return {
        "status": "success",
        "message": f"Successfully created collection '{clean_display_name}' and indexed {len(processed_documents)} file(s).",
        "collection_id": collection_id,
        "display_name": clean_display_name,
        "total_files": len(processed_documents),
        "documents": processed_documents,
        "s3_folder": storage_folder,
        "storage_folder": storage_folder,
    }


@router.post("/modify", summary="Add new PDF documents to an existing collection")
async def modify_collection_endpoint(
    collection_id: str = Form(...),
    file: List[UploadFile] = File(...),
    user_id: Optional[str] = Form(None),
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Appends new PDF file(s) to an existing collection pool:
    1. Saves document binary to storage under documents/{user_id}/{collection_id}/{filename}
    2. Records metadata in users_documents
    3. Updates user_collections.documents JSONB registry and increments total_files
    4. Runs PDFProcessor extraction, chunking, and embedding generation
    5. Upserts chunks into document_chunks with collection_id
    Guarded by verified JWT authentication.
    """
    clean_coll_id = str(collection_id).strip()
    if not clean_coll_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="collection_id is required.")

    effective_user_id = authenticated_user_id or user_id
    clean_user_id = str(effective_user_id).strip()

    # Verify collection exists
    coll_row = get_collection(collection_id=clean_coll_id, user_id=clean_user_id)
    if not coll_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{clean_coll_id}' not found or access denied."
        )

    # Filter uploaded files
    uploaded_files: List[UploadFile] = []
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

        try:
            # 1. Save document to storage and users_documents
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
            processor = PDFProcessor(file_bytes)
            text_content = processor.document_extractor()
            chunks = processor.pdf_chunker(text_content)

            # 4. Generate embeddings
            embedded_chunks = processor.generate_embeddings(chunks)

            # 5. Upsert chunks into document_chunks
            chunk_count = upsert_chunks(
                embedded_chunks=embedded_chunks,
                document_id=document_id,
                collection_id=clean_coll_id
            )
            doc_data["chunks_count"] = chunk_count
            added_documents.append(doc_data)
            print(f"[DocumentUpload:Modify] [+] Successfully added: {doc_data['file_name']} (Chunks: {chunk_count})")

        except Exception as proc_err:
            print(f"[DocumentUpload:Modify] [-] Error processing file '{f.filename}': {proc_err}", file=sys.stderr)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error processing file '{f.filename}': {str(proc_err)}"
            )

    print("=" * 65 + "\n")

    return {
        "status": "success",
        "message": f"Successfully added and indexed {len(added_documents)} document(s) in collection '{clean_coll_id}'.",
        "collection_id": clean_coll_id,
        "added_documents": added_documents,
        "count": len(added_documents)
    }


@router.get("/collections", summary="List all collections for the authenticated user")
async def list_collections_endpoint(
    user_id: Optional[str] = None,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Lists all knowledge collections for the authenticated user with enriched document manifests.
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id
    if not effective_user_id or not str(effective_user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id could not be resolved from authenticated token."
        )

    try:
        collections = list_user_collections(user_id=str(effective_user_id).strip())
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


@router.delete("/collections/{collection_id}", summary="Delete a collection pool")
async def delete_collection_endpoint(
    collection_id: str,
    user_id: Optional[str] = None,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Deletes a collection pool:
    - Removes records from user_collections and document_chunks
    - Deletes all associated files from storage under documents/{user_id}/{collection_id}/
    Guarded by verified JWT authentication.
    """
    effective_user_id = authenticated_user_id or user_id
    clean_coll_id = str(collection_id).strip()

    try:
        deleted = delete_collection(collection_id=clean_coll_id, user_id=effective_user_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection '{clean_coll_id}' not found or access denied."
            )

        return {
            "status": "success",
            "message": f"Collection '{clean_coll_id}' deleted successfully."
        }
    except HTTPException:
        raise
    except Exception as err:
        print(f"[DocumentUpload] Error deleting collection: {err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete collection: {str(err)}"
        )


@router.delete("/document/{document_id}", summary="Delete an individual PDF document")
async def delete_document_endpoint(
    document_id: str,
    collection_id: Optional[str] = None,
    user_id: Optional[str] = None,
    authenticated_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """
    Deletes an individual document from users_documents, cascades chunk removal,
    updates user_collections.documents JSONB array, and deletes the file from storage.
    Guarded by verified JWT authentication.
    """
    clean_doc_id = str(document_id).strip()
    clean_coll_id = str(collection_id).strip() if collection_id else None
    effective_user_id = authenticated_user_id or user_id

    try:
        deleted = delete_document(
            document_id=clean_doc_id,
            collection_id=clean_coll_id,
            user_id=effective_user_id
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{clean_doc_id}' not found or access denied."
            )

        return {
            "status": "success",
            "message": f"Document '{clean_doc_id}' deleted successfully."
        }
    except HTTPException:
        raise
    except Exception as err:
        print(f"[DocumentUpload] Error deleting document: {err}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(err)}"
        )
