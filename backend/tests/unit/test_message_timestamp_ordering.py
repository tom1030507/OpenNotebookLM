"""Regression coverage for deterministic message chronology."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Conversation, Message, Project
from app.utils import time as time_utils


FIXED_INSTANT = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze the shared UTC clock and isolate its monotonic state."""
    monkeypatch.setattr(time_utils, "utc_now", lambda: FIXED_INSTANT)
    monkeypatch.setattr(time_utils, "_last_ordered_utc_now", None, raising=False)


def test_ordered_utc_now_is_strictly_increasing_when_clock_is_frozen(frozen_clock):
    """Same-tick calls get a deterministic microsecond sequence."""
    values = [time_utils.ordered_utc_now() for _ in range(4)]

    assert values == [
        FIXED_INSTANT + timedelta(microseconds=offset)
        for offset in range(4)
    ]


def test_ordered_utc_now_is_thread_safe_when_clock_is_frozen(frozen_clock):
    """Concurrent calls do not reuse a frozen clock value."""
    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda _: time_utils.ordered_utc_now(), range(32)))

    assert len(set(values)) == 32
    assert sorted(values) == [
        FIXED_INSTANT + timedelta(microseconds=offset)
        for offset in range(32)
    ]


def test_same_flush_messages_have_strict_chronology_and_ordered_history(frozen_clock):
    """A same-flush history remains chronological even if the host clock ties."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(Project(id="project-1", name="Research", meta_json={}))
        session.add(Conversation(id="conversation-1", project_id="project-1", title="Chat"))
        session.add_all([
            Message(
                id=f"message-{index}",
                conversation_id="conversation-1",
                role=role,
                text=text,
                citations_json=[],
            )
            for index, (role, text) in enumerate([
                ("user", "First question"),
                ("assistant", "First answer"),
                ("user", "Second question"),
                ("assistant", "Second answer"),
            ])
        ])
        session.commit()

        history = session.query(Message).filter(
            Message.conversation_id == "conversation-1"
        ).order_by(Message.created_at).all()

        assert [message.text for message in history] == [
            "First question",
            "First answer",
            "Second question",
            "Second answer",
        ]
        assert [message.created_at for message in history] == [
            FIXED_INSTANT + timedelta(microseconds=offset)
            for offset in range(4)
        ]
    finally:
        session.close()
        engine.dispose()
