"""
Monitoring API endpoints for system metrics and dashboard.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

from app.services.monitoring import monitoring_service

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

@router.get("/dashboard")
async def get_dashboard():
    """
    Get comprehensive dashboard data.
    
    Returns:
        Dashboard metrics including API stats, costs, and errors
    """
    try:
        data = monitoring_service.get_dashboard_data()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api-metrics")
async def get_api_metrics(
    hours: int = Query(24, description="Number of hours to look back")
):
    """
    Get API metrics summary.
    
    Args:
        hours: Number of hours to look back
        
    Returns:
        API metrics summary
    """
    try:
        data = monitoring_service.get_api_metrics_summary(hours)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/costs")
async def get_costs(
    days: int = Query(30, description="Number of days to look back")
):
    """
    Get cost summary.
    
    Args:
        days: Number of days to look back
        
    Returns:
        Cost summary by service
    """
    try:
        data = monitoring_service.get_cost_summary(days)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/errors")
async def get_errors(
    hours: int = Query(24, description="Number of hours to look back")
):
    """
    Get error summary.
    
    Args:
        hours: Number of hours to look back
        
    Returns:
        Error summary by type
    """
    try:
        data = monitoring_service.get_error_summary(hours)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cleanup")
async def cleanup_old_data(
    days: int = Query(90, description="Delete data older than N days")
):
    """
    Clean up old monitoring data.
    
    Args:
        days: Delete data older than N days
        
    Returns:
        Success message
    """
    try:
        monitoring_service.cleanup_old_data(days)
        return {
            "message": f"Successfully cleaned up data older than {days} days",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring.
    
    Returns:
        Health status
    """
    return {
        "status": "healthy",
        "service": "monitoring",
        "timestamp": datetime.now().isoformat()
    }
