import os
import uuid
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from sqlalchemy import create_engine, text
from app.core.config import settings

DATABASE_URL = settings.DATABASE_URL or os.getenv("DATABASE_URL", "postgresql://root:@localhost:5432/kelostats")

# Global reusable engine for metadata persistence
app_db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Import pure connection handlers
from .postgres_connection import _postgres_connection
from .mysql_connection import _mysql_connection
from .oracle_sql_connection import _oracle_sql_connection
from .schema.extractor import _schema_extraction

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
