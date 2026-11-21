from typing import Any, Dict, List, Optional
from sqlalchemy import text

from app.core.config import settings
from app.services.connectors import app_db_engine as engine


def save_chat_message(project_id: Optional[str], role: str, message: Optional[str]) -> Optional[str]:
    """
    Persists a chat message in the chat_messages table:
    chat_messages(message_id UUID, project_id VARCHAR FK, role VARCHAR, message TEXT, created_at, updated_at)

    :param project_id: The workspace project ID
    :param role: Message sender role ('User' or 'AI')
    :param message: The text message content
    :return: Generated message_id UUID string if inserted, or None
    """
    if not project_id or not str(project_id).strip():
        return None

    cleaned_msg = str(message or "").strip()
    if not cleaned_msg:
        return None

    clean_project_id = str(project_id).strip()

    try:
        with engine.connect() as conn:
            # Check foreign key existence in workspace table before inserting
            check_sql = text("SELECT 1 FROM workspace WHERE project_id = :p_id LIMIT 1;")
            exists = conn.execute(check_sql, {"p_id": clean_project_id}).fetchone()

            if not exists:
                print(f"[!] [Chat DB] Warning: project_id '{clean_project_id}' does not exist in workspace table. Skipping chat_messages insert.")
                return None

            insert_sql = text("""
                INSERT INTO chat_messages (project_id, role, message, created_at, updated_at)
                VALUES (:project_id, :role, :message, NOW(), NOW())
                RETURNING message_id;
            """)
            result = conn.execute(insert_sql, {
                "project_id": clean_project_id,
                "role": role,
                "message": cleaned_msg
            })
            conn.commit()
            row = result.fetchone()
            msg_id = str(row[0]) if row else None
            print(f"[+] [Chat DB] Persisted {role} message to chat_messages (id: {msg_id}) for project: {clean_project_id}")
            return msg_id
    except Exception as exc:
        print(f"[-] [Chat DB] Error inserting {role} message for project '{clean_project_id}': {exc}")
        return None


def get_chat_history(project_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves all chat messages for the specified project_id ordered chronologically.
    Optionally validates ownership if user_id is provided.
    """
    if not project_id or not str(project_id).strip():
        return []

    clean_project_id = str(project_id).strip()

    try:
        with engine.connect() as conn:
            if user_id:
                check_sql = text("SELECT user_id FROM workspace WHERE project_id = :p_id LIMIT 1;")
                owner = conn.execute(check_sql, {"p_id": clean_project_id}).scalar()
                if owner and str(owner).strip() != str(user_id).strip():
                    print(f"[!] [Chat DB] Access denied: User '{user_id}' does not own workspace '{clean_project_id}'.")
                    return []

            query = text("""
                SELECT message_id, project_id, role, message, created_at, updated_at
                FROM chat_messages
                WHERE project_id = :project_id
                ORDER BY created_at ASC;
            """)
            result = conn.execute(query, {"project_id": clean_project_id}).fetchall()

            messages = []
            for row in result:
                messages.append({
                    "id": str(row.message_id),
                    "project_id": row.project_id,
                    "sender": "user" if str(row.role).lower() == "user" else "ai",
                    "role": row.role,
                    "text": row.message,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "timestamp": row.created_at.strftime("%I:%M %p") if row.created_at else None,
                })
            return messages
    except Exception as exc:
        print(f"[-] [Chat DB] Error retrieving chat history for project '{clean_project_id}': {exc}")
        return []


def get_recent_conversations(
    project_id: str,
    limit_user: int = 5,
    limit_ai: int = 5,
    exclude_last_user_query: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Retrieves the most recent conversation messages from the chat_messages table:
    up to `limit_user` User messages and `limit_ai` AI messages (past 5 recent conversations).
    If the newest message is a User message matching `exclude_last_user_query`, it is skipped
    so the current in-flight query is not treated as past history.

    Returns the messages in chronological order (oldest to newest):
    [{"role": "User", "message": "..."}, {"role": "AI", "message": "..."}]
    """
    if not project_id or not str(project_id).strip():
        return []

    clean_project_id = str(project_id).strip()
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT message_id, role, message, created_at
                FROM chat_messages
                WHERE project_id = :project_id
                ORDER BY created_at DESC
                LIMIT 30;
            """)
            rows = conn.execute(query, {"project_id": clean_project_id}).fetchall()

            if not rows:
                return []

            # If the most recent row matches the current in-flight query, skip it
            start_idx = 0
            if exclude_last_user_query and rows:
                first_role = str(rows[0].role).strip().lower()
                first_msg = str(rows[0].message).strip()
                if first_role == "user" and first_msg == exclude_last_user_query.strip():
                    start_idx = 1

            valid_rows = rows[start_idx:]
            user_count = 0
            ai_count = 0
            selected_rows = []

            for r in valid_rows:
                r_role = str(r.role).strip().lower()
                if r_role == "user":
                    if user_count < limit_user:
                        selected_rows.append(r)
                        user_count += 1
                else:
                    if ai_count < limit_ai:
                        selected_rows.append(r)
                        ai_count += 1

                if user_count >= limit_user and ai_count >= limit_ai:
                    break

            # Reverse to restore chronological order (oldest to newest)
            selected_rows.reverse()

            return [
                {
                    "role": "User" if str(r.role).strip().lower() == "user" else "AI",
                    "message": str(r.message or "").strip()
                }
                for r in selected_rows
                if str(r.message or "").strip()
            ]
    except Exception as exc:
        print(f"[-] [Chat DB] Error retrieving recent conversations for project '{clean_project_id}': {exc}")
        return []
