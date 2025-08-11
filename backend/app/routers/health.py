"""Health check router."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import os
import psutil

from app.db.database import get_db
from app.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/healthz")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Check database connection
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    # Get system metrics
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    
    return {
        "ok": db_status == "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
        "environment": settings.app_env,
        "database": db_status,
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_mb": memory_info.rss / 1024 / 1024,
            "disk_usage_percent": psutil.disk_usage("/").percent,
        },
        "config": {
            "llm_mode": settings.llm_mode,
            "emb_backend": settings.emb_backend,
            "debug": settings.debug,
        }
    }


@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """Readiness check endpoint."""
    try:
        # Check database
        db.execute(text("SELECT 1"))
        
        # Check required directories
        required_dirs = ["./data", "./models", "./uploads"]
        for dir_path in required_dirs:
            if not os.path.exists(dir_path):
                return {"ready": False, "reason": f"Directory {dir_path} not found"}
        
        return {"ready": True}
    except Exception as e:
        return {"ready": False, "reason": str(e)}
