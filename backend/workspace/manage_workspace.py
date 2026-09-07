import os
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import boto3
from botocore.config import Config

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
if (current_dir.parent / ".env").exists():
    load_dotenv(dotenv_path=current_dir.parent / ".env")
elif (current_dir / ".env").exists():
    load_dotenv(dotenv_path=current_dir / ".env")
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

router = APIRouter(prefix="/api/workspace", tags=["Workspace"])


class CreateWorkspacePayload(BaseModel):
    project_name: str
    user_id: str
    database_id: str
    template_id: str


def get_s3_client():
    """
    Returns an initialized S3 client for Supabase Storage.
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


def create_supabase_s3_folder(user_id: str, project_id: str) -> str:
    """
    Creates an S3 folder object in Supabase S3 bucket:
    workspace/{user_id}/{project_id}/
    """
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    folder_key = f"workspace/{user_id}/{project_id}/"

    s3_client = get_s3_client()
    if not s3_client:
        print("[!] Supabase S3 credentials not fully configured; skipping S3 folder creation.")
        return folder_key

    try:
        # In S3, a folder is represented as a zero-byte object ending in '/'
        s3_client.put_object(
            Bucket=bucket_name,
            Key=folder_key,
            Body=b""
        )
        print(f"[+] Successfully created Supabase S3 folder: {folder_key} in bucket '{bucket_name}'")
    except Exception as exc:
        print(f"[-] Supabase S3 folder creation error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database record prepared, but Supabase S3 folder creation failed: {str(exc)}"
        )

    return folder_key


def copy_supabase_template_files(template_id: str, user_id: str, project_id: str) -> List[str]:
    """
    Copies all files and folders in Supabase S3 from:
      templates/{template_id}/
    to:
      workspace/{user_id}/{project_id}/
    """
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()

    if not s3_client:
        print("[!] Supabase S3 client not available; skipping template copy.")
        return []

    src_prefix = f"templates/{template_id}/"
    dest_prefix = f"workspace/{user_id}/{project_id}/"

    copied_keys: List[str] = []
    continuation_token = None

    try:
        while True:
            list_kwargs = {
                "Bucket": bucket_name,
                "Prefix": src_prefix,
            }
            if continuation_token:
                list_kwargs["ContinuationToken"] = continuation_token

            resp = s3_client.list_objects_v2(**list_kwargs)
            contents = resp.get("Contents", [])

            for item in contents:
                src_key = item["Key"]
                rel_path = src_key[len(src_prefix):]
                if not rel_path:
                    continue

                dest_key = f"{dest_prefix}{rel_path}"

                s3_client.copy_object(
                    Bucket=bucket_name,
                    CopySource=f"{bucket_name}/{src_key}",
                    Key=dest_key
                )
                copied_keys.append(dest_key)
                print(f"[+] Copied template file: {src_key} -> {dest_key}")

            if resp.get("IsTruncated"):
                continuation_token = resp.get("NextContinuationToken")
            else:
                break

    except Exception as exc:
        print(f"[-] Error copying template files from S3: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Folder created, but copying template files failed: {str(exc)}"
        )

    return copied_keys


@router.post("/create", summary="Create workspace project in DB, create S3 folder, and copy template files")
def create_workspace_session(payload: CreateWorkspacePayload):
    """
    1. Inserts project into workspace table:
       workspace(project_id VARCHAR pk, project_name, user_id, database_id, template_id, created_at, updated_at)

    2. Generates project_id as project_{UUID}

    3. Creates Supabase S3 folder:
       workspace/{user_id}/{project_id}/

    4. Copies all files and folders from:
       templates/{template_id}/
       to:
       workspace/{user_id}/{project_id}/
    """
    if not payload.project_name or not payload.project_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project name is required."
        )

    if not payload.user_id or not payload.database_id or not payload.template_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: user_id, database_id, or template_id."
        )

    # Generate project_id as project_{UUID}
    project_id = f"project_{uuid.uuid4()}"
    project_name = payload.project_name.strip()

    try:
        # 1. Insert into PostgreSQL workspace table
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO workspace (project_id, project_name, user_id, database_id, template_id, created_at, updated_at)
                    VALUES (:project_id, :project_name, :user_id, :database_id, :template_id, NOW(), NOW());
                """),
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "user_id": payload.user_id,
                    "database_id": payload.database_id,
                    "template_id": payload.template_id,
                }
            )
            conn.commit()

        # 2. Create S3 folder in Supabase bucket: workspace/{user_id}/{project_id}/
        s3_folder = create_supabase_s3_folder(user_id=payload.user_id, project_id=project_id)

        # 3. Copy all files and folders from templates/{template_id}/ to workspace/{user_id}/{project_id}/
        copied_files = copy_supabase_template_files(
            template_id=payload.template_id,
            user_id=payload.user_id,
            project_id=project_id
        )

        # 4. Initialize manifest.json and convert copied template slides to UUIDs
        try:
            from workspace.manifest import load_manifest
            manifest_items = load_manifest(user_id=payload.user_id, project_id=project_id)
            print(f"[+] Initialized manifest.json with {len(manifest_items)} slides for workspace {project_id}")
        except Exception as m_init_err:
            print(f"[!] Notice initializing manifest for workspace {project_id}: {m_init_err}")

        return {
            "status": "success",
            "message": "Workspace created and template files copied successfully",
            "project_id": project_id,
            "project_name": project_name,
            "user_id": payload.user_id,
            "database_id": payload.database_id,
            "template_id": payload.template_id,
            "s3_folder": s3_folder,
            "copied_files_count": len(copied_files),
            "copied_files": copied_files
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workspace project: {str(exc)}"
        )


def fetch_workspace_history_from_s3(user_id: str) -> List[Dict[str, Any]]:
    """
    Scans Supabase S3 bucket under:
      workspace/{user_id}/
    lists all project folders, counts slides, and checks files.
    """
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()
    prefix = f"workspace/{user_id}/"

    s3_projects: Dict[str, Dict[str, Any]] = {}

    if s3_client:
        try:
            continuation_token = None
            while True:
                list_kwargs = {
                    "Bucket": bucket_name,
                    "Prefix": prefix,
                    "Delimiter": "/",
                }
                if continuation_token:
                    list_kwargs["ContinuationToken"] = continuation_token

                resp = s3_client.list_objects_v2(**list_kwargs)
                for common_prefix in resp.get("CommonPrefixes", []):
                    p_prefix = common_prefix.get("Prefix", "")
                    parts = [p for p in p_prefix.split("/") if p]
                    if len(parts) >= 2:
                        pid = parts[-1]
                        if pid not in s3_projects:
                            s3_projects[pid] = {
                                "project_id": pid,
                                "s3_folder": p_prefix,
                                "slide_count": 0,
                                "has_pptx": False,
                                "last_modified": None,
                            }

                if resp.get("IsTruncated"):
                    continuation_token = resp.get("NextContinuationToken")
                else:
                    break

            # Count slides and check pptx for each project found in S3
            for pid, pdata in s3_projects.items():
                # Check manifest.json first for instant, accurate slide count
                manifest_key = f"workspace/{user_id}/{pid}/manifest.json"
                try:
                    m_resp = s3_client.get_object(Bucket=bucket_name, Key=manifest_key)
                    m_data = json.loads(m_resp["Body"].read().decode("utf-8"))
                    m_items = m_data if isinstance(m_data, list) else m_data.get("slides", [])
                    pdata["slide_count"] = len(m_items)
                except Exception:
                    # Fallback to listing .html slide files
                    slides_prefix = f"workspace/{user_id}/{pid}/slides/"
                    try:
                        slide_resp = s3_client.list_objects_v2(
                            Bucket=bucket_name,
                            Prefix=slides_prefix,
                            MaxKeys=100
                        )
                        slide_items = [
                            item for item in slide_resp.get("Contents", [])
                            if item["Key"].endswith(".html") and not item["Key"].endswith("/")
                        ]
                        pdata["slide_count"] = len(slide_items)
                    except Exception as s_err:
                        print(f"[-] Error listing slides for {pid}: {s_err}")

                # Check if presentation.pptx exists
                try:
                    pptx_key = f"workspace/{user_id}/{pid}/presentation.pptx"
                    s3_client.head_object(Bucket=bucket_name, Key=pptx_key)
                    pdata["has_pptx"] = True
                except Exception:
                    pdata["has_pptx"] = False

        except Exception as exc:
            print(f"[-] Error scanning S3 for workspace history: {exc}")

    return list(s3_projects.values())


@router.get("/list", summary="Fetch all workspace projects for a user from Supabase S3 bucket and DB")
@router.get("/history", summary="Fetch all workspace projects for a user from Supabase S3 bucket and DB")
def list_workspaces(user_id: str = Query(..., description="User ID / UUID")):
    """
    1. Fetches all projects from Supabase S3 bucket under: workspace/{user_id}/
    2. Counts slides and checks presentation files in S3.
    3. Queries PostgreSQL workspace table to enrich with project_name, database info, and template info.
    4. Merges and returns the list sorted by most recent activity.
    """
    if not user_id or not user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id query parameter is required."
        )

    clean_user_id = user_id.strip()

    # 1. Fetch S3 projects
    s3_projects = fetch_workspace_history_from_s3(clean_user_id)
    s3_map = {p["project_id"]: p for p in s3_projects}

    # 2. Query PostgreSQL workspace table
    db_map = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT 
                        w.project_id, 
                        w.project_name, 
                        CAST(w.user_id AS TEXT) as user_id, 
                        w.database_id, 
                        w.template_id, 
                        w.created_at, 
                        w.updated_at,
                        d.database_name, 
                        d.database_type,
                        d.display_name as database_display_name,
                        t.template_name,
                        t.category as template_category
                    FROM workspace w
                    LEFT JOIN user_databases d ON w.database_id = d.db_id
                    LEFT JOIN templates t ON w.template_id = t.template_id
                    WHERE CAST(w.user_id AS TEXT) = :user_id
                    ORDER BY w.updated_at DESC
                """),
                {"user_id": clean_user_id}
            ).fetchall()

            for r in rows:
                db_map[r.project_id] = dict(r._mapping)
    except Exception as exc:
        print(f"[-] Error fetching DB workspace records for {clean_user_id}: {exc}")

    # 3. Merge S3 projects and DB projects
    all_project_ids = list(dict.fromkeys(list(s3_map.keys()) + list(db_map.keys())))
    merged_workspaces = []

    for pid in all_project_ids:
        s3_info = s3_map.get(pid, {})
        db_info = db_map.get(pid, {})

        created_at = db_info.get("created_at")
        updated_at = db_info.get("updated_at")

        # Human-friendly default project name if not stored in DB
        default_name = pid.replace("project_", "Project ").replace("_", " ").title()
        project_name = db_info.get("project_name") or default_name

        merged_workspaces.append({
            "project_id": pid,
            "project_name": project_name,
            "user_id": clean_user_id,
            "database_id": db_info.get("database_id"),
            "database_name": db_info.get("database_name"),
            "database_display_name": db_info.get("database_display_name") or db_info.get("database_name"),
            "database_type": db_info.get("database_type"),
            "template_id": db_info.get("template_id"),
            "template_name": db_info.get("template_name"),
            "template_category": db_info.get("template_category"),
            "slide_count": s3_info.get("slide_count", 0),
            "has_pptx": s3_info.get("has_pptx", False),
            "s3_folder": s3_info.get("s3_folder", f"workspace/{clean_user_id}/{pid}/"),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        })

    # Sort newest first
    merged_workspaces.sort(
        key=lambda w: w.get("updated_at") or w.get("created_at") or "",
        reverse=True
    )

    return {
        "status": "success",
        "user_id": clean_user_id,
        "total_workspaces": len(merged_workspaces),
        "workspaces": merged_workspaces
    }


def delete_supabase_s3_workspace_folder(user_id: str, project_id: str) -> int:
    """
    Deletes all files and objects under:
      workspace/{user_id}/{project_id}/
    in Supabase S3 storage bucket.
    """
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()
    if not s3_client or not user_id or not project_id:
        return 0

    prefix = f"workspace/{user_id}/{project_id}/"
    deleted_count = 0

    try:
        continuation_token = None
        while True:
            list_kwargs = {
                "Bucket": bucket_name,
                "Prefix": prefix
            }
            if continuation_token:
                list_kwargs["ContinuationToken"] = continuation_token

            resp = s3_client.list_objects_v2(**list_kwargs)
            contents = resp.get("Contents", [])

            if contents:
                for obj in contents:
                    key = obj.get("Key")
                    if not key:
                        continue
                    try:
                        s3_client.delete_object(Bucket=bucket_name, Key=key)
                        deleted_count += 1
                        print(f"[+] [Delete S3] Deleted object: {key}")
                    except Exception as del_err:
                        print(f"[-] [Delete S3] Error deleting {key}: {del_err}")

            if resp.get("IsTruncated"):
                continuation_token = resp.get("NextContinuationToken")
            else:
                break

        # Also delete marker if existing without trailing slash
        try:
            s3_client.delete_object(Bucket=bucket_name, Key=f"workspace/{user_id}/{project_id}")
        except Exception:
            pass

    except Exception as exc:
        print(f"[-] [Delete S3 Error] Failed to delete S3 folder {prefix}: {exc}")

    print(f"[+] [Delete S3] Finished deleting {deleted_count} S3 objects under {prefix}")
    return deleted_count


class DeleteWorkspacePayload(BaseModel):
    project_id: Optional[str] = None
    user_id: Optional[str] = None


@router.delete("/delete")
@router.post("/delete")
def delete_workspace(
    payload: Optional[DeleteWorkspacePayload] = None,
    project_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """
    Deletes a project workspace:
    1. Removes all S3 files under workspace/{user_id}/{project_id}/
    2. Deletes dependent records from chat_messages table where project_id = :project_id
    3. Deletes workspace record from workspace table where project_id = :project_id
    """
    target_project_id = (payload.project_id if payload and payload.project_id else project_id or "").strip()
    target_user_id = (payload.user_id if payload and payload.user_id else user_id or "").strip()

    if not target_project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id is required."
        )

    # 1. Look up user_id from DB if not provided
    if not target_user_id:
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT CAST(user_id AS TEXT) as user_id FROM workspace WHERE project_id = :pid LIMIT 1;"),
                    {"pid": target_project_id}
                ).fetchone()
                if row:
                    target_user_id = row.user_id
        except Exception as err:
            print(f"[-] [Delete Workspace] Error resolving user_id for project '{target_project_id}': {err}")

    # 2. Delete all S3 files under workspace/{user_id}/{project_id}/
    s3_deleted_count = 0
    if target_user_id:
        s3_deleted_count = delete_supabase_s3_workspace_folder(
            user_id=target_user_id,
            project_id=target_project_id
        )

    # 3. Delete from database tables (chat_messages and workspace)
    db_deleted = False
    try:
        with engine.begin() as conn:
            # Delete dependent chat messages first
            conn.execute(
                text("DELETE FROM chat_messages WHERE project_id = :pid;"),
                {"pid": target_project_id}
            )
            # Delete from workspace table
            res = conn.execute(
                text("DELETE FROM workspace WHERE project_id = :pid;"),
                {"pid": target_project_id}
            )
            db_deleted = (res.rowcount or 0) > 0
            print(f"[+] [Delete DB] Successfully deleted project '{target_project_id}' from workspace table (rows: {res.rowcount})")
    except Exception as exc:
        print(f"[-] [Delete DB Error] Failed to delete project '{target_project_id}' from database: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete project from database: {str(exc)}"
        )

    return {
        "status": "success",
        "message": f"Project '{target_project_id}' deleted successfully from database and S3.",
        "project_id": target_project_id,
        "user_id": target_user_id,
        "s3_objects_deleted": s3_deleted_count,
        "db_record_deleted": db_deleted
    }


@router.delete("/{project_id}")
def delete_workspace_by_path(
    project_id: str,
    user_id: Optional[str] = Query(None)
):
    """Convenience DELETE endpoint allowing /api/workspace/{project_id}."""
    return delete_workspace(payload=None, project_id=project_id, user_id=user_id)

