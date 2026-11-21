from fastapi import APIRouter, Depends

from app.core.auth import get_current_user_id
from app.api.v1.connectors import router as connectors_router
from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.workspace import router as workspace_router
from app.api.v1.slides import router as slides_router
from app.api.v1.editor import router as editor_router
from app.api.v1.templates import router as templates_router
from app.api.v1.auth import router as auth_router

# --------------------------------------------------------------------------
# Protected Router: All mounted endpoints require verified JWT Authentication
# --------------------------------------------------------------------------
protected_router = APIRouter(dependencies=[Depends(get_current_user_id)])

# Mount feature routers
protected_router.include_router(connectors_router)
protected_router.include_router(chat_router)
protected_router.include_router(documents_router)
protected_router.include_router(workspace_router)
protected_router.include_router(slides_router)
protected_router.include_router(editor_router)

# --------------------------------------------------------------------------
# Master API Router: Root /api prefix
# --------------------------------------------------------------------------
api_router = APIRouter(prefix="/api")
api_router.include_router(protected_router)

# Public & Catalog Routers (whitelisted / unauthenticated access)
api_router.include_router(templates_router)
api_router.include_router(auth_router)

__all__ = ["api_router"]
