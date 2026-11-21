import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text

from app.core.config import settings
from app.core.storage import get_storage
from app.services.connectors import app_db_engine as engine


# ==============================================================================
# Storage Operations (Using Unified Storage Adapter)
# ==============================================================================

def create_workspace_folder(user_id: str, project_id: str) -> str:
    """
    Creates a storage folder placeholder for the workspace:
    workspace/{user_id}/{project_id}/.keep
    """
    clean_user_id = str(user_id or "").strip()
    clean_project_id = str(project_id or "").strip()
    folder_prefix = f"workspace/{clean_user_id}/{clean_project_id}/"

    try:
        storage = get_storage()
        storage.create(f"{folder_prefix}.keep", b"")
        print(f"[WorkspaceManager] [+] Created storage folder placeholder: {folder_prefix}.keep")
    except Exception as exc:
        print(f"[WorkspaceManager] [!] Storage folder creation note: {exc}")

    return folder_prefix


def copy_template_files(template_id: str, user_id: str, project_id: str) -> List[str]:
    """
    Copies all template files from templates/{template_id}/ to:
    workspace/{user_id}/{project_id}/ using the unified storage adapter.
    """
    clean_template_id = str(template_id or "").strip()
    clean_user_id = str(user_id or "").strip()
    clean_project_id = str(project_id or "").strip()

    src_prefix = f"templates/{clean_template_id}/"
    dest_prefix = f"workspace/{clean_user_id}/{clean_project_id}/"

    storage = get_storage()
    copied_keys: List[str] = []

    try:
        file_keys = storage.list_files(prefix=src_prefix)
        print(f"[WorkspaceManager] Found {len(file_keys)} template file(s) under '{src_prefix}'")

        # Fast path: If CloudStorageAdapter with S3 client, perform server-side copy
        if hasattr(storage, "s3_client") and getattr(storage, "bucket_name", None):
            try:
                for src_key in file_keys:
                    rel_path = src_key[len(src_prefix):]
                    if not rel_path or rel_path.endswith("/"):
                        continue
                    dest_key = f"{dest_prefix}{rel_path}"
                    storage.s3_client.copy_object(
                        Bucket=storage.bucket_name,
                        CopySource=f"{storage.bucket_name}/{src_key}",
                        Key=dest_key
                    )
                    copied_keys.append(dest_key)
                    print(f"[WorkspaceManager] [+] Server-side copied: {src_key} -> {dest_key}")
                return copied_keys
            except Exception as s3_err:
                print(f"[WorkspaceManager] [!] S3 server copy note ({s3_err}), falling back to read/create...")

        # Universal fallback path (works for local and cloud storage)
        for src_key in file_keys:
            rel_path = src_key[len(src_prefix):]
            if not rel_path or rel_path.endswith("/"):
                continue
            dest_key = f"{dest_prefix}{rel_path}"
            data = storage.read(src_key)
            storage.create(dest_key, data)
            copied_keys.append(dest_key)
            print(f"[WorkspaceManager] [+] Copied: {src_key} -> {dest_key}")

    except Exception as exc:
        print(f"[WorkspaceManager] [-] Error copying template files: {exc}", file=sys.stderr)
        raise RuntimeError(f"Copying template files failed: {str(exc)}") from exc

    return copied_keys


def fetch_workspace_history_from_storage(user_id: str) -> List[Dict[str, Any]]:
    """
    Scans storage under workspace/{user_id}/ to collect slide counts,
    presentation files, and folder metadata.
    """
    clean_user_id = str(user_id or "").strip()
    prefix = f"workspace/{clean_user_id}/"

    storage = get_storage()
    projects: Dict[str, Dict[str, Any]] = {}

    try:
        all_files = storage.list_files(prefix=prefix)
        for key in all_files:
            # Expected format: workspace/{user_id}/{project_id}/...
            parts = key.split("/")
            if len(parts) >= 3:
                pid = parts[2]
                if pid and pid not in projects:
                    folder_path = f"workspace/{clean_user_id}/{pid}/"
                    projects[pid] = {
                        "project_id": pid,
                        "storage_folder": folder_path,
                        "s3_folder": folder_path,
                        "slide_count": 0,
                        "has_pptx": False,
                    }

        # Check manifest.json or count slides for each discovered project
        for pid, pdata in projects.items():
            manifest_key = f"workspace/{clean_user_id}/{pid}/manifest.json"
            try:
                if storage.exists(manifest_key):
                    raw_text = storage.read_text(manifest_key)
                    m_data = json.loads(raw_text)
                    slides = m_data if isinstance(m_data, list) else m_data.get("slides", [])
                    pdata["slide_count"] = len(slides)
            except Exception:
                pass

            if pdata["slide_count"] == 0:
                slides_prefix = f"workspace/{clean_user_id}/{pid}/slides/"
                slide_files = [f for f in all_files if f.startswith(slides_prefix) and f.endswith(".svg")]
                pdata["slide_count"] = len(slide_files)

            pptx_key = f"workspace/{clean_user_id}/{pid}/presentation.pptx"
            pdata["has_pptx"] = storage.exists(pptx_key)

    except Exception as exc:
        print(f"[WorkspaceManager] [!] Warning scanning storage history for {clean_user_id}: {exc}")

    return list(projects.values())


def delete_workspace_storage(user_id: str, project_id: str) -> int:
    """
    Deletes all files and objects under workspace/{user_id}/{project_id}/
    using the unified storage adapter.
    """
    clean_user_id = str(user_id or "").strip()
    clean_project_id = str(project_id or "").strip()

    if not clean_user_id or not clean_project_id:
        return 0

    prefix = f"workspace/{clean_user_id}/{clean_project_id}/"
    try:
        storage = get_storage()
        deleted_count = storage.delete_prefix(prefix)
        print(f"[WorkspaceManager] [+] Deleted {deleted_count} storage object(s) under '{prefix}'")
        return deleted_count
    except Exception as exc:
        print(f"[WorkspaceManager] [!] Note deleting storage prefix {prefix}: {exc}")
        return 0


# ==============================================================================
# Workspace Business Logic Services
# ==============================================================================

def create_workspace(
    project_name: str,
    user_id: str,
    template_id: str,
    database_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    1. Validates input and determines source mode.
    2. Inserts project record into PostgreSQL workspace table.
    3. Creates storage folder placeholder.
    4. Copies all files and folders from templates/{template_id}/ to workspace/{user_id}/{project_id}/.
    5. Initializes manifest.json.
    """
    clean_name = str(project_name or "").strip()
    clean_user_id = str(user_id or "").strip()
    clean_template_id = str(template_id or "").strip()
    clean_db_id = str(database_id or "").strip() if database_id else None
    clean_col_id = str(collection_id or "").strip() if collection_id else None

    if not clean_name:
        raise ValueError("Project name is required.")
    if not clean_user_id or not clean_template_id:
        raise ValueError("user_id and template_id are required.")

    # Determine source: strictly "database" or "documents"
    if clean_col_id and not clean_db_id:
        eff_source = "documents"
    elif clean_db_id and not clean_col_id:
        eff_source = "database"
    elif source in ("database", "documents"):
        eff_source = source
    else:
        eff_source = "database"

    project_id = f"project_{uuid.uuid4()}"

    # 1. Insert into PostgreSQL workspace table
    insert_sql = text("""
        INSERT INTO workspace (project_id, project_name, user_id, database_id, collection_id, source, template_id, created_at, updated_at)
        VALUES (:project_id, :project_name, :user_id, :database_id, :collection_id, :source, :template_id, NOW(), NOW());
    """)

    try:
        with engine.connect() as conn:
            conn.execute(
                insert_sql,
                {
                    "project_id": project_id,
                    "project_name": clean_name,
                    "user_id": clean_user_id,
                    "database_id": clean_db_id,
                    "collection_id": clean_col_id,
                    "source": eff_source,
                    "template_id": clean_template_id,
                }
            )
            conn.commit()
            print(f"[WorkspaceManager] [+] Created workspace DB record '{project_id}' for user '{clean_user_id}'")
    except Exception as db_err:
        print(f"[WorkspaceManager] [-] Database error creating workspace: {db_err}", file=sys.stderr)
        raise RuntimeError(f"Database error creating workspace: {str(db_err)}") from db_err

    # 2. Create storage folder placeholder
    folder_prefix = create_workspace_folder(user_id=clean_user_id, project_id=project_id)

    # 3. Copy template files into project workspace
    copied_files = copy_template_files(
        template_id=clean_template_id,
        user_id=clean_user_id,
        project_id=project_id
    )

    # 4. Initialize manifest.json
    try:
        from .manifest import load_manifest
        manifest_items = load_manifest(user_id=clean_user_id, project_id=project_id)
        print(f"[WorkspaceManager] [+] Initialized manifest.json with {len(manifest_items)} slides for {project_id}")
    except Exception as m_err:
        print(f"[WorkspaceManager] [!] Note initializing manifest for {project_id}: {m_err}")

    return {
        "status": "success",
        "message": "Workspace created and template files copied successfully",
        "project_id": project_id,
        "project_name": clean_name,
        "user_id": clean_user_id,
        "database_id": clean_db_id,
        "collection_id": clean_col_id,
        "source": eff_source,
        "template_id": clean_template_id,
        "storage_folder": folder_prefix,
        "s3_folder": folder_prefix,
        "copied_files_count": len(copied_files),
        "copied_files": copied_files
    }


def get_workspace(project_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single workspace record by project_id (and optionally user_id).
    """
    clean_pid = str(project_id or "").strip()
    if not clean_pid:
        return None

    query = """
        SELECT project_id, project_name, CAST(user_id AS TEXT) as user_id,
               database_id, collection_id, source, template_id, created_at, updated_at
        FROM workspace
        WHERE project_id = :project_id
    """
    params: Dict[str, Any] = {"project_id": clean_pid}
    if user_id:
        query += " AND CAST(user_id AS TEXT) = :user_id"
        params["user_id"] = str(user_id).strip()

    with engine.connect() as conn:
        row = conn.execute(text(query), params).mappings().first()
        return dict(row) if row else None


def _extract_svg_only(text: str) -> str:
    """Extracts pure <svg ... </svg> from text, discarding any outer wrappers."""
    if not text:
        return ""
    start_idx = text.find("<svg")
    end_idx = text.rfind("</svg>")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 6].strip()
    return text.strip()


def is_empty_slide(
    slide_code: Optional[str] = None,
    project_id: Optional[str] = None,
    slide_number: Optional[Union[int, str]] = None,
    user_id: Optional[str] = None
) -> bool:
    """
    Identifies whether a slide is blank based on the manifest.json 'is_blank_slide' flag.
    - If project_id & slide_number are provided, looks up 'is_blank_slide' directly in manifest.json.
    - If slide_code is provided and is completely empty/whitespace, returns True.
    - Returns False by default.
    Zero regex patterns, zero hardcoding.
    """
    if project_id and slide_number is not None:
        try:
            from .manifest import is_slide_blank
            uid = str(user_id or "").strip()
            if not uid:
                ws = get_workspace(project_id)
                if ws:
                    uid = str(ws.get("user_id") or "").strip()
            if uid:
                return is_slide_blank(user_id=uid, project_id=project_id, slide_number=slide_number)
        except Exception as exc:
            print(f"[!] Warning checking is_slide_blank from manifest: {exc}")

    return not bool(slide_code and slide_code.strip())


def GetSVGCode(project_id: str, slide_number: int, user_id: Optional[str] = None) -> str:
    """
    Retrieves the raw SVG slide code from the configured storage adapter.
    Guarantees pure SVG is returned.
    """
    if not project_id or slide_number < 1:
        return ""

    uid = str(user_id or "").strip()
    tmpl_id = None
    if not uid:
        try:
            ws = get_workspace(project_id=project_id)
            if ws:
                uid = str(ws.get("user_id") or "").strip()
                tmpl_id = str(ws.get("template_id") or "").strip()
        except Exception as ws_err:
            print(f"[!] Warning fetching workspace in GetSVGCode: {ws_err}")

    if not uid:
        return ""

    storage = get_storage()
    slides_prefix = f"workspace/{uid}/{project_id}/slides/"

    # 1. First priority: Check direct SVG slide files in workspace (slide_01.svg, slide_1.svg)
    direct_svg_candidates = [
        f"{slides_prefix}slide_{slide_number:02d}.svg",
        f"{slides_prefix}slide_{slide_number}.svg",
    ]
    for svg_key in direct_svg_candidates:
        try:
            if storage.exists(svg_key):
                svg_text = storage.read_text(svg_key)
                if svg_text.strip() and "<svg" in svg_text.lower():
                    print(f"[+] [GetSVGCode] Loaded Slide {slide_number} from direct SVG: {svg_key}")
                    return _extract_svg_only(svg_text)
        except Exception:
            pass

    # 2. Second priority: Resolve via manifest.json
    manifest_key = f"workspace/{uid}/{project_id}/manifest.json"
    try:
        if storage.exists(manifest_key):
            raw_manifest = storage.read_text(manifest_key)
            manifest_data = json.loads(raw_manifest)
            items = manifest_data if isinstance(manifest_data, list) else manifest_data.get("slides", [])
            for item in items:
                if int(item.get("count", 0)) == slide_number:
                    filename = item.get("filename")
                    if filename:
                        # Check if a .svg sibling exists (e.g., UUID.svg)
                        base_name = filename.rsplit(".", 1)[0]
                        svg_sibling = f"{slides_prefix}{base_name}.svg"
                        if storage.exists(svg_sibling):
                            svg_text = storage.read_text(svg_sibling)
                            if svg_text.strip() and "<svg" in svg_text.lower():
                                print(f"[+] [GetSVGCode] Loaded Slide {slide_number} from SVG sibling: {svg_sibling}")
                                return _extract_svg_only(svg_text)

                        # If filename itself exists
                        target_key = f"{slides_prefix}{filename}"
                        if storage.exists(target_key):
                            raw_text = storage.read_text(target_key)
                            if raw_text.strip():
                                if "<svg" in raw_text.lower():
                                    print(f"[+] [GetSVGCode] Loaded Slide {slide_number} ({filename}) from storage: {target_key}")
                                    return _extract_svg_only(raw_text)
    except Exception as m_err:
        print(f"[!] Warning checking manifest in GetSVGCode: {m_err}")

    # 3. Third priority: Check template SVG in storage
    if not tmpl_id:
        try:
            ws = get_workspace(project_id=project_id)
            if ws:
                tmpl_id = str(ws.get("template_id") or "").strip()
        except Exception:
            pass

    if tmpl_id:
        tmpl_candidates = [
            f"templates/{tmpl_id}/slides/slide_{slide_number:02d}.svg",
            f"templates/{tmpl_id}/slides/slide_{slide_number}.svg",
        ]
        for tmpl_key in tmpl_candidates:
            try:
                if storage.exists(tmpl_key):
                    svg_text = storage.read_text(tmpl_key)
                    if svg_text.strip() and "<svg" in svg_text.lower():
                        print(f"[+] [GetSVGCode] Loaded Slide {slide_number} from template SVG: {tmpl_key}")
                        return _extract_svg_only(svg_text)
            except Exception:
                pass

    return ""


def update_workspace_source(
    project_id: str,
    source: str,
    database_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Updates the workspace source mode to either 'database' or 'documents':
    - When source == 'database': saves database_id and erases collection_id (sets to NULL).
    - When source == 'documents': saves collection_id and erases database_id (sets to NULL).
    """
    clean_pid = str(project_id or "").strip()
    clean_source = str(source or "").strip().lower()

    if not clean_pid:
        raise ValueError("project_id is required.")
    if clean_source not in ("database", "documents"):
        raise ValueError("Invalid source. Must be either 'database' or 'documents'.")

    # Verify project exists
    existing = get_workspace(project_id=clean_pid, user_id=user_id)
    if not existing:
        raise KeyError(f"Workspace project '{clean_pid}' not found or access denied.")

    clean_db_id = str(database_id).strip() if database_id else None
    clean_col_id = str(collection_id).strip() if collection_id else None

    if clean_source == "database":
        final_db_id = clean_db_id or existing.get("database_id")
        final_col_id = None
    else:
        final_col_id = clean_col_id or existing.get("collection_id")
        final_db_id = None

    update_sql = text("""
        UPDATE workspace
        SET source = :source,
            database_id = :database_id,
            collection_id = :collection_id,
            updated_at = NOW()
        WHERE project_id = :project_id
        RETURNING project_id, project_name, source, database_id, collection_id;
    """)

    with engine.connect() as conn:
        res = conn.execute(
            update_sql,
            {
                "source": clean_source,
                "database_id": final_db_id,
                "collection_id": final_col_id,
                "project_id": clean_pid
            }
        ).mappings().first()
        conn.commit()

        return {
            "status": "success",
            "message": f"Workspace source updated to '{clean_source}' successfully",
            "project_id": res["project_id"],
            "source": res["source"],
            "database_id": res["database_id"],
            "collection_id": res["collection_id"],
        }


def update_workspace_request_mode(
    project_id: str,
    request_mode: str,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Updates the workspace response/request mode to either 'ask' or 'agent':
    - 'ask': Direct Q&A and conversational data answers.
    - 'agent': Full autonomous multi-agent planning & presentation slide editing.
    """
    clean_pid = str(project_id or "").strip()
    clean_mode = str(request_mode or "").strip().lower()

    if not clean_pid:
        raise ValueError("project_id is required.")
    if clean_mode not in ("ask", "agent"):
        raise ValueError("Invalid request_mode. Must be either 'ask' or 'agent'.")

    # Verify project exists
    existing = get_workspace(project_id=clean_pid, user_id=user_id)
    if not existing:
        raise KeyError(f"Workspace project '{clean_pid}' not found or access denied.")

    # Resilient update: updates response_mode column, fall back to request_mode if needed
    try:
        update_sql = text("""
            UPDATE workspace
            SET response_mode = :mode,
                updated_at = NOW()
            WHERE project_id = :project_id;
        """)
        with engine.connect() as conn:
            conn.execute(
                update_sql,
                {"mode": clean_mode, "project_id": clean_pid}
            )
            conn.commit()
    except Exception as exc:
        try:
            fallback_sql = text("""
                UPDATE workspace
                SET request_mode = :mode,
                    updated_at = NOW()
                WHERE project_id = :project_id;
            """)
            with engine.connect() as conn:
                conn.execute(
                    fallback_sql,
                    {"mode": clean_mode, "project_id": clean_pid}
                )
                conn.commit()
        except Exception:
            raise exc

    return {
        "status": "success",
        "message": f"Workspace mode updated to '{clean_mode}' successfully",
        "project_id": clean_pid,
        "request_mode": clean_mode,
        "response_mode": clean_mode,
    }


def list_user_workspaces(user_id: str) -> List[Dict[str, Any]]:
    """
    Fetches all workspace projects for a user, combining DB records and storage metadata.
    """
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        return []

    # 1. Fetch storage metadata (slide count, pptx presence)
    storage_projects = fetch_workspace_history_from_storage(clean_user_id)
    storage_map = {p["project_id"]: p for p in storage_projects}

    # 2. Query DB workspace table enriched with DB name, collection name, and template name
    db_map: Dict[str, Dict[str, Any]] = {}
    query_sql_with_mode = text("""
        SELECT 
            w.project_id, 
            w.project_name, 
            CAST(w.user_id AS TEXT) as user_id, 
            w.database_id, 
            w.collection_id,
            w.source,
            w.response_mode,
            w.template_id, 
            w.created_at, 
            w.updated_at,
            d.database_name, 
            d.database_type,
            d.display_name as database_display_name,
            c.display_name as collection_display_name,
            t.template_name,
            t.category as template_category
        FROM workspace w
        LEFT JOIN user_databases d ON w.database_id = d.db_id
        LEFT JOIN user_collections c ON w.collection_id = c.collection_id
        LEFT JOIN templates t ON w.template_id = t.template_id
        WHERE CAST(w.user_id AS TEXT) = :user_id
        ORDER BY w.updated_at DESC;
    """)

    query_sql_basic = text("""
        SELECT 
            w.project_id, 
            w.project_name, 
            CAST(w.user_id AS TEXT) as user_id, 
            w.database_id, 
            w.collection_id,
            w.source,
            w.template_id, 
            w.created_at, 
            w.updated_at,
            d.database_name, 
            d.database_type,
            d.display_name as database_display_name,
            c.display_name as collection_display_name,
            t.template_name,
            t.category as template_category
        FROM workspace w
        LEFT JOIN user_databases d ON w.database_id = d.db_id
        LEFT JOIN user_collections c ON w.collection_id = c.collection_id
        LEFT JOIN templates t ON w.template_id = t.template_id
        WHERE CAST(w.user_id AS TEXT) = :user_id
        ORDER BY w.updated_at DESC;
    """)

    try:
        with engine.connect() as conn:
            try:
                rows = conn.execute(query_sql_with_mode, {"user_id": clean_user_id}).fetchall()
            except Exception:
                rows = conn.execute(query_sql_basic, {"user_id": clean_user_id}).fetchall()
            for r in rows:
                db_map[r.project_id] = dict(r._mapping)
    except Exception as exc:
        print(f"[WorkspaceManager] [-] Error fetching DB workspaces for {clean_user_id}: {exc}")

    # 3. Merge DB records with storage info
    all_project_ids = list(dict.fromkeys(list(storage_map.keys()) + list(db_map.keys())))
    merged_workspaces = []

    for pid in all_project_ids:
        s_info = storage_map.get(pid, {})
        d_info = db_map.get(pid, {})

        created_at = d_info.get("created_at")
        updated_at = d_info.get("updated_at")

        default_name = pid.replace("project_", "Project ").replace("_", " ").title()
        project_name = d_info.get("project_name") or default_name

        has_db = bool(d_info.get("database_id"))
        has_col = bool(d_info.get("collection_id"))
        if has_db and not has_col:
            item_source = "database"
        elif has_col and not has_db:
            item_source = "documents"
        else:
            item_source = d_info.get("source") if d_info.get("source") in ("database", "documents") else "database"

        folder_path = s_info.get("storage_folder") or f"workspace/{clean_user_id}/{pid}/"

        merged_workspaces.append({
            "project_id": pid,
            "project_name": project_name,
            "user_id": clean_user_id,
            "database_id": d_info.get("database_id"),
            "database_name": d_info.get("database_name"),
            "database_display_name": d_info.get("database_display_name") or d_info.get("database_name"),
            "database_type": d_info.get("database_type"),
            "collection_id": d_info.get("collection_id"),
            "collection_display_name": d_info.get("collection_display_name"),
            "source": item_source,
            "response_mode": d_info.get("response_mode") or "agent",
            "template_id": d_info.get("template_id"),
            "template_name": d_info.get("template_name"),
            "template_category": d_info.get("template_category"),
            "slide_count": s_info.get("slide_count", 0),
            "has_pptx": s_info.get("has_pptx", False),
            "storage_folder": folder_path,
            "s3_folder": folder_path,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        })

    # Sort newest first
    merged_workspaces.sort(
        key=lambda w: w.get("updated_at") or w.get("created_at") or "",
        reverse=True
    )

    return merged_workspaces


def delete_workspace(project_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Deletes a project workspace completely:
    1. Resolves and checks user ownership.
    2. Deletes all files from storage under workspace/{user_id}/{project_id}/.
    3. Deletes dependent records from chat_messages table.
    4. Deletes workspace record from workspace table.
    """
    clean_pid = str(project_id or "").strip()
    if not clean_pid:
        raise ValueError("project_id is required.")

    # 1. Look up user_id from DB if not provided
    eff_user_id = str(user_id or "").strip()
    if not eff_user_id:
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT CAST(user_id AS TEXT) as user_id FROM workspace WHERE project_id = :pid LIMIT 1;"),
                    {"pid": clean_pid}
                ).fetchone()
                if row:
                    eff_user_id = str(row.user_id)
        except Exception as err:
            print(f"[WorkspaceManager] [-] Error resolving user_id for project '{clean_pid}': {err}")

    # 2. Delete storage files
    storage_deleted_count = 0
    if eff_user_id:
        storage_deleted_count = delete_workspace_storage(
            user_id=eff_user_id,
            project_id=clean_pid
        )

    # 3. Delete database records (chat_messages and workspace)
    db_deleted = False
    try:
        with engine.begin() as conn:
            # Delete dependent chat messages first
            conn.execute(
                text("DELETE FROM chat_messages WHERE project_id = :pid;"),
                {"pid": clean_pid}
            )
            # Delete from workspace table
            del_sql = "DELETE FROM workspace WHERE project_id = :pid"
            params: Dict[str, Any] = {"pid": clean_pid}
            if user_id:
                del_sql += " AND CAST(user_id AS TEXT) = :uid"
                params["uid"] = str(user_id).strip()

            res = conn.execute(text(del_sql), params)
            db_deleted = (res.rowcount or 0) > 0
            print(f"[WorkspaceManager] [+] Deleted workspace table record '{clean_pid}' (rows: {res.rowcount})")
    except Exception as exc:
        print(f"[WorkspaceManager] [-] Error deleting workspace from database: {exc}", file=sys.stderr)
        raise RuntimeError(f"Failed to delete project from database: {str(exc)}") from exc

    return {
        "status": "success",
        "message": f"Project '{clean_pid}' deleted successfully from database and storage.",
        "project_id": clean_pid,
        "user_id": eff_user_id,
        "storage_objects_deleted": storage_deleted_count,
        "db_record_deleted": db_deleted
    }
