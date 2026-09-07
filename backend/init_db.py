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

# Users table DDL
CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

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
    display_name VARCHAR(255),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Templates table DDL
CREATE_TEMPLATES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS templates (
    template_id VARCHAR(255) PRIMARY KEY,
    template_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Workspace table DDL
CREATE_WORKSPACE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workspace (
    project_id VARCHAR(255) PRIMARY KEY,
    project_name VARCHAR(255) NOT NULL,
    user_id UUID NOT NULL,
    database_id VARCHAR(255) NOT NULL,
    template_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Chat messages table DDL
CREATE_CHAT_MESSAGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id VARCHAR(255) NOT NULL REFERENCES workspace(project_id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_project_id ON chat_messages(project_id);
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
            conn.execute(text(CREATE_USERS_TABLE_SQL))
            conn.execute(text(CREATE_TABLE_SQL))
            conn.execute(text(CREATE_TEMPLATES_TABLE_SQL))
            conn.execute(text(CREATE_WORKSPACE_TABLE_SQL))
            conn.execute(text(CREATE_CHAT_MESSAGES_TABLE_SQL))
            conn.commit()
            print("[+] Table 'users' created/verified successfully!")
            print("[+] Table 'user_databases' created/verified successfully with 'schema JSONB' column!")
            print("[+] Table 'templates' created/verified successfully!")
            print("[+] Table 'workspace' created/verified successfully!")
            print("[+] Table 'chat_messages' created/verified successfully!")
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
