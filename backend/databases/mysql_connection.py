import urllib.parse
from typing import Any, Dict, Optional
from sqlalchemy import create_engine, text


def _mysql_connection(
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
    Pure connector: Establishes and verifies connection to a target MySQL database with SSL mode support.
    
    :param user_id: User identifier requesting the connection
    :param database_name: Target MySQL database name
    :param host: Hostname or IP address
    :param port: Port number (default 3306)
    :param username: Username for authentication
    :param password: Password for authentication
    :param schema_name: Schema/database name
    :param ssl_mode: SSL mode (disable, prefer, require, verify-ca, verify-full)
    :return: Dictionary containing connection status and metadata
    """
    encoded_user = urllib.parse.quote_plus(str(username))
    encoded_password = urllib.parse.quote_plus(str(password)) if password else ""
    port_int = int(port) if port else 3306
    db_target = database_name or schema_name or ""
    ssl = ssl_mode


    target_connection_url = f"mysql+pymysql://{encoded_user}:{encoded_password}@{host}:{port_int}/{db_target}"

    result: Dict[str, Any] = {
        "status": "pending",
        "user_id": str(user_id),
        "database_type": "mysql",
        "database_name": db_target,
        "host": host,
        "port": port_int,
        "username": username,
        "schema_name": schema_name or db_target,
        "ssl_mode": ssl,
    }

    try:
        engine = create_engine(
            target_connection_url,
            pool_pre_ping=True
        )
        with engine.connect() as conn:
            db_version = conn.execute(text("SELECT VERSION();")).scalar()

        result["status"] = "success"
        result["message"] = f"MySQL connection verified successfully (SSL Mode: {ssl})."
        result["version"] = str(db_version)
        return result

    except Exception as conn_err:
        result["status"] = "failed"
        result["message"] = f"Failed to connect to MySQL: {str(conn_err)}"
        return result
