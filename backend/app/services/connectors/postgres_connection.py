import urllib.parse
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, text


def _postgres_connection(
    user_id: str,
    database_name: str,
    host: str,
    port: int,
    username: str,
    password: str,
    schema_name: Optional[str] = None,
    ssl_mode: Optional[str] = None
) -> Dict[str, Any]:
    """
    Pure connector: Establishes and verifies connection to a target PostgreSQL database with SSL mode support.
    
    :param user_id: User identifier requesting the connection
    :param database_name: Target PostgreSQL database name
    :param host: Hostname or IP address
    :param port: Port number (default 5432)
    :param username: Username for authentication
    :param password: Password for authentication
    :param schema_name: Target schema (defaults to 'public')
    :param ssl_mode: SSL mode (optional: disable, allow, prefer, require, verify-ca, verify-full)
    :return: Dictionary containing connection status and metadata
    """
    encoded_user = urllib.parse.quote_plus(str(username))
    encoded_password = urllib.parse.quote_plus(str(password)) if password else ""
    port_int = int(port) if port else 5432
    schema = schema_name
    ssl = ssl_mode

    # Build connection URL
    target_connection_url = f"postgresql+psycopg2://{encoded_user}:{encoded_password}@{host}:{port_int}/{database_name}"
    if ssl:
        target_connection_url += f"?sslmode={ssl}"

    result: Dict[str, Any] = {
        "status": "pending",
        "user_id": str(user_id),
        "database_type": "postgres",
        "database_name": database_name,
        "host": host,
        "port": port_int,
        "username": username,
        "schema_name": schema,
        "ssl_mode": ssl,
    }

    try:
        engine = create_engine(
            target_connection_url,
            connect_args={"connect_timeout": 10},
            pool_pre_ping=True
        )
        with engine.connect() as conn:
            if schema:
                conn.execute(text(f'SET search_path TO "{schema}", public;'))
            db_version = conn.execute(text("SELECT version();")).scalar()

        result["status"] = "success"
        result["message"] = f"PostgreSQL connection verified successfully (SSL Mode: {ssl})."
        result["version"] = str(db_version)
        return result

    except Exception as conn_err:
        result["status"] = "failed"
        result["message"] = f"Failed to connect to PostgreSQL: {str(conn_err)}"
        return result



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
        columns = list(result.keys())
        rows = [{col: val for col, val in zip(columns, row)} for row in result.fetchall()]
        return rows
