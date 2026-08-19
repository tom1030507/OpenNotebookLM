"""API endpoints for cache management."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import structlog

from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.services.cache import cache_service
from app.routers.auth import get_current_user
from app.routers.ownership import require_document, require_project

logger = structlog.get_logger()

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(
    prefix="/api/cache",
    tags=["Cache"],
    dependencies=[Depends(get_current_user)],
)


class CacheStats(BaseModel):
    """Cache statistics response."""
    hits: int
    misses: int
    sets: int
    deletes: int
    backend: str
    total_keys: int
    hit_rate: str
    used_memory: Optional[str] = None
    connected_clients: Optional[int] = None


class CacheHealth(BaseModel):
    """Cache health response."""
    status: str
    backend: str
    error: Optional[str] = None


class CacheClearResponse(BaseModel):
    """Cache clear response."""
    cleared: int
    pattern: Optional[str] = None


class CacheInvalidateResponse(BaseModel):
    """Cache invalidation response."""
    invalidated: int
    target_type: str
    target_id: str


@router.get("/stats", response_model=CacheStats)
async def get_cache_stats():
    """Get cache statistics."""
    try:
        stats = cache_service.get_stats()
        return CacheStats(**stats)
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=CacheHealth)
async def get_cache_health():
    """Check cache health."""
    try:
        health = cache_service.health_check()
        return CacheHealth(**health)
    except Exception as e:
        logger.error(f"Failed to check cache health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clear", response_model=CacheClearResponse)
async def clear_cache(
    pattern: Optional[str] = Query(None, description="Pattern to match keys (e.g., 'query:*')")
):
    """Clear cache entries matching pattern."""
    try:
        count = cache_service.clear(pattern)
        return CacheClearResponse(cleared=count, pattern=pattern)
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/invalidate/project/{project_id}", response_model=CacheInvalidateResponse)
async def invalidate_project_cache(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invalidate the cache entries for one of the caller's projects."""
    # Checked even though this only drops cache entries: the response says how
    # many were invalidated, which would otherwise report on another account's
    # activity, and a 404-vs-200 difference would confirm the id exists.
    require_project(db, project_id, current_user)

    try:
        count = cache_service.invalidate_project_cache(project_id)
        return CacheInvalidateResponse(
            invalidated=count,
            target_type="project",
            target_id=project_id
        )
    except Exception as e:
        logger.error(f"Failed to invalidate project cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/invalidate/document/{document_id}", response_model=CacheInvalidateResponse)
async def invalidate_document_cache(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invalidate the cache entries for one of the caller's documents."""
    require_document(db, document_id, current_user)

    try:
        count = cache_service.invalidate_document_cache(document_id)
        return CacheInvalidateResponse(
            invalidated=count,
            target_type="document",
            target_id=document_id
        )
    except Exception as e:
        logger.error(f"Failed to invalidate document cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/warmup/{project_id}")
async def warmup_cache(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Warm up the cache for one of the caller's projects."""
    require_project(db, project_id, current_user)

    # This is a placeholder for cache warming logic
    # In production, you might want to:
    # 1. Load frequently asked queries
    # 2. Pre-generate embeddings for all documents
    # 3. Cache common search results
    
    return {
        "status": "warming up",
        "project_id": project_id,
        "message": "Cache warming is not yet implemented"
    }
