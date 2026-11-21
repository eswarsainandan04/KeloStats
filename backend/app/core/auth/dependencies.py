from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import VerifyTokens, generate_new_access_token

# HTTP Bearer scheme (auto_error=False allows graceful error formatting and custom header inspection)
bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> Optional[str]:
    """
    Extracts Bearer token from:
    1. Standard 'Authorization: Bearer <token>' header
    2. 'x-access-token' custom header
    """
    if credentials and credentials.credentials:
        return credentials.credentials.strip()

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.strip().lower().startswith("bearer "):
        return auth_header.strip()[7:].strip()

    custom_header = request.headers.get("x-access-token")
    if custom_header:
        return custom_header.strip()

    return None


def get_current_user_id(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """
    FastAPI Route Dependency (Protected Route Guard):
    - Cryptographically verifies the Access Token from the Authorization header.
    - Validates token expiration and token type ('access').
    - Returns the verified 'user_id' as a string.
    - Raises HTTP 401 Unauthorized if token is missing, expired, or invalid.

    Usage in any router:
        @router.post("/slides")
        def create_slide(user_id: str = Depends(get_current_user_id)):
            ...
    """
    token = _extract_token_from_request(request, credentials)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Missing Bearer token in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode and cryptographically verify
    payload = VerifyTokens.decode_token(token)

    # Strictly enforce token type
    token_type = payload.get("type")
    if token_type and token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: Expected an access token, but received a refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: user_id claim not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Attach to request state for downstream middleware compatibility
    request.state.user_id = str(user_id)
    return str(user_id)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """
    FastAPI Route Dependency:
    - Returns the full decoded JWT payload dictionary:
      {'user_id': '...', 'sub': '...', 'type': 'access', 'exp': ..., 'iat': ...}
    """
    token = _extract_token_from_request(request, credentials)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = VerifyTokens.decode_token(token)

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: Expected access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user_id identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.user_id = str(user_id)
    return payload


def get_optional_user_id(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[str]:
    """
    Optional Route Dependency:
    - If a valid token is provided, returns user_id.
    - If no token or invalid token, returns None without raising an HTTPException.
    - Ideal for public endpoints that have personalized views for logged-in users.
    """
    token = _extract_token_from_request(request, credentials)
    if not token:
        return None

    try:
        payload = VerifyTokens.decode_token(token)
        if payload.get("type") == "access":
            uid = payload.get("user_id") or payload.get("sub")
            if uid:
                request.state.user_id = str(uid)
                return str(uid)
    except Exception:
        pass

    return None
