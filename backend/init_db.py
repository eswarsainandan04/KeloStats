import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Locate and load .env file from current file directory or parent directory
current_dir = Path(__file__).resolve().parent
if (current_dir / ".env").exists():
    load_dotenv(dotenv_path=current_dir / ".env")
elif (current_dir.parent / ".env").exists():
    load_dotenv(dotenv_path=current_dir.parent / ".env")
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://root:@localhost:5432/kelostats")

# Clean table schema DDL with schema JSONB column
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_databases (
    db_id VARCHAR(255) PRIMARY KEY,
    user_id UUID NOT NULL,

    database_type VARCHAR(50) NOT NULL,
    database_name VARCHAR(255),

    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL,

    username VARCHAR(255) NOT NULL,
    password TEXT NOT NULL,

    schema_name VARCHAR(255),
    service_name VARCHAR(255),
    ssl_mode VARCHAR(50) DEFAULT 'prefer',
    schema JSONB,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_url: str = None) -> bool:
    """
    Creates tables if they do not exist in the database.
    """
    target_url = db_url or DATABASE_URL
    print(f"[*] Connecting to database using URL: {target_url.split('@')[-1] if '@' in target_url else target_url}")

    try:
        engine = create_engine(target_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text(CREATE_TABLE_SQL))
            conn.commit()
            print("[+] Table 'user_databases' created/verified successfully with 'schema JSONB' column!")
        return True
    except Exception as e:
        print(f"[-] Error creating tables: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    print("========================================")
    print("  Initializing Kelostats Database Table ")
    print("========================================")
    success = init_db()
    if success:
        print("[SUCCESS] Database initialization completed.")
    else:
        print("[FAILED] Could not complete database initialization.")
