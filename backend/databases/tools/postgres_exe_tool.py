import urllib.parse
from typing import Any, Dict, List
from sqlalchemy import create_engine, text


def execute_postgres_tool(db_info: Dict[str, Any], sql_query: str) -> List[Any]:
    """
    Tool: Executes search SQL on PostgreSQL target database.
    """
    user = urllib.parse.quote_plus(str(db_info.get("username") or ""))
    pwd = urllib.parse.quote_plus(str(db_info.get("password") or ""))
    host = db_info.get("host")
    port = int(db_info.get("port") or 5432)
    db_name = db_info.get("database_name") or ""
    schema = db_info.get("schema_name") or "public"
    ssl = db_info.get("ssl_mode")

    conn_url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db_name}"
    if ssl:
        conn_url += f"?sslmode={ssl}"

    engine = create_engine(conn_url, pool_pre_ping=True)
    with engine.connect() as conn:
        if schema:
            conn.execute(text(f'SET search_path TO "{schema}", public;'))
        result = conn.execute(text(sql_query))
        rows = [row[0] for row in result.fetchall() if row[0] is not None]
        return rows
