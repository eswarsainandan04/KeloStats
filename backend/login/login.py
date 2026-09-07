import os
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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login", status_code=status.HTTP_200_OK)
def login_user(payload: LoginRequest):
    email = payload.email.strip().lower()
    password = payload.password

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required."
        )

    # 1. Fetch user from database
    query = text("""
        SELECT user_id, full_name, email, password
        FROM users
        WHERE LOWER(email) = :email
        LIMIT 1
    """)

    with engine.connect() as conn:
        user = conn.execute(query, {"email": email}).fetchone()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    user_id, full_name, user_email, hashed_password = user

    # 2. Verify password with bcrypt
    try:
        is_valid = bcrypt.checkpw(
            password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        is_valid = False

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    return {
        "status": "success",
        "message": "Login successful.",
        "user": {
            "user_id": str(user_id),
            "full_name": full_name,
            "email": user_email
        }
    }
