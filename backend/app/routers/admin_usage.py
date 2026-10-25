"""Administrator-only server-wide usage reporting."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.schemas import AdminUsageResponse
from app.services.admin_usage import get_admin_usage

router = APIRouter()


@router.get("/admin/usage", response_model=AdminUsageResponse)
def admin_usage(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Return server-wide usage to configured administrators.

    Args:
        days: Number of UTC calendar days to include.
        db: Database session.
        current_user: Signed-in account.
        settings: Current cost estimation setting.

    Returns:
        Total and per-user usage for the selected window.

    Raises:
        HTTPException: With status 404 when the account is not an administrator.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=404, detail="Not found")
    if days not in (7, 30, 90):
        raise HTTPException(status_code=422, detail="days must be 7, 30, or 90")
    return get_admin_usage(db, days, settings.estimated_cost_per_1k_tokens_usd)
