import os
import re
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Load database configuration from backend/.env
env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
CSV_PATH = Path(__file__).resolve().parent / "Global_Superstore2.csv"
SCHEMA_NAME = "store"
TABLE_NAME = "global_superstore"


def clean_column_name(col: str) -> str:
    """Converts column names to clean snake_case."""
    col = col.strip().replace("-", "_").replace(" ", "_")
    col = re.sub(r"[^\w\s_]", "", col)
    return col.lower()


def parse_date_safe(val):
    """Parses date string into YYYY-MM-DD format."""
    if pd.isna(val) or not str(val).strip():
        return None
    try:
        dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
        if pd.notna(dt):
            return dt.date()
        dt = pd.to_datetime(val, errors="coerce")
        if pd.notna(dt):
            return dt.date()
    except Exception:
        pass
    return None


def push_global_superstore():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV file not found at: {CSV_PATH}")

    print(f"[*] Reading CSV file: {CSV_PATH}...")
    # Attempt reading with utf-8 / latin-1 / cp1252 encodings
    try:
        df = pd.read_csv(CSV_PATH, encoding="utf-8")
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(CSV_PATH, encoding="latin-1")
        except Exception:
            df = pd.read_csv(CSV_PATH, encoding="cp1252")

    print(f"[+] Loaded {len(df)} rows and {len(df.columns)} columns from CSV.")

    # Clean column names
    df.columns = [clean_column_name(c) for c in df.columns]
    print(f"[*] Cleaned columns: {list(df.columns)}")

    # Parse date columns if present
    date_cols = [c for c in df.columns if "date" in c]
    for dc in date_cols:
        print(f"[*] Parsing date column: {dc}...")
        df[dc] = pd.to_datetime(df[dc], dayfirst=True, errors="coerce").dt.date

    # Clean numeric columns (sales, profit, shipping_cost, discount, quantity)
    numeric_cols = ["sales", "profit", "shipping_cost", "discount", "quantity"]
    for nc in numeric_cols:
        if nc in df.columns:
            if df[nc].dtype == object:
                df[nc] = (
                    df[nc]
                    .astype(str)
                    .str.replace("$", "", regex=False)
                    .str.replace(",", "", regex=False)
                    .str.strip()
                )
                df[nc] = pd.to_numeric(df[nc], errors="coerce")

    # Connect to PostgreSQL
    print(f"[*] Connecting to database at: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}...")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.connect() as conn:
        # Create schema if not exists
        print(f"[*] Ensuring schema '{SCHEMA_NAME}' exists...")
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_NAME}";'))
        conn.commit()

        # Drop existing table if user wants clean reload
        conn.execute(text(f'DROP TABLE IF EXISTS "{SCHEMA_NAME}"."{TABLE_NAME}" CASCADE;'))
        conn.commit()

    # DDL with optimized types
    create_table_ddl = f"""
    CREATE TABLE "{SCHEMA_NAME}"."{TABLE_NAME}" (
        row_id INTEGER PRIMARY KEY,
        order_id VARCHAR(100),
        order_date DATE,
        ship_date DATE,
        ship_mode VARCHAR(50),
        customer_id VARCHAR(50),
        customer_name VARCHAR(255),
        segment VARCHAR(50),
        city VARCHAR(150),
        state VARCHAR(150),
        country VARCHAR(150),
        postal_code VARCHAR(50),
        market VARCHAR(50),
        region VARCHAR(100),
        product_id VARCHAR(100),
        category VARCHAR(100),
        sub_category VARCHAR(100),
        product_name TEXT,
        sales NUMERIC(12, 4),
        quantity INTEGER,
        discount NUMERIC(6, 4),
        profit NUMERIC(12, 4),
        shipping_cost NUMERIC(12, 4),
        order_priority VARCHAR(50)
    );
    """

    with engine.connect() as conn:
        print(f"[*] Creating table '{SCHEMA_NAME}.{TABLE_NAME}'...")
        conn.execute(text(create_table_ddl))
        conn.commit()
        print(f"[+] Table '{SCHEMA_NAME}.{TABLE_NAME}' created successfully.")

    # High performance bulk write
    print(f"[*] Inserting {len(df)} rows into '{SCHEMA_NAME}.{TABLE_NAME}' in batches...")
    df.to_sql(
        name=TABLE_NAME,
        con=engine,
        schema=SCHEMA_NAME,
        if_exists="append",
        index=False,
        chunksize=2000,
        method="multi"
    )

    # Verification
    with engine.connect() as conn:
        row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{SCHEMA_NAME}"."{TABLE_NAME}";')).scalar()
        sample = conn.execute(text(f'SELECT * FROM "{SCHEMA_NAME}"."{TABLE_NAME}" LIMIT 3;')).fetchall()
        print(f"\n[SUCCESS] Successfully pushed {row_count} rows into {SCHEMA_NAME}.{TABLE_NAME}!")
        print("[*] Sample 3 records inserted:")
        for r in sample:
            print("   ", r)


if __name__ == "__main__":
    push_global_superstore()
