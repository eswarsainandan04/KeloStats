from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from databases.database import router as database_router
from databases.schema_extraction.schema_input import router as schema_router
from workflow.orchestrator import router as workflow_router

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



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
