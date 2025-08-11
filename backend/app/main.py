"""Main FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import structlog
from pathlib import Path

from app.config import get_settings
from app.db.database import init_db
from app.routers import projects, ingest, query, export, health
from app.utils.logging import setup_logging

# Setup logging
setup_logging()
logger = structlog.get_logger()

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting OpenNotebookLM", version="0.1.0")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    # Ensure required directories exist
    Path("./data").mkdir(exist_ok=True)
    Path("./models").mkdir(exist_ok=True)
    Path("./uploads").mkdir(exist_ok=True)
    
    yield
    
    # Shutdown
    logger.info("Shutting down OpenNotebookLM")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Open-source NotebookLM alternative with RAG capabilities",
    version="0.1.0",
    lifespan=lifespan,
    debug=settings.debug,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(ingest.router, prefix="/api", tags=["ingest"])
app.include_router(query.router, prefix="/api", tags=["query"])
app.include_router(export.router, prefix="/api", tags=["export"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
        "health": "/healthz",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
