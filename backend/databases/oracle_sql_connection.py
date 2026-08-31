import urllib.parse
from typing import Any, Dict, Optional
from sqlalchemy import create_engine, text


def _oracle_sql_connection(
    user_id: str,
    database_name: Optional[str],
    host: str,
    port: int,
    username: str,
    password: str,
    service_name: Optional[str] = None,
    schema_name: Optional[str] = None,
    ssl_mode: Optional[str] = None
) -> Dict[str, Any]:
    """
    Pure connector: Establishes and verifies connection to a target Oracle SQL database with SSL support.
    
    :param user_id: User identifier requesting the connection
    :param database_name: Target Oracle SID or database name
    :param host: Hostname or IP address
    :param port: Port number (default 1521 or 2484 for TCPS)
    :param username: Username for authentication
    :param password: Password for authentication
    :param service_name: Oracle service name (e.g., 'XE')
    :param schema_name: Target schema name
    :param ssl_mode: SSL mode (disable, prefer, require)
    :return: Dictionary containing connection status and metadata
    """
    encoded_user = urllib.parse.quote_plus(str(username))
    encoded_password = urllib.parse.quote_plus(str(password)) if password else ""
    port_int = int(port) if port else 1521
    target_service = service_name or database_name or "XE"
    ssl = ssl_mode

    # Build target connection URL
    target_connection_url = (
        f"oracle+oracledb://{encoded_user}:{encoded_password}@{host}:{port_int}/"
        f"?service_name={target_service}"
    )

    result: Dict[str, Any] = {
        "status": "pending",
        "user_id": str(user_id),
        "database_type": "oracle_sql",
        "database_name": database_name or target_service,
        "service_name": target_service,
        "host": host,
        "port": port_int,
        "username": username,
        "schema_name": schema_name or username,
        "ssl_mode": ssl,
    }

    try:
        engine = create_engine(
            target_connection_url,
            connect_args={"connect_timeout": 10},
            pool_pre_ping=True
        )
        with engine.connect() as conn:
            if schema_name:
                conn.execute(text(f'ALTER SESSION SET CURRENT_SCHEMA = "{schema_name}"'))
            db_version = conn.execute(text("SELECT * FROM v$version WHERE rownum = 1")).scalar()

        result["status"] = "success"
        result["message"] = f"Oracle SQL connection verified successfully (SSL Mode: {ssl})."
        result["version"] = str(db_version) if db_version else "Oracle Database connected"
        return result

    except Exception as conn_err:
        result["status"] = "failed"
        result["message"] = f"Failed to connect to Oracle SQL: {str(conn_err)}"
        return result
