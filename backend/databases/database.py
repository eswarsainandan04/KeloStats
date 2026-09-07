import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import create_engine, text

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://root:@localhost:5432/kelostats")

# Global reusable engine for metadata persistence
app_db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Import pure connection handlers
from .postgres_connection import _postgres_connection
from .mysql_connection import _mysql_connection
from .oracle_sql_connection import _oracle_sql_connection
from .schema_extraction.extractor import _schema_extraction

# Allowed database dialects
SUPPORTED_DATABASES = ["mysql", "postgres", "oracle_sql"]


# ---------------------------------------------------------------------------
# Centralized Persistence Helper (Prevents Duplicates via Upsert)
# ---------------------------------------------------------------------------
def save_user_database_credential(
    user_id: str,
    database_type: str,
    host: str,
    port: int,
    username: str,
    password: str,
    database_name: Optional[str] = None,
    schema_name: Optional[str] = None,
    service_name: Optional[str] = None,
    ssl_mode: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Centralized helper to save database credentials.
    Prevents duplicates by checking if the user has already configured this database.
    If it exists: Updates the credentials and returns the existing db_id.
    If it does not exist: Inserts a new row with a new db_id.
    """
    now = datetime.utcnow()
    clean_display = (display_name or "").strip() or (database_name or "").strip() or (service_name or "").strip() or f"{database_type.capitalize()} DB"

    check_sql = text("""
        SELECT db_id FROM user_databases
        WHERE user_id = :user_id
          AND database_type = :database_type
          AND host = :host
          AND port = :port
          AND COALESCE(database_name, '') = COALESCE(:database_name, '')
          AND COALESCE(schema_name, '') = COALESCE(:schema_name, '')
          AND COALESCE(service_name, '') = COALESCE(:service_name, '')
        LIMIT 1
    """)

    params = {
        "user_id": str(user_id),
        "database_type": database_type.lower(),
        "database_name": database_name or "",
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "schema_name": schema_name or "",
        "service_name": service_name or "",
        "ssl_mode": ssl_mode or "",
        "display_name": clean_display,
        "updated_at": now,
    }

    with app_db_engine.connect() as conn:
        existing_id = conn.execute(check_sql, params).scalar()

        if existing_id:
            # Update existing record
            update_sql = text("""
                UPDATE user_databases
                SET username = :username,
                    password = :password,
                    ssl_mode = :ssl_mode,
                    display_name = COALESCE(NULLIF(:display_name, ''), display_name),
                    updated_at = :updated_at
                WHERE db_id = :db_id
            """)
            conn.execute(update_sql, {**params, "db_id": existing_id})
            conn.commit()
            return {
                "db_id": str(existing_id),
                "action": "updated",
                "message": f"Existing {database_type.capitalize()} database credentials updated successfully."
            }
        else:
            # Insert brand new record with db_{uuid} prefix
            generated_id = f"db_{uuid.uuid4()}"
            insert_sql = text("""
                INSERT INTO user_databases (
                    db_id, user_id, database_type, database_name,
                    host, port, username, password,
                    schema_name, service_name, ssl_mode, display_name, created_at, updated_at
                ) VALUES (
                    :db_id, :user_id, :database_type, :database_name,
                    :host, :port, :username, :password,
                    :schema_name, :service_name, :ssl_mode, :display_name, :created_at, :updated_at
                )
            """)
            conn.execute(insert_sql, {**params, "db_id": generated_id, "created_at": now})
            conn.commit()
            return {
                "db_id": generated_id,
                "action": "created",
                "message": f"New {database_type.capitalize()} database credentials saved successfully."
            }


# ---------------------------------------------------------------------------
# Database Selection, Verification & Orchestration
# ---------------------------------------------------------------------------
def select_database_type(
    user_id: str,
    db_type: str,
    host: str,
    port: int,
    username: str,
    password: str,
    database_name: Optional[str] = None,
    schema_name: Optional[str] = None,
    service_name: Optional[str] = None,
    ssl_mode: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    1. Tests connection via target connector (Postgres, MySQL, Oracle) including SSL settings.
    2. If connection succeeds, saves or updates credentials in user_databases table centrally without duplicates.
    """
    normalized_type = (db_type or "").lower().strip()

    if normalized_type not in SUPPORTED_DATABASES:
        raise ValueError(
            f"Invalid database_type '{db_type}'. Must be one of: {SUPPORTED_DATABASES}"
        )

    # 1. Test target database connection with SSL mode
    if normalized_type == "mysql":
        connection_result = _mysql_connection(
            user_id=user_id,
            database_name=database_name or "",
            host=host,
            port=port,
            username=username,
            password=password,
            schema_name=schema_name,
            ssl_mode=ssl_mode
        )
    elif normalized_type == "postgres":
        connection_result = _postgres_connection(
            user_id=user_id,
            database_name=database_name or "",
            host=host,
            port=port,
            username=username,
            password=password,
            schema_name=schema_name or "public",
            ssl_mode=ssl_mode
        )
    elif normalized_type == "oracle_sql":
        connection_result = _oracle_sql_connection(
            user_id=user_id,
            database_name=database_name,
            host=host,
            port=port,
            username=username,
            password=password,
            service_name=service_name,
            schema_name=schema_name,
            ssl_mode=ssl_mode
        )

    # 2. If target connection succeeded, persist/update credentials in the metadata DB
    if connection_result.get("status") == "success":
        try:
            save_result = save_user_database_credential(
                user_id=user_id,
                database_type=normalized_type,
                host=host,
                port=port,
                username=username,
                password=password,
                database_name=database_name,
                schema_name=schema_name,
                service_name=service_name,
                ssl_mode=ssl_mode,
                display_name=display_name,
            )
            db_id = save_result["db_id"]
            connection_result["db_id"] = db_id
            connection_result["action"] = save_result["action"]
            connection_result["message"] = save_result["message"]

            # 3. Trigger dynamic schema extraction and save output to output/{db_id}.json
            try:
                extraction_res = _schema_extraction(
                    db_id=db_id,
                    user_id=user_id,
                    database_type=normalized_type,
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    database_name=database_name,
                    schema_name=schema_name,
                    service_name=service_name,
                    ssl_mode=ssl_mode,
                )
                connection_result["schema_file"] = extraction_res.get("file_path")
                connection_result["total_tables_extracted"] = extraction_res.get("total_tables")
            except Exception as extract_err:
                print(f"[!] Schema extraction warning: {extract_err}")
                connection_result["schema_extraction_error"] = str(extract_err)

        except Exception as db_err:
            connection_result["status"] = "partial_success"
            connection_result["message"] = f"Connection verified, but failed to save credentials into database: {str(db_err)}"

    return connection_result


# ---------------------------------------------------------------------------
# Database Module API Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/databases", tags=["Databases"])




@router.post("/connect", summary="Connect and save user database credentials (Upsert)")
def connect_database_endpoint(payload: dict):
    """
    Connect Database flow:
    - User selects db_type from ['mysql', 'postgres', 'oracle_sql'].
    - System verifies connection to target database with SSL mode.
    - If verified, centrally inserts or updates credentials into user_databases table without duplicates.
    """
    try:
        result = select_database_type(
            user_id=payload.get("user_id"),
            db_type=payload.get("database_type"),
            host=payload.get("host"),
            port=int(payload.get("port") or 0),
            username=payload.get("username"),
            password=payload.get("password", ""),
            database_name=payload.get("database_name"),
            schema_name=payload.get("schema_name"),
            service_name=payload.get("service_name"),
            ssl_mode=payload.get("ssl_mode"),
            display_name=payload.get("display_name"),
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


@router.get("/database_info", summary="Get connected database information")
def get_database_info_endpoint(user_id: str):
    """
    Returns list of all databases connected and saved by the user.
    user_id is compulsory.
    Accessible via: GET /api/databases/database_info?user_id=...
    """
    if not user_id or not user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is compulsory."
        )

    try:
        sql = text("""
            SELECT db_id, database_type, database_name, host, port, username, schema_name, service_name, ssl_mode, created_at, display_name
            FROM user_databases
            WHERE user_id = :user_id
            ORDER BY created_at DESC
        """)
        with app_db_engine.connect() as conn:
            rows = conn.execute(sql, {"user_id": user_id.strip()}).fetchall()
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


class DeleteDatabasePayload(BaseModel):
    db_id: Optional[str] = None
    user_id: Optional[str] = None


@router.delete("/delete", summary="Delete connected database credentials")
@router.post("/delete", summary="Delete connected database credentials")
def delete_database_endpoint(
    payload: Optional[DeleteDatabasePayload] = None,
    db_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """
    Deletes a connected database credentials record from user_databases table.
    Also cleans up extracted schema JSON if cached locally.
    Accessible via:
      POST /api/databases/delete  (JSON body: {"db_id": "...", "user_id": "..."})
      DELETE /api/databases/delete?db_id=...&user_id=...
    """
    target_db_id = (payload.db_id if payload and payload.db_id else db_id or "").strip()
    target_user_id = (payload.user_id if payload and payload.user_id else user_id or "").strip()

    if not target_db_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="db_id is required."
        )

    try:
        # 1. Delete from user_databases table
        with app_db_engine.begin() as conn:
            if target_user_id:
                delete_sql = text("DELETE FROM user_databases WHERE db_id = :db_id AND CAST(user_id AS TEXT) = :user_id;")
                result = conn.execute(delete_sql, {"db_id": target_db_id, "user_id": target_user_id})
            else:
                delete_sql = text("DELETE FROM user_databases WHERE db_id = :db_id;")
                result = conn.execute(delete_sql, {"db_id": target_db_id})

            print(f"[+] [Delete DB] Deleted db_id '{target_db_id}' (rows affected: {result.rowcount})")

        # 2. Clean up any cached schema json files
        schema_file = Path(__file__).resolve().parent / "schema_extraction" / "output" / f"{target_db_id}.json"
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


@router.delete("/{db_id}", summary="Delete database by path parameter")
def delete_database_by_path(
    db_id: str,
    user_id: Optional[str] = Query(None)
):
    """Convenience DELETE endpoint allowing /api/databases/{db_id}."""
    return delete_database_endpoint(payload=None, db_id=db_id, user_id=user_id)
