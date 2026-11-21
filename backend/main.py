from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

# ==============================================================================
# FastAPI Application Initialization
# ==============================================================================
app = FastAPI(
    title="Kelostats API",
    description="Autonomous Multi-Agent AI Analytics, Presentation Generation & Document Intelligence Platform.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ==============================================================================
# Cross-Origin Resource Sharing (CORS) Middleware
# ==============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# Health Check Endpoints
# ==============================================================================
@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
def health_check():
    """Returns the operational status of the service."""
    return {
        "status": "healthy",
        "service": "kelostats-backend",
        "version": "2.0.0",
        "storage_mode": settings.STORAGE_MODE,
    }


# ==============================================================================
# Mount Master API Router
# All feature routers (Auth, Connectors, Chat, Documents, Workspace, Slides,
# Editor, Templates) are unified under /api with native JWT protection.
# ==============================================================================
app.include_router(api_router)


# ==============================================================================
# Server Entrypoint
# ==============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
