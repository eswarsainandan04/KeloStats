import os
import uuid
from datetime import datetime
from pathlib import Path
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
    full_name: str
    email: EmailStr
    password: str
    confirm_password: str


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

    # 2. Check if user already exists
    check_sql = text("SELECT user_id FROM users WHERE LOWER(email) = :email LIMIT 1")

    with engine.connect() as conn:
        existing = conn.execute(check_sql, {"email": email}).fetchone()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email address already exists. Please log in."
            )

        # 3. Hash password
        hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        new_user_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # 4. Insert into database
        insert_sql = text("""
            INSERT INTO users (user_id, full_name, email, password, created_at, updated_at)
            VALUES (:user_id, :full_name, :email, :password, :created_at, :updated_at)
        """)

        conn.execute(
            insert_sql,
            {
                "user_id": new_user_id,
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
            "user_id": new_user_id,
            "full_name": full_name,
            "email": email
        }
    }
