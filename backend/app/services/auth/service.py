import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import text

from app.core.auth.security import (
    GenerateTokens,
    hash_password,
    verify_password,
)
from app.services.connectors import app_db_engine as engine


# ==============================================================================
# Domain Services for User Registration, Authentication & Profile Sync
# ==============================================================================

def register_user(
    full_name: str,
    email: str,
    password: str,
    confirm_password: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Registers a new user record in PostgreSQL `users` table:
    - Validates inputs (name, password length, match).
    - Hashes password via bcrypt using app.core.auth.
    - Synchronizes or inserts user with UUID.
    """
    clean_name = (full_name or "").strip()
    clean_email = (email or "").strip().lower()

    if not clean_name:
        raise ValueError("Full name is required.")

    if not clean_email or "@" not in clean_email:
        raise ValueError("A valid email address is required.")

    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    if password != confirm_password:
        raise ValueError("Passwords do not match.")

    # Validate or generate UUID
    provided_user_id = (user_id or "").strip()
    if provided_user_id:
        try:
            target_user_id = str(uuid.UUID(provided_user_id))
        except ValueError:
            raise ValueError("Invalid user_id UUID format.")
    else:
        target_user_id = str(uuid.uuid4())

    hashed_pwd = hash_password(password)
    now = datetime.now(timezone.utc)

    with engine.connect() as conn:
        # Check if user_id already exists (idempotent sync with external auth)
        existing_by_id = conn.execute(
            text("SELECT user_id FROM users WHERE user_id = :user_id LIMIT 1"),
            {"user_id": target_user_id}
        ).fetchone()

        if existing_by_id:
            conn.execute(
                text("""
                    UPDATE users
                    SET full_name = :full_name,
                        email = :email,
                        password = :password,
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                """),
                {
                    "user_id": target_user_id,
                    "full_name": clean_name,
                    "email": clean_email,
                    "password": hashed_pwd,
                    "updated_at": now,
                }
            )
            conn.commit()
            token_generator = GenerateTokens(user_id=str(target_user_id))
            tokens = token_generator.generate_token_pair()
            return {
                "status": "success",
                "message": "User profile synced successfully.",
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "token_type": "bearer",
                "user": {
                    "user_id": target_user_id,
                    "full_name": clean_name,
                    "email": clean_email,
                }
            }

        # Check if email already exists
        existing_by_email = conn.execute(
            text("SELECT user_id FROM users WHERE LOWER(email) = :email LIMIT 1"),
            {"email": clean_email}
        ).fetchone()

        if existing_by_email:
            if not provided_user_id:
                raise KeyError("An account with this email address already exists. Please log in.")

            # Align existing email row with external user_id
            conn.execute(
                text("""
                    UPDATE users
                    SET user_id = :user_id,
                        full_name = :full_name,
                        password = :password,
                        updated_at = :updated_at
                    WHERE LOWER(email) = :email
                """),
                {
                    "user_id": target_user_id,
                    "full_name": clean_name,
                    "email": clean_email,
                    "password": hashed_pwd,
                    "updated_at": now,
                }
            )
            conn.commit()
            token_generator = GenerateTokens(user_id=str(target_user_id))
            tokens = token_generator.generate_token_pair()
            return {
                "status": "success",
                "message": "User registered and synced successfully.",
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "token_type": "bearer",
                "user": {
                    "user_id": target_user_id,
                    "full_name": clean_name,
                    "email": clean_email,
                }
            }

        # Insert new user record
        insert_sql = text("""
            INSERT INTO users (user_id, full_name, email, password, created_at, updated_at)
            VALUES (:user_id, :full_name, :email, :password, :created_at, :updated_at)
        """)
        conn.execute(
            insert_sql,
            {
                "user_id": target_user_id,
                "full_name": clean_name,
                "email": clean_email,
                "password": hashed_pwd,
                "created_at": now,
                "updated_at": now,
            }
        )
        conn.commit()

    token_generator = GenerateTokens(user_id=str(target_user_id))
    tokens = token_generator.generate_token_pair()

    return {
        "status": "success",
        "message": "User registered successfully.",
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": "bearer",
        "user": {
            "user_id": target_user_id,
            "full_name": clean_name,
            "email": clean_email,
        }
    }


def sync_auth_user(
    user_id: str,
    email: str,
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ensures an authenticated user session has a matching record in the PostgreSQL `users` table.
    """
    clean_uid_str = (user_id or "").strip()
    try:
        target_user_id = str(uuid.UUID(clean_uid_str))
    except ValueError:
        raise ValueError("Invalid user_id UUID format.")

    clean_email = (email or "").strip().lower()
    clean_name = (full_name or "").strip() or clean_email.split("@")[0] or "User"
    now = datetime.now(timezone.utc)

    with engine.connect() as conn:
        existing_by_id = conn.execute(
            text("SELECT user_id, full_name FROM users WHERE user_id = :user_id LIMIT 1"),
            {"user_id": target_user_id}
        ).fetchone()

        if existing_by_id:
            if full_name and full_name.strip():
                conn.execute(
                    text("""
                        UPDATE users
                        SET full_name = :full_name,
                            email = :email,
                            updated_at = :updated_at
                        WHERE user_id = :user_id
                    """),
                    {
                        "user_id": target_user_id,
                        "full_name": clean_name,
                        "email": clean_email,
                        "updated_at": now,
                    }
                )
                conn.commit()
            return {
                "status": "success",
                "user": {
                    "user_id": target_user_id,
                    "full_name": clean_name,
                    "email": clean_email,
                }
            }

        existing_by_email = conn.execute(
            text("SELECT user_id FROM users WHERE LOWER(email) = :email LIMIT 1"),
            {"email": clean_email}
        ).fetchone()

        if existing_by_email:
            conn.execute(
                text("""
                    UPDATE users
                    SET user_id = :user_id,
                        full_name = :full_name,
                        updated_at = :updated_at
                    WHERE LOWER(email) = :email
                """),
                {
                    "user_id": target_user_id,
                    "full_name": clean_name,
                    "email": clean_email,
                    "updated_at": now,
                }
            )
            conn.commit()
            return {
                "status": "success",
                "user": {
                    "user_id": target_user_id,
                    "full_name": clean_name,
                    "email": clean_email,
                }
            }

        # Password column is NOT NULL; store a random hash for externally-managed accounts
        placeholder_hash = hash_password(uuid.uuid4().hex)
        conn.execute(
            text("""
                INSERT INTO users (user_id, full_name, email, password, created_at, updated_at)
                VALUES (:user_id, :full_name, :email, :password, :created_at, :updated_at)
            """),
            {
                "user_id": target_user_id,
                "full_name": clean_name,
                "email": clean_email,
                "password": placeholder_hash,
                "created_at": now,
                "updated_at": now,
            }
        )
        conn.commit()

    return {
        "status": "success",
        "user": {
            "user_id": target_user_id,
            "full_name": clean_name,
            "email": clean_email,
        }
    }


def authenticate_user(
    email: str,
    password: str,
) -> Dict[str, Any]:
    """
    Authenticates user credentials against the database:
    - Verifies password with bcrypt.
    - Generates signed JWT access & refresh tokens via app.core.auth.
    - Returns token payload and user profile.
    """
    clean_email = (email or "").strip().lower()

    if not clean_email or not password:
        raise ValueError("Email and password are required.")

    query = text("""
        SELECT user_id, full_name, email, password
        FROM users
        WHERE LOWER(email) = :email
        LIMIT 1
    """)

    with engine.connect() as conn:
        user = conn.execute(query, {"email": clean_email}).fetchone()

    if not user:
        raise PermissionError("Invalid email or password.")

    user_id, full_name, user_email, hashed_password = user

    if not verify_password(password, str(hashed_password)):
        raise PermissionError("Invalid email or password.")

    token_generator = GenerateTokens(user_id=str(user_id))
    tokens = token_generator.generate_token_pair()

    return {
        "status": "success",
        "message": "Login successful.",
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": "bearer",
        "user": {
            "user_id": str(user_id),
            "full_name": full_name,
            "email": user_email,
        }
    }
