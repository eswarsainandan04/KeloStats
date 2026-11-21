import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.auth import get_current_user_id
from app.services.connectors.database import app_db_engine, select_database_type

router = APIRouter(prefix="/databases", tags=["Databases / Connectors"])


# ==============================================================================
# 1. Connect Database Endpoint (Upsert)
# ==============================================================================

class ConnectDatabasePayload(BaseModel):
    user_id: Optional[str] = None
    database_type: str
    host: str
    port: int
    username: str
    password: Optional[str] = ""
    database_name: Optional[str] = None
    schema_name: Optional[str] = None
    service_name: Optional[str] = None
    ssl_mode: Optional[str] = None
    display_name: Optional[str] = None


@router.post("/connect", summary="Connect and save user database credentials (Upsert)")
def connect_database_endpoint(
    payload: ConnectDatabasePayload,
    authenticated_user_id: str = Depends(get_current_user_id),
):
    """
    Connect Database flow:
    - User selects db_type from ['mysql', 'postgres', 'oracle_sql'].
    - System verifies connection to target database with SSL mode.
    - If verified, centrally inserts or updates credentials into user_databases table without duplicates.
    - Enforces authenticated user_id from the verified JWT token.
    """
    # Prefer authenticated user_id from JWT token over payload
    target_uid = authenticated_user_id or payload.user_id

    try:
        result = select_database_type(
            user_id=target_uid,
            db_type=payload.database_type,
            host=payload.host,
            port=int(payload.port or 0),
            username=payload.username,
            password=payload.password or "",
            database_name=payload.database_name,
            schema_name=payload.schema_name,
            service_name=payload.service_name,
            ssl_mode=payload.ssl_mode,
            display_name=payload.display_name,
        )

        if result.get("status") == "failed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message")
            )
        return result

    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Connection error: {str(exc)}"
        )


# ==============================================================================
# 2. Get Database Information Endpoint
# ==============================================================================

@router.get("/database_info", summary="Get connected database information")
def get_database_info_endpoint(
    user_id: Optional[str] = Query(None, description="Optional override user_id"),
    authenticated_user_id: str = Depends(get_current_user_id),
):
    """
    Returns list of all databases connected and saved by the user.
    Uses verified user_id from JWT authentication.
    Accessible via: GET /api/databases/database_info
    """
    target_uid = authenticated_user_id or user_id
    if not target_uid or not str(target_uid).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is compulsory."
        )

    try:
        sql = text("""
            SELECT db_id, database_type, database_name, host, port, username, schema_name, service_name, ssl_mode, created_at, display_name
            FROM user_databases
            WHERE CAST(user_id AS TEXT) = :user_id
            ORDER BY created_at DESC
        """)
        with app_db_engine.connect() as conn:
            rows = conn.execute(sql, {"user_id": str(target_uid).strip()}).fetchall()
            databases = []
            for row in rows:
                db_name = row[2] or ""
                srv_name = row[7] or ""
                disp_name = row[10] if len(row) > 10 and row[10] else None
                final_display_name = (disp_name or "").strip() or db_name or srv_name or "Database"

                databases.append({
                    "db_id": row[0],
                    "database_type": row[1],
                    "database_name": db_name,
                    "host": row[3],
                    "port": row[4],
                    "username": row[5],
                    "schema_name": row[6],
                    "service_name": srv_name,
                    "ssl_mode": row[8],
                    "created_at": str(row[9]) if row[9] else None,
                    "display_name": final_display_name,
                })
            return {"status": "success", "databases": databases}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch databases: {str(exc)}"
        )


# ==============================================================================
# 3. Get Database Schema Endpoint
# ==============================================================================

@router.get("/schema", summary="Get database schema and tables metadata from user_databases table")
def get_database_schema_endpoint(
    database_id: Optional[str] = Query(None, description="Database ID"),
    db_id: Optional[str] = Query(None, description="Alternative parameter for database ID"),
    authenticated_user_id: str = Depends(get_current_user_id),
):
    """
    Fetches the extracted database schema and tables information stored in the
    'schema' JSON column of the 'user_databases' table.
    Accessible via:
      GET /api/databases/schema?database_id=...
      GET /api/database/schema?database_id=...
    """
    target_id = (database_id or db_id or "").strip()
    if not target_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="database_id is required."
        )

    try:
        sql = text("""
            SELECT db_id, database_type, database_name, display_name, schema_name, service_name, schema
            FROM user_databases
            WHERE db_id = :db_id
            LIMIT 1;
        """)

        with app_db_engine.connect() as conn:
            row = conn.execute(sql, {"db_id": target_id}).fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Database with ID '{target_id}' was not found."
            )

        db_id_val, db_type, db_name, disp_name, schema_name, srv_name, schema_col = row

        # Parse schema column from user_databases table
        schema_data = None
        if schema_col is not None:
            if isinstance(schema_col, dict):
                schema_data = schema_col
            elif isinstance(schema_col, str) and schema_col.strip():
                try:
                    schema_data = json.loads(schema_col)
                except Exception as parse_err:
                    print(f"[!] Error parsing schema JSON string from DB: {parse_err}")

        # Fallback to local output/{db_id}.json file if not found in database column
        if not schema_data:
            base_conn = Path(__file__).resolve().parent.parent.parent / "services" / "connectors"
            local_file = base_conn / "schema" / "output" / f"{target_id}.json"
            if not local_file.exists():
                local_file = base_conn / "output" / f"{target_id}.json"

            if local_file.exists():
                try:
                    with open(local_file, "r", encoding="utf-8") as f:
                        schema_data = json.load(f)
                except Exception as f_err:
                    print(f"[!] Error reading local schema file: {f_err}")

        if not schema_data:
            return {
                "status": "not_found",
                "message": "No schema has been extracted for this database yet.",
                "database_id": target_id,
                "database_name": (disp_name or "").strip() or db_name or srv_name or "Database",
                "database_type": db_type,
                "tables": [],
                "total_tables": 0
            }

        tables = schema_data.get("tables", [])

        return {
            "status": "success",
            "database_id": target_id,
            "database_name": (disp_name or "").strip() or db_name or srv_name or schema_data.get("database_name", "Database"),
            "database_type": db_type or schema_data.get("database_type"),
            "schema_name": schema_name or schema_data.get("schema_name"),
            "service_name": srv_name or schema_data.get("service_name"),
            "total_tables": len(tables),
            "tables": tables,
            "schema": schema_data
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch schema: {str(exc)}"
        )


# ==============================================================================
# 4. Delete Database Endpoint
# ==============================================================================

class DeleteDatabasePayload(BaseModel):
    db_id: Optional[str] = None
    user_id: Optional[str] = None


@router.post("/delete", summary="Delete connected database credentials")
def delete_database_endpoint(
    payload: Optional[DeleteDatabasePayload] = None,
    db_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    authenticated_user_id: str = Depends(get_current_user_id),
):
    """
    Deletes a connected database credentials record from user_databases table.
    Enforces user ownership: only the user who connected the DB can delete it.
    Accessible via:
      POST /api/databases/delete  (JSON body: {"db_id": "..."})
    """
    target_db_id = (payload.db_id if payload and payload.db_id else db_id or "").strip()
    target_user_id = authenticated_user_id or (payload.user_id if payload and payload.user_id else user_id or "").strip()

    if not target_db_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="db_id is required."
        )

    try:
        # 1. Delete from user_databases table with strict user_id ownership check
        with app_db_engine.begin() as conn:
            if target_user_id:
                delete_sql = text("DELETE FROM user_databases WHERE db_id = :db_id AND CAST(user_id AS TEXT) = :user_id;")
                result = conn.execute(delete_sql, {"db_id": target_db_id, "user_id": str(target_user_id)})
            else:
                delete_sql = text("DELETE FROM user_databases WHERE db_id = :db_id;")
                result = conn.execute(delete_sql, {"db_id": target_db_id})

            print(f"[+] [Delete DB] Deleted db_id '{target_db_id}' (rows affected: {result.rowcount})")

        # 2. Clean up any cached schema json files (in schema/output or output)
        base_conn = Path(__file__).resolve().parent.parent.parent / "services" / "connectors"
        for output_sub in ["schema/output", "output"]:
            schema_file = base_conn / output_sub / f"{target_db_id}.json"
            if schema_file.exists():
                try:
                    schema_file.unlink()
                    print(f"[+] [Delete DB] Removed cached schema file: {schema_file}")
                except Exception as f_err:
                    print(f"[!] [Delete DB] Could not remove schema file: {f_err}")

        return {
            "status": "success",
            "message": f"Database '{target_db_id}' deleted successfully.",
            "db_id": target_db_id
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete database: {str(exc)}"
        )
