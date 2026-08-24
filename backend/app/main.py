"""Main FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.lifecycle import lifespan
from app.routers import (
    auth, projects, ingest, query, export, health, files, mindmap, video
)
from app.api import cache
from app.utils.logging import setup_logging
from app.middleware.upload_body_limit import UploadBodyLimitMiddleware

# Setup logging
setup_logging()

settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Open-source NotebookLM alternative with RAG capabilities",
    version="0.1.0",
    lifespan=lifespan,
    debug=settings.debug,
)

# Starlette makes the most recently added middleware outermost. The upload
# guard must remain ahead of routing/form parsing, while CORS must wrap its
# direct 413 so browser clients are allowed to read the stable error response.
app.add_middleware(
    UploadBodyLimitMiddleware,
    max_file_size_bytes=settings.max_file_size_bytes,
    configured_limit_mb=settings.max_file_size_mb,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/api", tags=["authentication"])
app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(ingest.router, prefix="/api", tags=["ingest"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(query.router, prefix="/api", tags=["query"])
app.include_router(export.router, prefix="/api", tags=["export"])
app.include_router(mindmap.router, prefix="/api", tags=["mindmap"])
app.include_router(video.router, prefix="/api", tags=["video summary"])
app.include_router(cache.router)  # Cache management endpoints


@app.get("/")
async def root():
    """Describe the running service and its discovery endpoints.

    Args:
        None.

    Returns:
        Basic application metadata and health endpoint locations.
    """
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
        "health": "/healthz",
        "readiness": "/readyz",
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
