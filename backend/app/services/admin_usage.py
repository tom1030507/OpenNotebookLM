"""Aggregate server-wide usage for configured administrators."""
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import uuid

from sqlalchemy import LargeBinary, case, cast, func, select, union_all
from sqlalchemy.orm import Session
import structlog

from app.db.models import (
    AudioOverview,
    Conversation,
    Document,
    Message,
    Project,
    StudioGeneration,
    User,
)
from app.utils.time import utc_now

logger = structlog.get_logger()


@dataclass
class LLMUsage:
    """Provider token counts captured during one Studio operation."""

    token_count: int = 0


_current_usage: ContextVar[LLMUsage | None] = ContextVar(
    "studio_llm_usage",
    default=None,
)


@contextmanager
def capture_llm_usage():
    """Collect token counts from LLM calls made in this execution context.

    Args:
        None.

    Yields:
        The mutable token counter for the current generation.

    Returns:
        A context manager that resets capture after the operation.
    """
    usage = LLMUsage()
    token = _current_usage.set(usage)
    try:
        yield usage
    finally:
        _current_usage.reset(token)


def record_llm_usage(provider_usage: dict | None) -> None:
    """Add one provider response's token count to an active Studio request.

    Args:
        provider_usage: Provider usage object from `LLMService.generate`.

    Returns:
        None.
    """
    usage = _current_usage.get()
    if usage is None or not isinstance(provider_usage, dict):
        return
    try:
        usage.token_count += max(0, int(provider_usage.get("total_tokens") or 0))
    except (TypeError, ValueError):
        return


@contextmanager
def track_studio_generation(db: Session, user_id: str):
    """Record one successful Studio response and its provider token usage.

    Args:
        db: Request database session.
        user_id: User who requested the generation.

    Yields:
        None.

    Returns:
        A context manager that saves usage after the generation succeeds.
    """
    with capture_llm_usage() as usage:
        yield

    try:
        db.add(StudioGeneration(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_count=usage.token_count,
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to record Studio usage", user_id=user_id)


def sync_admin_users(db: Session, admin_emails: list[str]) -> None:
    """Set admin flags from the configured email allowlist.

    Args:
        db: Startup database session.
        admin_emails: Normalized addresses from `ADMIN_EMAILS`.

    Returns:
        None.
    """
    admins = {
        email.strip().casefold()
        for email in admin_emails
        if email.strip()
    }
    for user in db.query(User).all():
        user.is_admin = user.email.casefold() in admins
    db.commit()


def _metric_row(
    rows: dict,
    user_id: str | None,
    username: str = "Unassigned",
    email: str | None = None,
) -> dict:
    """Return the mutable usage row for an account or legacy unassigned data."""
    if user_id not in rows:
        rows[user_id] = {
            "user_id": user_id,
            "username": username,
            "email": email,
            "queries": 0,
            "studio_generations": 0,
            "tokens": 0,
            "estimated_cost_usd": 0.0,
            "storage_bytes": 0,
        }
    return rows[user_id]


def get_admin_usage(db: Session, days: int, cost_per_1k_tokens_usd: float) -> dict:
    """Return totals and per-user usage for a UTC calendar-day window.

    Args:
        db: Database session.
        days: Number of UTC calendar days to include (7, 30, or 90).
        cost_per_1k_tokens_usd: Blended estimate for messages without a stored cost.

    Returns:
        Server-wide totals, per-user usage, daily and weekly active account
        counts, and current storage snapshots. Activity includes queries,
        Studio generations, and added sources.
    """
    today = utc_now().date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min, timezone.utc)
    end = datetime.combine(today + timedelta(days=1), time.min, timezone.utc)
    token_rate = max(0.0, cost_per_1k_tokens_usd) / 1000
    rows = {}

    # shortcut: pre-feature Studio outputs lack generation records; add a backfill if admins need historical counts.

    for user_id, username, email in db.query(
        User.id, User.username, User.email
    ).order_by(User.username).all():
        _metric_row(rows, user_id, username, email)

    owner_id = func.coalesce(Conversation.user_id, Project.user_id)
    estimated_message_cost = case(
        (Message.cost.is_not(None), Message.cost),
        else_=func.coalesce(Message.token_count, 0) * token_rate,
    )
    message_rows = db.execute(
        select(
            owner_id.label("user_id"),
            func.sum(case((Message.role == "user", 1), else_=0)).label("queries"),
            func.sum(case(
                (Message.role == "assistant", func.coalesce(Message.token_count, 0)),
                else_=0,
            )).label("tokens"),
            func.sum(case(
                (Message.role == "assistant", estimated_message_cost),
                else_=0,
            )).label("cost"),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Project, Project.id == Conversation.project_id)
        .where(Message.created_at >= start, Message.created_at < end)
        .group_by(owner_id)
    ).all()
    for row in message_rows:
        metric = _metric_row(rows, row.user_id)
        metric["queries"] += row.queries or 0
        metric["tokens"] += row.tokens or 0
        metric["estimated_cost_usd"] += row.cost or 0

    studio_rows = db.execute(
        select(
            StudioGeneration.user_id,
            func.count(StudioGeneration.id).label("generations"),
            func.sum(StudioGeneration.token_count).label("tokens"),
        )
        .where(StudioGeneration.created_at >= start, StudioGeneration.created_at < end)
        .group_by(StudioGeneration.user_id)
    ).all()
    for row in studio_rows:
        metric = _metric_row(rows, row.user_id)
        metric["studio_generations"] += row.generations
        metric["tokens"] += row.tokens or 0
        metric["estimated_cost_usd"] += (row.tokens or 0) * token_rate

    audio_owner_id = func.coalesce(AudioOverview.user_id, Project.user_id)
    audio_rows = db.execute(
        select(
            audio_owner_id.label("user_id"),
            func.sum(
                case((AudioOverview.status == "ready", 1), else_=0)
            ).label("generations"),
            func.sum(AudioOverview.token_count).label("tokens"),
        )
        .join(Project, Project.id == AudioOverview.project_id)
        .where(
            AudioOverview.created_at >= start,
            AudioOverview.created_at < end,
        )
        .group_by(audio_owner_id)
    ).all()
    for row in audio_rows:
        metric = _metric_row(rows, row.user_id)
        metric["studio_generations"] += row.generations
        metric["tokens"] += row.tokens or 0
        metric["estimated_cost_usd"] += (row.tokens or 0) * token_rate

    for user_id, meta_json, content_size in db.execute(
        select(
            Document.user_id,
            Document.meta_json,
            func.length(cast(Document.content, LargeBinary)),
        )
    ).all():
        metadata = meta_json if isinstance(meta_json, dict) else {}
        value = (
            metadata.get("file_size")
            or metadata.get("text_size")
            or content_size
            or 0
        )
        try:
            size = int(value)
        except (TypeError, ValueError):
            size = 0
        if size > 0:
            _metric_row(rows, user_id)["storage_bytes"] += size

    activity = union_all(
        select(owner_id.label("user_id"), Message.created_at.label("created_at"))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Project, Project.id == Conversation.project_id)
        .where(Message.role == "user"),
        select(StudioGeneration.user_id, StudioGeneration.created_at),
        select(audio_owner_id, AudioOverview.created_at)
        .join(Project, Project.id == AudioOverview.project_id),
        select(Document.user_id, Document.created_at),
    ).subquery()
    activity_rows = db.execute(
        select(activity.c.user_id, func.date(activity.c.created_at))
        .where(activity.c.created_at >= start, activity.c.created_at < end)
    ).all()
    active_by_day = defaultdict(set)
    active_by_week = defaultdict(set)
    for user_id, day_value in activity_rows:
        if user_id is None or day_value is None:
            continue
        day = datetime.strptime(day_value, "%Y-%m-%d").date()
        active_by_day[day].add(user_id)
        active_by_week[day - timedelta(days=day.weekday())].add(user_id)

    daily_activity = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "user_count": len(active_by_day[today - timedelta(days=offset)]),
        }
        for offset in range(days - 1, -1, -1)
    ]
    first_week = start.date() - timedelta(days=start.date().weekday())
    week_starts = []
    week_start = first_week
    while week_start <= today:
        week_starts.append(week_start)
        week_start += timedelta(days=7)
    weekly_activity = [
        {"week_start": week.isoformat(), "user_count": len(active_by_week[week])}
        for week in week_starts
    ]

    per_user = sorted(
        rows.values(),
        key=lambda row: (row["user_id"] is None, row["username"].casefold()),
    )
    for row in per_user:
        row["estimated_cost_usd"] = round(row["estimated_cost_usd"], 6)
    totals = {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "queries": sum(row["queries"] for row in per_user),
        "studio_generations": sum(row["studio_generations"] for row in per_user),
        "tokens": sum(row["tokens"] for row in per_user),
        "estimated_cost_usd": round(
            sum(row["estimated_cost_usd"] for row in per_user), 6
        ),
        "storage_bytes": sum(row["storage_bytes"] for row in per_user),
    }
    return {
        "days": days,
        "active_users_by_day": daily_activity,
        "active_users_by_week": weekly_activity,
        "totals": totals,
        "users": per_user,
    }
