from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.services.auth import (
    authenticate_user,
    register_user,
    sync_auth_user,
)
from app.core.auth.security import generate_new_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ==============================================================================
# Pydantic Request Models
# ==============================================================================

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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ==============================================================================
# Auth Endpoints
# ==============================================================================

@router.post("/signup", status_code=status.HTTP_201_CREATED, summary="Register a new user account")
def signup_endpoint(payload: SignUpRequest) -> Dict[str, Any]:
    """
    Registers a new user record in the PostgreSQL database.
    Idempotently syncs with external user_id if supplied.
    """
    try:
        result = register_user(
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            confirm_password=payload.confirm_password,
            user_id=payload.user_id,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except KeyError as dup_err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(dup_err).strip("'"),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(exc)}",
        )


@router.post("/sync-user", status_code=status.HTTP_200_OK, summary="Sync external auth user with PostgreSQL")
def sync_user_endpoint(payload: SyncUserRequest) -> Dict[str, Any]:
    """
    Ensures an authenticated user has a corresponding row in the local PostgreSQL users table.
    """
    try:
        result = sync_auth_user(
            user_id=payload.user_id,
            email=payload.email,
            full_name=payload.full_name,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"User sync failed: {str(exc)}",
        )


@router.post("/login", status_code=status.HTTP_200_OK, summary="Authenticate user credentials and issue tokens")
def login_endpoint(payload: LoginRequest) -> Dict[str, Any]:
    """
    Verifies user credentials and returns signed JWT access token and user profile.
    """
    try:
        result = authenticate_user(
            email=payload.email,
            password=payload.password,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except PermissionError as perm_err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(perm_err),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(exc)}",
        )


@router.post("/refresh", status_code=status.HTTP_200_OK, summary="Issue a fresh access token using a refresh token")
def refresh_token_endpoint(payload: RefreshTokenRequest) -> Dict[str, Any]:
    """
    Validates the refresh token and issues a new access token.
    If the refresh token is expired or invalid, raises 401 requiring re-login.
    """
    try:
        new_access_token = generate_new_access_token(refresh_token=payload.refresh_token)
        return {
            "status": "success",
            "message": "Access token refreshed successfully.",
            "access_token": new_access_token,
            "token_type": "bearer",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token refresh failed: {str(exc)}",
        )
