"""Durable queue lifecycle for project audio overviews."""
from __future__ import annotations

import asyncio
from threading import Event as ThreadEvent
from typing import Callable, Optional

import structlog
from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.db.models import AudioOverview
from app.utils.time import ordered_utc_now

logger = structlog.get_logger()
AudioProcessor = Callable[[str], None]


def recover_abandoned_audio_overviews(session_factory: sessionmaker) -> None:
    """Return work left running by a stopped process to the durable queue.

    Args:
        session_factory: Database session factory.

    Returns:
        None.
    """
    with session_factory() as db:
        db.execute(
            update(AudioOverview)
            .where(AudioOverview.status == "running")
            .values(status="queued", started_at=None, updated_at=ordered_utc_now())
        )
        db.commit()


def claim_next_audio_overview(session_factory: sessionmaker) -> Optional[str]:
    """Atomically claim the oldest queued overview.

    Args:
        session_factory: Database session factory.

    Returns:
        The claimed id, or None when no row was claimed.
    """
    with session_factory() as db:
        overview_id = db.query(AudioOverview.id).filter(
            AudioOverview.status == "queued",
        ).order_by(
            AudioOverview.created_at,
            AudioOverview.id,
        ).first()
        if overview_id is None:
            return None
        overview_id = overview_id[0]
        claimed = db.execute(
            update(AudioOverview)
            .where(
                AudioOverview.id == overview_id,
                AudioOverview.status == "queued",
            )
            .values(
                status="running",
                started_at=ordered_utc_now(),
                completed_at=None,
                error=None,
                updated_at=ordered_utc_now(),
            )
        )
        db.commit()
        return overview_id if claimed.rowcount == 1 else None


class AudioOverviewWorker:
    """Single-job supervisor with startup recovery and bounded polling."""

    def __init__(
        self,
        session_factory: sessionmaker,
        processor: Optional[AudioProcessor] = None,
        poll_interval: float = 0.5,
        enabled: bool = True,
    ) -> None:
        """Configure a sequential worker for the CPU-heavy speech pipeline.

        Args:
            session_factory: Factory for claim and per-job sessions.
            processor: Optional synchronous generation pipeline.
            poll_interval: Maximum seconds between empty-queue checks.
            enabled: Whether this process may recover and synthesize queued work.

        Returns:
            None.
        """
        if poll_interval <= 0:
            raise ValueError("audio overview worker poll interval must be positive")
        self.session_factory = session_factory
        if processor is None:
            from app.services.audio_overview import AudioOverviewService

            service = AudioOverviewService()
            processor = lambda overview_id: service.process(
                session_factory,
                overview_id,
            )
        self.processor = processor
        self.poll_interval = poll_interval
        self.enabled = enabled
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._claim_stop_event = ThreadEvent()

    async def start(self) -> None:
        """Recover interrupted rows and start the retained supervisor task."""
        if not self.enabled or (self._task is not None and not self._task.done()):
            return
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._claim_stop_event = ThreadEvent()
        self._loop = asyncio.get_running_loop()
        # shortcut: single backend process only; add leases before scaling replicas.
        await asyncio.to_thread(
            recover_abandoned_audio_overviews,
            self.session_factory,
        )
        self._task = asyncio.create_task(
            self._run(),
            name="durable-audio-overview-worker",
        )

    async def stop(self) -> None:
        """Stop claiming and drain the current speech job before shutdown."""
        self._claim_stop_event.set()
        self._stop_event.set()
        self._wake_event.set()
        task = self._task
        if task is not None:
            await task
        self._task = None
        self._loop = None

    def notify(self) -> None:
        """Wake the queue after a request commits a new overview row."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            self._wake_event.set()
        else:
            loop.call_soon_threadsafe(self._wake_event.set)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                overview_id = await asyncio.to_thread(
                    self._claim_next_unless_stopping,
                )
            except OperationalError as error:
                logger.warning(
                    "Audio overview claim failed; retrying",
                    error_type=type(error).__name__,
                )
                await self._wait_for_wake()
                continue
            if overview_id is None:
                await self._wait_for_wake()
                continue
            try:
                await asyncio.to_thread(self.processor, overview_id)
            except Exception as error:
                logger.exception(
                    "Audio overview worker processor failed",
                    overview_id=overview_id,
                    error_type=type(error).__name__,
                )
                self._mark_failed(overview_id)

    def _claim_next_unless_stopping(self) -> Optional[str]:
        if self._claim_stop_event.is_set():
            return None
        return claim_next_audio_overview(self.session_factory)

    async def _wait_for_wake(self) -> None:
        try:
            await asyncio.wait_for(
                self._wake_event.wait(),
                timeout=self.poll_interval,
            )
        except asyncio.TimeoutError:
            pass
        finally:
            self._wake_event.clear()

    def _mark_failed(self, overview_id: str) -> None:
        with self.session_factory() as db:
            db.execute(
                update(AudioOverview)
                .where(
                    AudioOverview.id == overview_id,
                    AudioOverview.status == "running",
                )
                .values(
                    status="failed",
                    error="Audio overview generation failed.",
                    completed_at=ordered_utc_now(),
                    updated_at=ordered_utc_now(),
                )
            )
            db.commit()
