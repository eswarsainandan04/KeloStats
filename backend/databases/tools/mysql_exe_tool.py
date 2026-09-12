import urllib.parse
from typing import Any, Dict, List
from sqlalchemy import create_engine, text


def execute_mysql_tool(db_info: Dict[str, Any], sql_query: str) -> List[Any]:
    """
    Tool: Executes search SQL on MySQL target database.
    """
    user = urllib.parse.quote_plus(str(db_info.get("username") or ""))
    pwd = urllib.parse.quote_plus(str(db_info.get("password") or ""))
    host = db_info.get("host")
    port = int(db_info.get("port") or 3306)
    db_target = db_info.get("database_name") or db_info.get("schema_name") or ""

    conn_url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db_target}"
    engine = create_engine(conn_url, pool_pre_ping=True)
    with engine.connect() as conn:
        result = conn.execute(text(sql_query))
        columns = list(result.keys())
        rows = [{col: val for col, val in zip(columns, row)} for row in result.fetchall()]
        return rows
