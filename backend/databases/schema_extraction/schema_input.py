import json
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import create_engine, text

# Load environment variables
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://root:@localhost:5432/kelostats")

# Database engine for retrieving metadata
app_db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Dialect pretty printer
DIALECT_MAP = {
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "oracle": "Oracle SQL",
    "oracle_sql": "Oracle SQL",
    "sqlite": "SQLite",
    "mariadb": "MariaDB",
    "mssql": "SQL Server",
    "sqlserver": "SQL Server",
}


def _format_number(val: Any) -> str:
    """Formats int, float, or Decimal cleanly without unnecessary trailing zeros."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, int):
        return str(val)
    if isinstance(val, (float, Decimal)):
        f_val = float(val)
        if f_val.is_integer():
            return str(int(f_val))
        # Strip trailing zeros for clean presentation (e.g. 5.2, 0.45, 39.75)
        return f"{f_val:.4f}".rstrip("0").rstrip(".")
    return str(val)


def _format_sample_value(sample: Any) -> str:
    """Formats a single sample value for LLM text prompt representation."""
    if sample is None:
        return "null"
    if isinstance(sample, str):
        # Escape internal quotes if needed and wrap in double quotes
        escaped = sample.replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(sample, (datetime, date, time)):
        return f'"{sample.isoformat()}"'
    if isinstance(sample, (int, float, Decimal)):
        return _format_number(sample)
    if isinstance(sample, bool):
        return str(sample)
    return f'"{str(sample)}"'


def json_to_llm_text(schema_data: Dict[str, Any]) -> str:
    """
    Dynamically converts a database schema dictionary (JSON) into a structured LLM text prompt format.
    """
    database_name = schema_data.get("database_name") or schema_data.get("service_name") or "Unknown"
    raw_dialect = schema_data.get("database_type") or ""
    dialect = DIALECT_MAP.get(raw_dialect.lower().strip(), raw_dialect.capitalize() if raw_dialect else "SQL")
    schema_name = schema_data.get("schema_name")

    lines: List[str] = []

    # 1. Header Section
    lines.append("DATABASE SCHEMA")
    lines.append("")
    lines.append(f"Database: {database_name}")
    lines.append(f"Dialect: {dialect}")
    if schema_name:
        lines.append(f"Schema: {schema_name}")
    elif schema_data.get("service_name"):
        lines.append(f"Service: {schema_data.get('service_name')}")

    tables = schema_data.get("tables", [])

    # Pre-calculate primary keys per table to accurately resolve foreign key relationships
    table_pk_map: Dict[str, List[str]] = {}
    for tbl in tables:
        t_name = tbl.get("table_name", "")
        pks = [
            col.get("column_name")
            for col in tbl.get("column_wise_summary", [])
            if col.get("is_primary_key")
        ]
        table_pk_map[t_name] = pks

    relationships: List[str] = []

    # 2. Table Sections
    for tbl in tables:
        t_name = tbl.get("table_name", "")
        row_count = tbl.get("number_of_rows", 0)
        cols = tbl.get("column_wise_summary", [])

        lines.append("")
        lines.append(f"TABLE: {t_name}")
        lines.append(f"Rows: {row_count}")
        lines.append("")
        lines.append("Columns:")

        for col in cols:
            col_name = col.get("column_name", "")
            raw_type = col.get("data_type", "")
            # Normalize type string (e.g. "NUMERIC(12, 2)" -> "NUMERIC(12,2)")
            clean_type = raw_type.replace(", ", ",")

            is_pk = col.get("is_primary_key", False)
            is_fk = col.get("is_foreign_key", False)
            ref_tables = col.get("reference_tables", [])
            is_cat = col.get("is_categorical", False)

            null_pct = col.get("null_percentage", 0.0)
            unique_pct = col.get("unique_percentage", 0.0)
            distinct_cnt = col.get("distinct_count")

            min_val = col.get("min_value")
            max_val = col.get("max_value")
            min_date = col.get("min_date")
            max_date = col.get("max_date")
            min_time = col.get("min_time")
            max_time = col.get("max_time")
            min_ts = col.get("min_timestamp") or col.get("min_datetime")
            max_ts = col.get("max_timestamp") or col.get("max_datetime")
            sample_vals = col.get("sample_values", [])
            cat_vals = col.get("categories", [])

            parts: List[str] = [f"- {col_name}", clean_type]

            # Primary Key
            if is_pk:
                parts.append("PK")

            # Foreign Key
            if is_fk and ref_tables:
                for ref_t in ref_tables:
                    # Find target column in referenced table (PK or matching column name)
                    target_col = col_name
                    ref_pks = table_pk_map.get(ref_t, [])
                    if ref_pks:
                        target_col = ref_pks[0]
                    parts.append(f"FK -> {ref_t}.{target_col}")
                    relationships.append(f"- {t_name}.{col_name} -> {ref_t}.{target_col}")

            # Categorical Flag
            if is_cat:
                parts.append("categorical")

            # Uniqueness & Nullability logic:
            # - If unique == 100% (or PK): show 'not_null' instead of unique%
            # - If unique < 100%: show 'unique: X%' instead of 'not_null'
            is_100_unique = is_pk or (unique_pct is not None and unique_pct >= 100.0)

            if is_100_unique:
                parts.append("not_null")
            elif unique_pct is not None:
                parts.append(f"unique: {_format_number(unique_pct)}%")


            # Distinct Count (for categorical columns)
            if is_cat and distinct_cnt is not None:
                parts.append(f"distinct: {distinct_cnt}")

            # Value Range (for numeric / timeseries range-enabled columns)
            if min_val is not None and max_val is not None:
                parts.append(f"range: {_format_number(min_val)}-{_format_number(max_val)}")
            elif min_date is not None and max_date is not None:
                parts.append(f"range: {_format_sample_value(min_date)}-{_format_sample_value(max_date)}")
            elif min_time is not None and max_time is not None:
                parts.append(f"range: {_format_sample_value(min_time)}-{_format_sample_value(max_time)}")
            elif min_ts is not None and max_ts is not None:
                parts.append(f"range: {_format_sample_value(min_ts)}-{_format_sample_value(max_ts)}")

            # Categories or Sample Values
            if is_cat and cat_vals:
                formatted_cats = [_format_sample_value(c) for c in cat_vals]
                cats_str = ", ".join(formatted_cats)
                if distinct_cnt is not None and distinct_cnt > len(cat_vals):
                    remaining = distinct_cnt - len(cat_vals)
                    cats_str += f",..+{remaining}"
                parts.append(f"categories: {cats_str}")
            elif sample_vals:
                formatted_samples = [_format_sample_value(s) for s in sample_vals]
                parts.append(f"samples: {', '.join(formatted_samples)}")

            lines.append(" | ".join(parts))

    # 3. Relationships Section
    if relationships:
        lines.append("")
        lines.append("")
        lines.append("RELATIONSHIPS:")
        for rel in relationships:
            lines.append(rel)

    return "\n".join(lines).strip() + "\n"


def _fetch_schema_from_db(database_id: str) -> Dict[str, Any]:
    """
    Retrieves the schema JSON from the metadata database (user_databases).
    Falls back to local json file in output/ directory if DB record is not accessible.
    """
    clean_id = str(database_id).strip()
    db_id = clean_id if clean_id.startswith("db_") else f"db_{clean_id}"

    schema_data = None

    # Query schema from user_databases table
    query_sql = text("SELECT schema FROM user_databases WHERE db_id = :db_id LIMIT 1;")

    try:
        with app_db_engine.connect() as conn:
            res = conn.execute(query_sql, {"db_id": db_id}).scalar()
            if res:
                if isinstance(res, str):
                    schema_data = json.loads(res)
                elif isinstance(res, dict):
                    schema_data = res
    except Exception as db_err:
        print(f"[!] Metadata DB query warning: {db_err}")

    # Fallback to schema_extraction/output/{db_id}.json if not found in DB
    if not schema_data:
        json_file = Path(__file__).resolve().parent / "output" / f"{db_id}.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    schema_data = json.load(f)
                if schema_data:
                    print(f"[*] Loaded schema from fallback local file: {json_file}")
            except Exception as file_err:
                print(f"[!] Error reading file {json_file}: {file_err}")

    if not schema_data:
        raise ValueError(
            f"Schema JSON could not be found in metadata database or output directory for database_id '{database_id}'."
        )

    return schema_data


def _schema_to_llm(database_id: str) -> str:
    """
    Main function to retrieve schema JSON for database_id, convert it to formatted
    LLM prompt text, and save the result in schema_extraction/output/db_{uuid}.txt.

    :param database_id: Database ID (e.g. 'db_0be7d5cb-9437-432e-a829-b7eb67233687' or UUID)
    :return: Formatted LLM prompt string
    """
    # 1. Retrieve schema JSON
    schema_json = _fetch_schema_from_db(database_id)

    # 2. Convert JSON schema to LLM prompt text
    llm_prompt_text = json_to_llm_text(schema_json)

    # 3. Determine output file name (e.g. db_{uuid}.txt)
    clean_id = str(database_id).strip()
    normalized_db_id = clean_id if clean_id.startswith("db_") else f"db_{clean_id}"

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    txt_file_path = output_dir / f"{normalized_db_id}.txt"
    with open(txt_file_path, "w", encoding="utf-8") as f:
        f.write(llm_prompt_text)

    print(f"[+] LLM Schema text generated and saved to: {txt_file_path}")
    return llm_prompt_text


# ---------------------------------------------------------------------------
# API Router for POST api/schema_input
# ---------------------------------------------------------------------------
router = APIRouter(tags=["Schema LLM Input"])


class SchemaInputRequest(BaseModel):
    database_id: Optional[str] = None
    db_id: Optional[str] = None


