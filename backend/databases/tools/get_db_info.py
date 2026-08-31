import os
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
backend_dir = Path(__file__).resolve().parent.parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
app_db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def fetch_database_info(database_id: str) -> Dict[str, Any]:
    """
    Retrieves full connection credentials and database metadata from the user_databases table based on database_id.
    
    :param database_id: The ID of the database (e.g. 'db_4edfa948-...' or '4edfa948-...')
    :return: Dictionary with database_type, host, port, username, password, database_name, schema_name, service_name, ssl_mode
    """
    if not database_id or not str(database_id).strip():
        raise ValueError("database_id is required to fetch database info.")

    clean_id = str(database_id).strip()
    formatted_id = clean_id if clean_id.startswith("db_") else f"db_{clean_id}"

    query = text("""
        SELECT database_type, host, port, username, password,
               database_name, schema_name, service_name, ssl_mode
        FROM user_databases
        WHERE db_id = :db_id OR db_id = :raw_id
        LIMIT 1;
    """)

    with app_db_engine.connect() as conn:
        row = conn.execute(query, {"db_id": formatted_id, "raw_id": clean_id}).fetchone()

    if not row:
        raise ValueError(f"Database with id '{database_id}' not found in user_databases table.")

    data = dict(row._mapping)
    return data
