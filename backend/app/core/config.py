import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Resolve paths
# config.py is at: backend/app/core/config.py
# backend_root is: backend/
CURRENT_DIR = Path(__file__).resolve().parent
APP_DIR = CURRENT_DIR.parent
BACKEND_ROOT = APP_DIR.parent

# Load .env file from backend root or system environment
ENV_FILE = BACKEND_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()


class Settings:
    """
    Centralized production configuration loaded from environment variables and .env.
    """

    # --------------------------------------------------------------------------
    # Storage Configuration
    # --------------------------------------------------------------------------
    # STORAGE_MODE can be explicitly set to 'local' or 'cloud' in .env.
    # If not set, defaults to 'cloud' when S3 credentials exist, otherwise 'local'.
    _raw_storage_mode = os.getenv("STORAGE_MODE", "").strip().lower()
    if _raw_storage_mode in ("local", "cloud"):
        STORAGE_MODE: str = _raw_storage_mode
    elif os.getenv("S3_ACCESS_KEY_ID") and os.getenv("S3_ENDPOINT_URL"):
        STORAGE_MODE: str = "cloud"
    else:
        STORAGE_MODE: str = "local"

    # Directory for local file storage (backend/storage/)
    LOCAL_STORAGE_DIR: Path = BACKEND_ROOT / "storage"

    # Universal Cloud Object Storage (S3 / MinIO / Cloudflare R2 / Object Storage)
    S3_ENDPOINT_URL: Optional[str] = os.getenv("S3_ENDPOINT_URL")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    S3_ACCESS_KEY_ID: Optional[str] = os.getenv("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY: Optional[str] = os.getenv("S3_SECRET_ACCESS_KEY")
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "storage")

    # --------------------------------------------------------------------------
    # Database Configuration
    # --------------------------------------------------------------------------
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/kelostats"
    )

    # --------------------------------------------------------------------------
    # Authentication & JWT Configuration
    # --------------------------------------------------------------------------
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

    # --------------------------------------------------------------------------
    # LLM & AI Configuration
    # --------------------------------------------------------------------------
    LLM_BASE_URL: Optional[str] = os.getenv("LLM_BASE_URL")
    LLM_MODEL: Optional[str] = os.getenv("LLM_MODEL")
    LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY")

    PPT_GENERATION_LLM_BASE_URL: Optional[str] = os.getenv("PPT_GENERATION_LLM_BASE_URL")
    PPT_GENERATION_LLM_MODEL: Optional[str] = os.getenv("PPT_GENERATION_LLM_MODEL")
    PPT_GENERATION_LLM_API_KEY: Optional[str] = os.getenv("PPT_GENERATION_LLM_API_KEY")

    PLANNING_LLM_BASE_URL: Optional[str] = os.getenv("PLANNING_LLM_BASE_URL")
    PLANNING_LLM_MODEL: Optional[str] = os.getenv("PLANNING_LLM_MODEL")
    PLANNING_LLM_API_KEY: Optional[str] = os.getenv("PLANNING_LLM_API_KEY")

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")


# Global singleton instance
settings = Settings()
