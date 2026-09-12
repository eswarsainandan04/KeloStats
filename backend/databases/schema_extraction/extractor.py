import json
import os
import urllib.parse
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import uuid

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.types import (
    Integer,
    BigInteger,
    SmallInteger,
    Numeric,
    Float,
    Date,
    DateTime,
    Time,
    Interval,
    TIMESTAMP,
    String,
    Text as SQLText,
    Boolean,
    Enum as SQLEnum,
)


def is_categorical(series: pd.Series) -> bool:
    """
    Determines if a pandas Series is categorical using pandas dtype keyword checkers.
    """
    numeric_series = pd.to_numeric(series, errors="ignore")
    if pd.api.types.is_numeric_dtype(numeric_series) or pd.api.types.is_datetime64_any_dtype(numeric_series):
        return False

    return bool(
        pd.api.types.is_object_dtype(numeric_series)
        or pd.api.types.is_string_dtype(numeric_series)
        or pd.api.types.is_bool_dtype(numeric_series)
        or pd.api.types.is_categorical_dtype(numeric_series)
    )


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to serialize datetime, Decimal, UUID, and binary objects."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime, date, time)):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj) if "." in str(obj) else int(obj)
        elif isinstance(obj, uuid.UUID):
            return str(obj)
        elif isinstance(obj, bytes):
            try:
                return obj.decode("utf-8")
            except Exception:
                return str(obj)
        return super().default(obj)


def _build_target_engine(
    database_type: str,
    host: str,
    port: int,
    username: str,
    password: str,
    database_name: Optional[str] = None,
    schema_name: Optional[str] = None,
    service_name: Optional[str] = None,
    ssl_mode: Optional[str] = None,
) -> Engine:
    """Builds and returns an active SQLAlchemy Engine for the target database."""
    db_type = (database_type or "").lower().strip()
    encoded_user = urllib.parse.quote_plus(str(username))
    encoded_pass = urllib.parse.quote_plus(str(password)) if password else ""
    port_int = int(port) if port else 5432

    if db_type in ["postgres", "postgresql"]:
        db_target = database_name or "postgres"
        url = f"postgresql+psycopg2://{encoded_user}:{encoded_pass}@{host}:{port_int}/{db_target}"
        if ssl_mode and str(ssl_mode).strip().lower() != "none":
            url += f"?sslmode={str(ssl_mode).strip()}"
        return create_engine(url, connect_args={"connect_timeout": 10}, pool_pre_ping=True)

    elif db_type in ["mysql"]:
        db_target = database_name or schema_name or ""
        url = f"mysql+pymysql://{encoded_user}:{encoded_pass}@{host}:{port_int}/{db_target}"
        return create_engine(url, connect_args={"connect_timeout": 10}, pool_pre_ping=True)

    elif db_type in ["oracle", "oracle_sql"]:
        target_service = service_name or database_name or "XE"
        url = f"oracle+oracledb://{encoded_user}:{encoded_pass}@{host}:{port_int}/?service_name={target_service}"
        return create_engine(url, connect_args={"connect_timeout": 10}, pool_pre_ping=True)

    else:
        raise ValueError(f"Unsupported database_type '{database_type}' for schema extraction.")


def _quote_ident(ident: str, db_type: str) -> str:
    """Quotes identifiers (table or column names) based on database dialect."""
    if db_type in ["mysql"]:
        return f"`{ident}`"
    else:
        return f'"{ident}"'


def _schema_extraction(
    db_id: str,
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
) -> Dict[str, Any]:
    """
    Extracts dynamic metadata and schema summary for a database and saves to output/{db_id}.json.

    :return: Dictionary containing extraction result and file path
    """
    print(f"[*] Starting schema extraction for database '{database_name}' (db_id: {db_id})...")
    db_type_normalized = (database_type or "").lower().strip()

    # 1. Create engine and inspector
    engine = _build_target_engine(
        database_type=db_type_normalized,
        host=host,
        port=port,
        username=username,
        password=password,
        database_name=database_name,
        schema_name=schema_name,
        service_name=service_name,
        ssl_mode=ssl_mode,
    )

    inspector = inspect(engine)

    # Determine target schema
    target_schema = schema_name
    if not target_schema:
        if db_type_normalized in ["postgres", "postgresql"]:
            target_schema = "public"
        elif db_type_normalized == "mysql":
            target_schema = database_name

    # 2. Get table names
    try:
        table_names = inspector.get_table_names(schema=target_schema)
    except Exception as e:
        print(f"[!] Falling back to default schema for tables: {e}")
        table_names = inspector.get_table_names()

    tables_summary: List[Dict[str, Any]] = []

    with engine.connect() as conn:
        # Set search path if PostgreSQL
        if db_type_normalized in ["postgres", "postgresql"] and target_schema:
            try:
                conn.execute(text(f'SET search_path TO "{target_schema}", public;'))
            except Exception:
                pass

        for table_name in table_names:
            print(f"  [-] Analyzing table: {table_name}")
            quoted_table = _quote_ident(table_name, db_type_normalized)
            if target_schema and db_type_normalized in ["postgres", "postgresql"]:
                table_qualifier = f'{_quote_ident(target_schema, db_type_normalized)}.{quoted_table}'
            else:
                table_qualifier = quoted_table

            # Total rows in table
            try:
                row_count_res = conn.execute(text(f"SELECT COUNT(*) FROM {table_qualifier};")).scalar()
                total_rows = int(row_count_res) if row_count_res is not None else 0
            except Exception as e:
                print(f"    [!] Error getting row count for {table_name}: {e}")
                total_rows = 0

            # Columns
            try:
                columns = inspector.get_columns(table_name, schema=target_schema)
            except Exception:
                columns = inspector.get_columns(table_name)

            # Primary Key columns
            try:
                pk_constraint = inspector.get_pk_constraint(table_name, schema=target_schema)
                pk_columns: Set[str] = set(pk_constraint.get("constrained_columns", []) or [])
            except Exception:
                pk_columns = set()

            # Foreign Key mappings: col_name -> list of referenced tables
            fk_map: Dict[str, List[str]] = {}
            try:
                fk_constraints = inspector.get_foreign_keys(table_name, schema=target_schema)
                for fk in fk_constraints:
                    referred_tbl = fk.get("referred_table")
                    constrained_cols = fk.get("constrained_columns", [])
                    if referred_tbl and constrained_cols:
                        for col in constrained_cols:
                            fk_map.setdefault(col, []).append(referred_tbl)
            except Exception:
                pass

            column_summaries: List[Dict[str, Any]] = []

            for col in columns:
                col_name = col["name"]
                col_type = str(col["type"])
                quoted_col = _quote_ident(col_name, db_type_normalized)

                is_pk = col_name in pk_columns
                is_fk = col_name in fk_map
                ref_tables = fk_map.get(col_name, [])

                null_pct = 0.0
                unique_pct = 0.0
                distinct_count = 0
                sample_values: List[Any] = []

                if total_rows > 0:
                    # 1. Null count
                    try:
                        null_sql = f"SELECT COUNT(*) FROM {table_qualifier} WHERE {quoted_col} IS NULL;"
                        null_count = conn.execute(text(null_sql)).scalar() or 0
                        null_pct = round((float(null_count) / float(total_rows)) * 100, 2)
                    except Exception as e:
                        null_pct = 0.0

                    # 2. Distinct count
                    try:
                        distinct_sql = f"SELECT COUNT(DISTINCT {quoted_col}) FROM {table_qualifier};"
                        distinct_count = conn.execute(text(distinct_sql)).scalar() or 0
                        unique_pct = round((float(distinct_count) / float(total_rows)) * 100, 2)
                    except Exception:
                        distinct_count = 0
                        unique_pct = 0.0

                    # 3. Sample values (5 non-null sample rows)
                    try:
                        sample_sql = f"SELECT {quoted_col} FROM {table_qualifier} WHERE {quoted_col} IS NOT NULL LIMIT 5;"
                        sample_rows = conn.execute(text(sample_sql)).fetchall()
                        sample_values = [row[0] for row in sample_rows]
                    except Exception as e:
                        sample_values = []

                # 1. Type inspection via SQLAlchemy and type hierarchy
                raw_type = col.get("type")
                type_name = str(raw_type).upper()

                # Temporal check: Date, DateTime, Timestamp, Time, Interval
                is_temporal = (
                    isinstance(raw_type, (Date, DateTime, Time, Interval, TIMESTAMP))
                    or any(t in type_name for t in ("DATE", "TIME", "TIMESTAMP", "INTERVAL"))
                )

                if not is_temporal and sample_values:
                    if any(isinstance(v, (datetime, date, time)) for v in sample_values if v is not None):
                        is_temporal = True

                # Numeric check: strictly non-temporal numeric types
                if is_temporal:
                    is_numeric = False
                else:
                    is_numeric = isinstance(raw_type, (Integer, BigInteger, SmallInteger, Numeric, Float))
                    if sample_values and not is_numeric:
                        try:
                            s_series = pd.Series(sample_values)
                            if not pd.api.types.is_datetime64_any_dtype(s_series):
                                num_series = pd.to_numeric(s_series, errors="coerce")
                                if num_series.notnull().all() and not num_series.empty:
                                    is_numeric = True
                        except Exception:
                            is_numeric = False

                # Temporal classification for time series columns
                temporal_kind = None
                if is_temporal:
                    if isinstance(raw_type, Date) or type_name == "DATE" or ("DATE" in type_name and "TIME" not in type_name):
                        temporal_kind = "date"
                    elif isinstance(raw_type, Time) or type_name == "TIME" or ("TIME" in type_name and "DATE" not in type_name and "TIMESTAMP" not in type_name):
                        temporal_kind = "time"
                    elif isinstance(raw_type, TIMESTAMP) or "TIMESTAMP" in type_name:
                        temporal_kind = "timestamp"
                    elif isinstance(raw_type, DateTime) or "DATETIME" in type_name:
                        temporal_kind = "datetime"
                    else:
                        temporal_kind = "datetime"

                # 2. Dynamic categorical determination:
                # Primary keys or 100% unique identifier columns are not categorical
                is_100_percent_unique = (total_rows > 0 and (unique_pct >= 100.0 or distinct_count >= total_rows))

                if is_pk or is_100_percent_unique:
                    is_cat = False
                elif is_numeric or is_temporal:
                    is_cat = False
                elif sample_values:
                    # Check via Pandas type keywords
                    col_series = pd.to_numeric(pd.Series(sample_values), errors="ignore")
                    is_cat = is_categorical(col_series)
                else:
                    # Fallback for empty tables
                    is_cat = isinstance(raw_type, (String, SQLText, Boolean, SQLEnum))



                # Extract top 5 categories if column is categorical
                categories: List[Any] = []
                if is_cat and total_rows > 0:
                    try:
                        cat_sql = f"SELECT {quoted_col} FROM {table_qualifier} WHERE {quoted_col} IS NOT NULL GROUP BY {quoted_col} ORDER BY COUNT(*) DESC LIMIT 5;"
                        cat_rows = conn.execute(text(cat_sql)).fetchall()
                        categories = [row[0] for row in cat_rows if row[0] is not None]
                    except Exception:
                        try:
                            cat_sql = f"SELECT DISTINCT {quoted_col} FROM {table_qualifier} WHERE {quoted_col} IS NOT NULL LIMIT 5;"
                            cat_rows = conn.execute(text(cat_sql)).fetchall()
                            categories = [row[0] for row in cat_rows if row[0] is not None]
                        except Exception:
                            # Fallback to unique values from sample_values
                            seen = set()
                            categories = []
                            for s in sample_values:
                                if s is not None and s not in seen:
                                    seen.add(s)
                                    categories.append(s)

                # 4. Extract MIN and MAX for numeric and time series (temporal) columns
                min_val = None
                max_val = None
                if (is_numeric or is_temporal) and total_rows > 0:
                    try:
                        min_max_sql = f"SELECT MIN({quoted_col}), MAX({quoted_col}) FROM {table_qualifier} WHERE {quoted_col} IS NOT NULL;"
                        min_max_row = conn.execute(text(min_max_sql)).fetchone()
                        if min_max_row:
                            min_val = min_max_row[0]
                            max_val = min_max_row[1]
                    except Exception:
                        min_val = None
                        max_val = None

                # Build column dictionary
                col_dict: Dict[str, Any] = {
                    "column_name": col_name,
                    "data_type": col_type,
                    "null_percentage": null_pct,
                    "unique_percentage": unique_pct,
                    "is_primary_key": is_pk,
                    "is_foreign_key": is_fk,
                }

                if is_fk and ref_tables:
                    col_dict["reference_tables"] = ref_tables

                col_dict["is_categorical"] = is_cat

                if is_cat:
                    col_dict["distinct_count"] = int(distinct_count)
                    col_dict["categories"] = categories
                else:
                    col_dict["sample_values"] = sample_values

                if is_numeric:
                    col_dict["min_value"] = min_val
                    col_dict["max_value"] = max_val
                elif is_temporal and min_val is not None and max_val is not None:
                    if temporal_kind == "date":
                        col_dict["min_date"] = min_val
                        col_dict["max_date"] = max_val
                    elif temporal_kind == "time":
                        col_dict["min_time"] = min_val
                        col_dict["max_time"] = max_val
                    elif temporal_kind == "timestamp":
                        col_dict["min_timestamp"] = min_val
                        col_dict["max_timestamp"] = max_val
                    elif temporal_kind == "datetime":
                        col_dict["min_datetime"] = min_val
                        col_dict["max_datetime"] = max_val
                    else:
                        col_dict["min_datetime"] = min_val
                        col_dict["max_datetime"] = max_val

                column_summaries.append(col_dict)

            tables_summary.append({
                "table_name": table_name,
                "number_of_rows": total_rows,
                "number_of_columns": len(columns),
                "column_wise_summary": column_summaries,
            })

    # 3. Build final JSON payload
    schema_payload: Dict[str, Any] = {
        "database_id": db_id,
        "database_name": database_name or service_name or "",
        "database_type": database_type,
        "user_id": user_id,
    }

    if schema_name and str(schema_name).strip():
        schema_payload["schema_name"] = schema_name

    if service_name and str(service_name).strip():
        schema_payload["service_name"] = service_name

    schema_payload["tables"] = tables_summary

    # 4. Save to output directory
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_file_path = output_dir / f"{db_id}.json"
    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(schema_payload, f, indent=2, cls=CustomJSONEncoder)

    print(f"[+] Schema extraction completed! Output saved to: {json_file_path}")

    # 5. Insert schema JSON directly into user_databases table
    _insert_schema_db(db_id=db_id, schema_payload=schema_payload)

    return {
        "status": "success",
        "file_path": str(json_file_path),
        "total_tables": len(tables_summary),
        "schema": schema_payload,
    }


def _insert_schema_db(db_id: str, schema_payload: Dict[str, Any]) -> None:
    """
    Inserts or updates the extracted schema JSON into the user_databases table in the application database.
    """
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    app_db_url = os.getenv("DATABASE_URL", "postgresql://root:@localhost:5432/kelostats")
    app_engine = create_engine(app_db_url, pool_pre_ping=True)

    schema_json_str = json.dumps(schema_payload, cls=CustomJSONEncoder)
    now = datetime.utcnow()

    update_sql = text("""
        UPDATE user_databases
        SET schema = :schema_json,
            updated_at = :updated_at
        WHERE db_id = :db_id;
    """)

    try:
        with app_engine.connect() as conn:
            conn.execute(update_sql, {
                "db_id": str(db_id),
                "schema_json": schema_json_str,
                "updated_at": now,
            })
            conn.commit()
            print(f"[+] Schema JSON inserted into 'user_databases' table for db_id: {db_id}")
    except Exception as e:
        print(f"[!] Warning: Could not insert schema JSON into database table: {e}")






 