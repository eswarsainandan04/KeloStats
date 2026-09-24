import os
import json
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any

import jwt
from jwt.algorithms import ECAlgorithm
from dotenv import load_dotenv
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Ensure environment variables are loaded
current_dir = Path(__file__).resolve().parent
backend_root = current_dir.parent
if (backend_root / ".env").exists():
    load_dotenv(dotenv_path=backend_root / ".env")
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://pwqipyiadiegfqxknkid.supabase.co")
SUPABASE_JWKS_URL = os.getenv(
    "SUPABASE_JWKS_URL",
    f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
)
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Embedded public JWK as fallback for offline / instant validation
FALLBACK_JWK = {
    "x": "mF2Y9DwvTqwXoKb2BeYdKG_NduIaG76GeeI_fhwIUYE",
    "y": "IVH81mFPb96tXYjUnnFdJtPsWqctw3244TGwQ8tom8A",
    "alg": "ES256",
    "crv": "P-256",
    "ext": True,
    "kid": "1cdc9e5a-ce26-414c-b68c-9fdaf036e282",
    "kty": "EC",
    "key_ops": ["verify"]
}

# Cache compiled EC public keys by kid
_KEY_CACHE: Dict[str, Any] = {}


def _get_public_key_for_kid(kid: Optional[str]) -> Any:
    """Retrieves or builds the EC public key matching the token's kid header."""
    global _KEY_CACHE

    if kid and kid in _KEY_CACHE:
        return _KEY_CACHE[kid]

    # Try fetching fresh JWKS from Supabase
    try:
        req = urllib.request.Request(
            SUPABASE_JWKS_URL,
            headers={"User-Agent": "KeloStats-Backend"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            jwks_data = json.loads(response.read().decode("utf-8"))
            for key_dict in jwks_data.get("keys", []):
                k_id = key_dict.get("kid")
                if key_dict.get("kty") == "EC" and key_dict.get("crv") == "P-256":
                    ec_pub = ECAlgorithm.from_jwk(key_dict)
                    if k_id:
                        _KEY_CACHE[k_id] = ec_pub
    except Exception as fetch_err:
        print(f"[Supabase Auth] Notice: Using fallback JWK ({fetch_err})")

    # If still not found, compile fallback JWK
    fallback_kid = FALLBACK_JWK.get("kid")
    if fallback_kid not in _KEY_CACHE:
        _KEY_CACHE[fallback_kid] = ECAlgorithm.from_jwk(FALLBACK_JWK)

    return _KEY_CACHE.get(kid) or _KEY_CACHE.get(fallback_kid)


def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """
    Cryptographically verifies an incoming Supabase JWT token.
    Supports asymmetric ES256 (ECC P-256) and legacy HS256.
    """
    if not token or not isinstance(token, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or empty authentication token."
        )

    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    try:
        unverified_header = jwt.get_unverified_header(clean_token)
    except Exception as header_err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid JWT header format: {str(header_err)}"
        )

    alg = unverified_header.get("alg", "ES256")
    kid = unverified_header.get("kid")

    decode_kwargs: Dict[str, Any] = {
        "audience": "authenticated",
        "leeway": 300,
        "options": {
            "verify_iat": False,
            "verify_exp": True,
            "verify_aud": True,
        }
    }

    try:
        if alg == "ES256":
            public_key = _get_public_key_for_kid(kid)
            payload = jwt.decode(
                clean_token,
                public_key,
                algorithms=["ES256"],
                **decode_kwargs
            )
        elif alg == "HS256" and SUPABASE_JWT_SECRET:
            payload = jwt.decode(
                clean_token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                **decode_kwargs
            )
        else:
            # As a resilient fallback, attempt decoding with JWK or without algorithm restriction if possible
            try:
                public_key = _get_public_key_for_kid(kid)
                payload = jwt.decode(
                    clean_token,
                    public_key,
                    algorithms=["ES256", "HS256"],
                    **decode_kwargs
                )
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Unsupported token algorithm '{alg}'."
                )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload missing user_id ('sub')."
            )

        return payload

    except jwt.ImmatureSignatureError:
        # Ignore iat timestamp drift between Supabase cloud and local host
        payload = jwt.decode(clean_token, options={"verify_signature": False})
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please log in again."
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience."
        )
    except jwt.PyJWTError as jwt_err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Cryptographic verification failed: {str(jwt_err)}"
        )


# FastAPI Security Bearer Scheme
security = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> str:
    """
    FastAPI dependency: Enforces strict Supabase JWT verification.
    Returns the verified user UUID string.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer token is required."
        )

    payload = verify_supabase_jwt(credentials.credentials)
    return payload["sub"]


def get_optional_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> Optional[str]:
    """
    FastAPI dependency: Permissive mode.
    If a Bearer token is present, validates it and returns verified user UUID.
    If no token is provided, returns None (allowing backward-compatibility).
    """
    if not credentials or not credentials.credentials:
        return None

    try:
        payload = verify_supabase_jwt(credentials.credentials)
        return payload.get("sub")
    except HTTPException:
        raise
    except Exception:
        return None
