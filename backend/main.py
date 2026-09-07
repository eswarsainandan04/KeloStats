from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from databases.database import router as database_router
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

# Include routers
app.include_router(database_router)
app.include_router(schema_router)
app.include_router(workflow_router)
app.include_router(signup_router)
app.include_router(login_router)
app.include_router(workspace_router)
app.include_router(templates_router)
app.include_router(editor_router)
app.include_router(render_ppt_router)
app.include_router(chat_router)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
