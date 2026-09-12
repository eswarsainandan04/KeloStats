import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import create_engine, text

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
if (current_dir.parent / ".env").exists():
    load_dotenv(dotenv_path=current_dir.parent / ".env")
elif (current_dir / ".env").exists():
    load_dotenv(dotenv_path=current_dir / ".env")
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

router = APIRouter(prefix="/api/workspace/chat", tags=["Workspace Chat"])


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


def get_chat_history(project_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all chat messages for the specified project_id ordered chronologically.
    """
    if not project_id:
        return []

    try:
        with engine.connect() as conn:
            query = text("""
                SELECT message_id, project_id, role, message, created_at, updated_at
                FROM chat_messages
                WHERE project_id = :project_id
                ORDER BY created_at ASC;
            """)
            result = conn.execute(query, {"project_id": project_id}).fetchall()

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
        print(f"[-] [Chat DB] Error retrieving chat history for project '{project_id}': {exc}")
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



@router.get("/{project_id}", summary="Get chat messages history for a project")
def get_chat_messages_endpoint(project_id: str):
    """
    Returns chronological chat history for a workspace project.
    """
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id is required."
        )

    messages = get_chat_history(project_id)
    return {
        "status": "success",
        "project_id": project_id,
        "count": len(messages),
        "messages": messages
    }
