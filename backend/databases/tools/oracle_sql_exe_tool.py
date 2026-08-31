import urllib.parse
from typing import Any, Dict, List
from sqlalchemy import create_engine, text


def execute_oracle_tool(db_info: Dict[str, Any], sql_query: str) -> List[Any]:
    """
    Tool: Executes search SQL on Oracle SQL target database.
    """
    user = urllib.parse.quote_plus(str(db_info.get("username") or ""))
    pwd = urllib.parse.quote_plus(str(db_info.get("password") or ""))
    host = db_info.get("host")
    port = int(db_info.get("port") or 1521)
    target_service = db_info.get("service_name") or db_info.get("database_name") or "XE"
    schema = db_info.get("schema_name")

    conn_url = f"oracle+oracledb://{user}:{pwd}@{host}:{port}/?service_name={target_service}"
    engine = create_engine(conn_url, connect_args={"connect_timeout": 10}, pool_pre_ping=True)
    with engine.connect() as conn:
        if schema:
            conn.execute(text(f'ALTER SESSION SET CURRENT_SCHEMA = "{schema}"'))
        result = conn.execute(text(sql_query))
        rows = [row[0] for row in result.fetchall() if row[0] is not None]
        return rows
