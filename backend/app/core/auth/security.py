import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt
from fastapi import HTTPException, status

from app.core.config import settings

# --------------------------------------------------------------------------
# Configuration & Expiration Constants
# --------------------------------------------------------------------------
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
if not JWT_SECRET_KEY or JWT_SECRET_KEY == "your-secret-key-change-in-production":
    # Fallback to keep working, but warn in production
    print("[Security Warning] Using default or unconfigured JWT_SECRET_KEY. Please set in .env!")

JWT_ALGORITHM = settings.JWT_ALGORITHM or "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES or 30
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS or 30


# ==============================================================================
# 1. PASSWORD HASHING (BCRYPT)
# ==============================================================================

def hash_password(password: str) -> str:
    """
    Hashes a plaintext password using bcrypt with automatic salt generation.
    Enforces 72-byte max length to protect against bcrypt truncation vulnerabilities.
    """
    if not password:
        raise ValueError("Password cannot be empty.")
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 72:
        raise ValueError("Password cannot exceed 72 bytes.")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plaintext password against a stored bcrypt hash in constant time.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


# ==============================================================================
# 2. TOKEN GENERATION
# ==============================================================================

class GenerateTokens:
    """
    Generates cryptographically signed access and refresh tokens.
    Guarantees user_id is in the payload.
    """

    def __init__(self, user_id: Optional[str] = None):
        self.user_id = str(user_id) if user_id else None

    def generate_access_token(
        self,
        user_id: Optional[str] = None,
        extra_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generates short-lived Access Token (e.g. 30 minutes).
        Payload contains both 'user_id' and standard 'sub'.
        """
        uid = str(user_id or self.user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required to generate access token.")

        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": uid,
            "user_id": uid,
            "type": "access",
            "exp": expire,
            "iat": now,
            "jti": str(uuid.uuid4()),
        }
        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def generate_refresh_token(
        self,
        user_id: Optional[str] = None,
        extra_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generates long-lived Refresh Token (e.g. 30 days).
        Payload contains both 'user_id' and standard 'sub'.
        """
        uid = str(user_id or self.user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required to generate refresh token.")

        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        payload = {
            "sub": uid,
            "user_id": uid,
            "type": "refresh",
            "exp": expire,
            "iat": now,
            "jti": str(uuid.uuid4()),
        }
        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def generate_token_pair(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates both access and refresh tokens at once for login/signup responses.
        """
        uid = str(user_id or self.user_id or "").strip()
        access_tok = self.generate_access_token(uid)
        refresh_tok = self.generate_refresh_token(uid)

        return {
            "access_token": access_tok,
            "refresh_token": refresh_tok,
            "token_type": "Bearer",
            "user_id": uid,
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }


# Convenient standalone aliases matching standard conventions
create_access_token = GenerateTokens().generate_access_token
create_refresh_token = GenerateTokens().generate_refresh_token


# ==============================================================================
# 3. REFRESH LOGIC
# ==============================================================================

def generate_new_access_token(user_id: Optional[str] = None, refresh_token: str = "") -> str:
    """
    Validates the refresh token and issues a fresh new access token.
    If user_id is omitted, it is securely derived from the token's subject/user_id claim.
    If the refresh token is expired, raises an HTTP 401 error requiring re-login.
    """
    if not refresh_token or not refresh_token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token. Please navigate to login.",
        )

    clean_token = refresh_token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    try:
        payload = jwt.decode(clean_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        # Strictly verify token type
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Expected a refresh token.",
            )

        token_user_id = payload.get("user_id") or payload.get("sub")
        if not token_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token payload: missing user_id.",
            )

        if user_id and str(token_user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token subject does not match user_id.",
            )

        # Issue fresh new access token
        token_gen = GenerateTokens(token_user_id)
        return token_gen.generate_access_token()

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session ended: Refresh token has expired. Please navigate to login.",
        )
    except jwt.PyJWTError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid refresh token: {str(err)}. Please navigate to login.",
        )


# ==============================================================================
# 4. VERIFY TOKENS
# ==============================================================================

class VerifyTokens:
    """
    Cryptographic verification helpers for access and refresh tokens.
    """

    @staticmethod
    def decode_token(token: str) -> Dict[str, Any]:
        """Decodes token and verifies its cryptographic signature."""
        if not token or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token.",
            )

        clean_token = token.strip()
        if clean_token.lower().startswith("bearer "):
            clean_token = clean_token[7:].strip()

        try:
            return jwt.decode(clean_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
            )
        except jwt.PyJWTError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(err)}",
            )

    @staticmethod
    def verify_token(
        access_token: str,
        refresh_token: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete verification flow:
        1. Checks access_token.
        2. If access_token is valid -> returns status 'valid' and user_id.
        3. If access_token is expired/invalid and refresh_token is provided:
           - Automatically calls generate_new_access_token()
           - If refresh_token also expired -> raises 401 with navigate to login instruction.
        """
        try:
            clean_access = access_token.strip()
            if clean_access.lower().startswith("bearer "):
                clean_access = clean_access[7:].strip()

            payload = jwt.decode(clean_access, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

            # Ensure it is an access token, not a refresh token used as access
            if payload.get("type") != "access":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type: expected access token.",
                )

            uid = payload.get("user_id") or payload.get("sub")
            return {
                "status": "valid",
                "user_id": uid,
                "payload": payload,
                "new_access_token": None,
            }

        except (jwt.ExpiredSignatureError, jwt.PyJWTError):
            # Access token is expired or invalid
            if refresh_token:
                # Try issuing a fresh access token using the refresh token
                new_token = generate_new_access_token(user_id=user_id, refresh_token=refresh_token)
                resolved_uid = user_id
                if not resolved_uid:
                    # Extract from refresh token payload
                    try:
                        clean_refresh = refresh_token.strip()
                        if clean_refresh.lower().startswith("bearer "):
                            clean_refresh = clean_refresh[7:].strip()
                        r_payload = jwt.decode(clean_refresh, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
                        resolved_uid = r_payload.get("user_id") or r_payload.get("sub")
                    except Exception:
                        pass

                return {
                    "status": "refreshed",
                    "user_id": resolved_uid,
                    "new_access_token": new_token,
                }

            # If no refresh token provided, raise standard 401
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token expired. Please refresh token or navigate to login.",
            )
