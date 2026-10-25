"""SQL-backed usage summaries for owned projects."""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import case, func, select, true
from sqlalchemy.orm import Session

from app.db.models import Conversation, Document, Message, ProjectDocument
from app.utils.time import utc_now

_QUESTION_LIMIT = 280
_RECENT_LIMIT = 10


def get_project_analytics(
    db: Session,
    project_id: str,
    owner_id: str,
    days: int,
) -> dict:
    """Return project activity, citation, and rating aggregates.

    Args:
        db: Database session.
        project_id: Owned project id.
        owner_id: Project owner's user id.
        days: Calendar-day window (7, 30, or 90).

    Returns:
        Aggregated project analytics with zero-filled UTC days.
    """
    today = utc_now().date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min, timezone.utc)
    end = datetime.combine(today + timedelta(days=1), time.min, timezone.utc)

    question_day = func.date(Message.created_at).label("date")
    question_rows = db.execute(
        select(question_day, func.count(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Message.role == "user",
            Message.created_at >= start,
            Message.created_at < end,
        )
        .group_by(question_day)
    ).all()
    counts_by_day = {row.date: row[1] for row in question_rows}
    questions_by_day = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "question_count": counts_by_day.get(
                (today - timedelta(days=offset)).isoformat(), 0
            ),
        }
        for offset in range(days - 1, -1, -1)
    ]

    conversation_count = db.execute(
        select(func.count(func.distinct(Message.conversation_id)))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Message.created_at >= start,
            Message.created_at < end,
        )
    ).scalar_one()

    rating_row = db.execute(
        select(
            func.sum(case((Message.rating == "up", 1), else_=0)),
            func.sum(case((Message.rating == "down", 1), else_=0)),
            func.sum(case((Message.rating.in_(("up", "down")), 0), else_=1)),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Message.role == "assistant",
            Message.created_at >= start,
            Message.created_at < end,
        )
    ).one()
    ratings = {
        "up": rating_row[0] or 0,
        "down": rating_row[1] or 0,
        "unrated": rating_row[2] or 0,
    }

    citation_rows = func.json_each(Message.citations_json).table_valued(
        "value"
    ).alias("citation_rows")
    cited_document_id = func.json_extract(
        citation_rows.c.value, "$.document_id"
    ).label("document_id")
    citation_counts = (
        select(cited_document_id, func.count().label("citation_count"))
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(citation_rows, true())
        .join(
            ProjectDocument,
            (ProjectDocument.project_id == project_id)
            & (ProjectDocument.document_id == cited_document_id),
        )
        .where(
            Conversation.project_id == project_id,
            Message.role == "assistant",
            Message.created_at >= start,
            Message.created_at < end,
        )
        .group_by(cited_document_id)
        .subquery()
    )
    source_rows = db.execute(
        select(
            Document.id,
            Document.title,
            citation_counts.c.citation_count,
        )
        .select_from(ProjectDocument)
        .join(Document, Document.id == ProjectDocument.document_id)
        .outerjoin(citation_counts, citation_counts.c.document_id == Document.id)
        .where(ProjectDocument.project_id == project_id)
        .order_by(citation_counts.c.citation_count.desc(), Document.title)
    ).all()
    top_cited_sources = [
        {
            "document_id": row.id,
            "title": row.title,
            "citation_count": row.citation_count,
        }
        for row in source_rows
        if row.citation_count
    ]
    uncited_sources = [
        {"document_id": row.id, "title": row.title}
        for row in source_rows
        if not row.citation_count
    ]

    ordered_messages = (
        select(
            Message.id,
            Message.conversation_id,
            Message.role,
            Message.text,
            Message.rating,
            Message.created_at,
            func.row_number().over(
                partition_by=Message.conversation_id,
                order_by=(Message.created_at, Message.id),
            ).label("sequence"),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.project_id == project_id,
            (Conversation.user_id == owner_id) | Conversation.user_id.is_(None),
        )
        .cte("ordered_messages")
    )
    with_previous_question = select(
        ordered_messages,
        func.max(
            case(
                (ordered_messages.c.role == "user", ordered_messages.c.sequence),
                else_=None,
            )
        ).over(
            partition_by=ordered_messages.c.conversation_id,
            order_by=ordered_messages.c.sequence,
            rows=(None, -1),
        ).label("question_sequence"),
    ).cte("messages_with_previous_question")
    question_message = with_previous_question.alias("question_message")
    # shortcut: return only the latest 10 down-rated questions; add cursor pagination if users need older feedback.
    recent_rows = db.execute(
        select(question_message.c.text, with_previous_question.c.created_at)
        .join(
            question_message,
            (question_message.c.conversation_id == with_previous_question.c.conversation_id)
            & (question_message.c.sequence == with_previous_question.c.question_sequence),
        )
        .where(
            with_previous_question.c.role == "assistant",
            with_previous_question.c.rating == "down",
            with_previous_question.c.created_at >= start,
            with_previous_question.c.created_at < end,
        )
        .order_by(
            with_previous_question.c.created_at.desc(),
            with_previous_question.c.id.desc(),
        )
        .limit(_RECENT_LIMIT)
    ).all()
    recent_down_rated_questions = []
    for row in recent_rows:
        question = row.text.strip()
        if len(question) > _QUESTION_LIMIT:
            question = question[:_QUESTION_LIMIT - 1].rstrip() + "…"
        recent_down_rated_questions.append({
            "question": question,
            "answered_at": row.created_at,
        })

    return {
        "days": days,
        "questions_by_day": questions_by_day,
        "conversation_count": conversation_count,
        "top_cited_sources": top_cited_sources,
        "ratings": ratings,
        "recent_down_rated_questions": recent_down_rated_questions,
        "uncited_sources": uncited_sources,
    }
