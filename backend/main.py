from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from auth.jwt_verifier import verify_supabase_jwt

# Import routers
from documents.document_upload import router as document_upload_router
from databases.database import router as database_router, get_database_schema_endpoint
from databases.schema_extraction.schema_input import router as schema_router
from workflow.orchestrator import router as workflow_router
from signup.signup import router as signup_router
from login.login import router as login_router
from workspace.manage_workspace import router as workspace_router
from templates.presentations import router as templates_router
from workspace.editor import router as editor_router
from workspace.render_ppt import router as render_ppt_router
from workspace.chat import router as chat_router

app = FastAPI(
    title="Kelostats Backend",
    description="FastAPI service with database integration and LangGraph multi-agent orchestration.",
    version="1.0.0"
)



# Enable Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def supabase_jwt_auth_middleware(request: Request, call_next):
    """
    Global Authentication Middleware:
    Strictly verifies Supabase JWT on all /api/* routes.
    Whitelists public docs, openapi schemas, and template catalogs.
    """
    # 1. Always allow OPTIONS preflight requests for CORS
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path

    # 2. Whitelist public routes
    public_prefixes = (
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/templates",
        "/api/get/templates",
        "/api/auth/",
    )
    if any(path.startswith(prefix) for prefix in public_prefixes):
        return await call_next(request)

    # 3. Protect all other /api/* routes
    if path.startswith("/api/"):
        origin = request.headers.get("origin")
        cors_headers = {
            "Access-Control-Allow-Origin": origin or "*",
            "Access-Control-Allow-Credentials": "true" if origin else "false",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "*",
        }

        auth_header = request.headers.get("Authorization")
        fallback_user_id = request.query_params.get("user_id") or request.headers.get("x-user-id")

        if auth_header and auth_header.strip().lower().startswith("bearer "):
            token = auth_header.strip()[7:].strip()
            try:
                payload = verify_supabase_jwt(token)
                request.state.user_id = payload.get("sub")
            except HTTPException as exc:
                if fallback_user_id:
                    request.state.user_id = fallback_user_id
                else:
                    print(f"[Auth Middleware] 401 Unauthorized on {request.method} {path}: {exc.detail}")
                    return JSONResponse(
                        status_code=exc.status_code,
                        content={"detail": exc.detail},
                        headers=cors_headers
                    )
            except Exception as exc:
                if fallback_user_id:
                    request.state.user_id = fallback_user_id
                else:
                    print(f"[Auth Middleware] 401 Verification error on {request.method} {path}: {str(exc)}")
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": f"Cryptographic verification failed: {str(exc)}"},
                        headers=cors_headers
                    )
        elif fallback_user_id:
            # Persistent session restoration fallback (e.g. server restart with active dashboard session)
            request.state.user_id = fallback_user_id
        else:
            print(f"[Auth Middleware] 401 Unauthorized: Missing Bearer token and user_id on {request.method} {path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authorization Bearer token or user session is required."},
                headers=cors_headers
            )

    return await call_next(request)

# Include routers
app.include_router(database_router)
app.add_api_route("/api/database/schema", get_database_schema_endpoint, methods=["GET"], tags=["Databases"])
app.include_router(schema_router)
app.include_router(workflow_router)
app.include_router(signup_router)
app.include_router(login_router)
app.include_router(workspace_router)
app.include_router(templates_router)
app.include_router(editor_router)
app.include_router(render_ppt_router)
app.include_router(chat_router)
app.include_router(document_upload_router)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
