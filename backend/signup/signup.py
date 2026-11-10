import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
import bcrypt
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, text

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://root:@localhost:5432/kelostats")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class SignUpRequest(BaseModel):
    user_id: Optional[str] = None
    full_name: str
    email: EmailStr
    password: str
    confirm_password: str


class SyncUserRequest(BaseModel):
    user_id: str
    email: EmailStr
    full_name: Optional[str] = None


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup_user(payload: SignUpRequest):
    full_name = payload.full_name.strip()
    email = payload.email.strip().lower()
    password = payload.password
    confirm_password = payload.confirm_password

    # 1. Validation
    if not full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name is required."
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long."
        )

    if password != confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match."
        )

    # Use Supabase Auth user_id if provided, otherwise generate a new UUID
    provided_user_id = (payload.user_id or "").strip()
    if provided_user_id:
        try:
            target_user_id = str(uuid.UUID(provided_user_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid user_id UUID format."
            )
    else:
        target_user_id = str(uuid.uuid4())

    # 2. Hash password
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    now = datetime.utcnow()

    with engine.connect() as conn:
        # 3a. Check if user_id already exists in users table (idempotent sync with Supabase Auth)
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
                    "full_name": full_name,
                    "email": email,
                    "password": hashed_password,
                    "updated_at": now,
                }
            )
            conn.commit()
            return {
                "status": "success",
                "message": "User profile synced successfully.",
                "user": {
                    "user_id": target_user_id,
                    "full_name": full_name,
                    "email": email
                }
            }

        # 3b. Check if email already exists
        existing_by_email = conn.execute(
            text("SELECT user_id FROM users WHERE LOWER(email) = :email LIMIT 1"),
            {"email": email}
        ).fetchone()

        if existing_by_email:
            if not provided_user_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email address already exists. Please log in."
                )
            # Align existing email row with Supabase Auth user_id
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
                    "full_name": full_name,
                    "email": email,
                    "password": hashed_password,
                    "updated_at": now,
                }
            )
            conn.commit()
            return {
                "status": "success",
                "message": "User registered and synced successfully.",
                "user": {
                    "user_id": target_user_id,
                    "full_name": full_name,
                    "email": email
                }
            }

        # 4. Insert into users table
        insert_sql = text("""
            INSERT INTO users (user_id, full_name, email, password, created_at, updated_at)
            VALUES (:user_id, :full_name, :email, :password, :created_at, :updated_at)
        """)

        conn.execute(
            insert_sql,
            {
                "user_id": target_user_id,
                "full_name": full_name,
                "email": email,
                "password": hashed_password,
                "created_at": now,
                "updated_at": now
            }
        )
        conn.commit()

    return {
        "status": "success",
        "message": "User registered successfully.",
        "user": {
            "user_id": target_user_id,
            "full_name": full_name,
            "email": email
        }
    }


@router.post("/sync-user", status_code=status.HTTP_200_OK)
def sync_auth_user(payload: SyncUserRequest):
    """
    Ensures a Supabase Auth user has a matching record in the PostgreSQL `users` table.
    """
    try:
        target_user_id = str(uuid.UUID(payload.user_id.strip()))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user_id UUID format."
        )

    email = payload.email.strip().lower()
    full_name = (payload.full_name or "").strip() or email.split("@")[0] or "User"
    now = datetime.utcnow()

    with engine.connect() as conn:
        existing_by_id = conn.execute(
            text("SELECT user_id, full_name FROM users WHERE user_id = :user_id LIMIT 1"),
            {"user_id": target_user_id}
        ).fetchone()

        if existing_by_id:
            if payload.full_name and payload.full_name.strip():
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
                        "full_name": full_name,
                        "email": email,
                        "updated_at": now,
                    }
                )
                conn.commit()
            return {
                "status": "success",
                "user": {
                    "user_id": target_user_id,
                    "full_name": full_name,
                    "email": email
                }
            }

        existing_by_email = conn.execute(
            text("SELECT user_id FROM users WHERE LOWER(email) = :email LIMIT 1"),
            {"email": email}
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
                    "full_name": full_name,
                    "email": email,
                    "updated_at": now,
                }
            )
            conn.commit()
            return {
                "status": "success",
                "user": {
                    "user_id": target_user_id,
                    "full_name": full_name,
                    "email": email
                }
            }

        # Password column is NOT NULL; store a random bcrypt hash for Supabase-managed accounts
        placeholder_hash = bcrypt.hashpw(uuid.uuid4().hex.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        conn.execute(
            text("""
                INSERT INTO users (user_id, full_name, email, password, created_at, updated_at)
                VALUES (:user_id, :full_name, :email, :password, :created_at, :updated_at)
            """),
            {
                "user_id": target_user_id,
                "full_name": full_name,
                "email": email,
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
            "full_name": full_name,
            "email": email
        }
    }
