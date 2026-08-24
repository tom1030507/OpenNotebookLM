"""Tests for durable ingestion job persistence and worker lifecycle."""
import asyncio
import importlib.util
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import models
from app.services import ingestion_jobs
from app.utils.time import utc_now


@pytest.fixture
def job_database(tmp_path):
    """Create a file database whose sessions can cross worker threads.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        Engine and session factory for one isolated durable queue.
    """
    engine = create_engine(
        "sqlite:///%s" % (tmp_path / "worker.db"),
        connect_args={"check_same_thread": False},
    )
    models.Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield engine, session_factory
    finally:
        engine.dispose()


def add_document(db, document_id):
    """Insert the document required by a job foreign key.

    Args:
        db: Test database session.
        document_id: Identifier to insert.

    Returns:
        The inserted document.
    """
    document = models.Document(
        id=document_id,
        title=document_id,
        source_type="url",
        status="queued",
    )
    db.add(document)
    db.commit()
    return document


async def wait_for_job_status(session_factory, job_id, status, timeout=2):
    """Wait until a worker persists one expected terminal or active state.

    Args:
        session_factory: Factory bound to the test database.
        job_id: Durable job identifier.
        status: State to wait for.
        timeout: Maximum seconds before the assertion fails.

    Returns:
        The matching status string.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        with session_factory() as db:
            if db.get(models.IngestionJob, job_id).status == status:
                return status
        await asyncio.sleep(0.01)
    raise AssertionError("job %s never reached %s" % (job_id, status))


def test_ingestion_job_service_is_available():
    """The durable queue has a service module owned by the application.

    Args:
        None.

    Returns:
        None.
    """
    assert importlib.util.find_spec("app.services.ingestion_jobs") is not None


def test_create_all_adds_ingestion_jobs_idempotently(tmp_path):
    """A fresh database can create the durable queue more than once.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        None.
    """
    assert hasattr(models, "IngestionJob")

    database_path = tmp_path / "jobs.db"
    engine = create_engine("sqlite:///%s" % database_path)
    try:
        models.Base.metadata.create_all(engine)

        inspector = inspect(engine)
        assert "ingestion_jobs" in inspector.get_table_names()
        assert {
            "id",
            "document_id",
            "job_type",
            "payload_json",
            "status",
            "attempts",
            "last_error",
            "created_at",
            "started_at",
            "completed_at",
        } == {
            column["name"]
            for column in inspector.get_columns("ingestion_jobs")
        }

        session_factory = sessionmaker(bind=engine)
        with session_factory() as db:
            db.add(models.Document(
                id="document-1",
                title="Queued source",
                source_type="url",
            ))
            db.add(models.IngestionJob(
                id="job-1",
                document_id="document-1",
                job_type="url",
                payload_json={"url": "https://example.com"},
            ))
            db.commit()

        models.Base.metadata.create_all(engine)

        with session_factory() as db:
            job = db.get(models.IngestionJob, "job-1")
            assert job.status == "queued"
            assert job.attempts == 0
            assert job.created_at.utcoffset().total_seconds() == 0
    finally:
        engine.dispose()


def test_only_active_jobs_are_unique_per_document(job_database):
    """Terminal history coexists, but two active rows cannot compete.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        add_document(db, "document-1")
        db.add_all([
            models.IngestionJob(
                id="failed-1",
                document_id="document-1",
                job_type="url",
                payload_json={"url": "https://example.com/1"},
                status="failed",
            ),
            models.IngestionJob(
                id="failed-2",
                document_id="document-1",
                job_type="url",
                payload_json={"url": "https://example.com/2"},
                status="failed",
            ),
        ])
        db.commit()

        db.add(models.IngestionJob(
            id="queued-1",
            document_id="document-1",
            job_type="url",
            payload_json={"url": "https://example.com/retry"},
            status="queued",
        ))
        db.commit()
        db.add(models.IngestionJob(
            id="running-2",
            document_id="document-1",
            job_type="url",
            payload_json={"url": "https://example.com/duplicate"},
            status="running",
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_duplicate_enqueue_reuses_one_durable_job(job_database):
    """Repeated enqueue cannot create competing work for one document.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        add_document(db, "document-1")
        first = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-1",
            job_type="url",
            payload={"url": "https://example.com"},
        )
        db.commit()
        first_id = first.id

        second = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-1",
            job_type="url",
            payload={"url": "https://example.com"},
        )
        db.commit()

        assert second.id == first_id
        assert db.query(models.IngestionJob).count() == 1
        assert second.status == "queued"


def test_enqueue_preserves_failed_history_and_creates_one_retry(job_database):
    """Retry keeps terminal history while creating one new active row.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-1")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com"},
        )
        job.status = "failed"
        job.attempts = 1
        job.last_error = {"type": "RuntimeError", "message": "offline"}
        job.completed_at = utc_now()
        document.status = "error"
        db.commit()
        failed_job_id = job.id

        retried = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com"},
        )
        db.commit()

        assert retried.id != failed_job_id
        assert retried.status == "queued"
        assert retried.attempts == 0
        assert retried.last_error is None
        assert retried.completed_at is None
        assert document.status == "queued"
        assert db.query(models.IngestionJob).count() == 2
        failed = db.get(models.IngestionJob, failed_job_id)
        assert failed.status == "failed"
        assert failed.last_error == {
            "type": "RuntimeError",
            "message": "offline",
        }


def test_recovery_requeues_abandoned_running_jobs(job_database):
    """Startup makes work abandoned by a crashed process claimable again.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-1")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com"},
        )
        job.status = "running"
        job.attempts = 1
        job.started_at = utc_now()
        document.status = "processing"
        db.commit()
        job_id = job.id

    assert ingestion_jobs.recover_abandoned_jobs(session_factory) == 1

    with session_factory() as db:
        recovered = db.get(models.IngestionJob, job_id)
        assert recovered.status == "queued"
        assert recovered.attempts == 1
        assert recovered.started_at is None
        assert recovered.document.status == "queued"


def test_worker_claims_atomically_and_records_attempt_metadata(job_database):
    """A claim moves exactly one queued job to running before processing.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        add_document(db, "document-1")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-1",
            job_type="url",
            payload={"url": "https://example.com"},
        )
        db.commit()
        job_id = job.id

    assert ingestion_jobs.claim_next_job(session_factory) == job_id
    assert ingestion_jobs.claim_next_job(session_factory) is None

    with session_factory() as db:
        claimed = db.get(models.IngestionJob, job_id)
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.started_at is not None
        assert claimed.document.status == "processing"


def test_two_sessions_have_exactly_one_claim_winner(job_database):
    """Concurrent claimers cannot both increment and execute one job.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        add_document(db, "document-1")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-1",
            job_type="url",
            payload={"url": "https://example.com"},
        )
        db.commit()
        job_id = job.id

    barrier = threading.Barrier(2)

    def claim_together():
        barrier.wait(timeout=2)
        return ingestion_jobs.claim_next_job(session_factory)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim_together(), range(2)))

    assert sorted(result is None for result in results) == [False, True]
    assert job_id in results
    with session_factory() as db:
        claimed = db.get(models.IngestionJob, job_id)
        assert claimed.status == "running"
        assert claimed.attempts == 1


def test_worker_uses_a_fresh_session_outside_the_event_loop(job_database):
    """A claimed job never reuses the request Session or blocks asyncio.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as request_db:
        add_document(request_db, "document-1")
        job = ingestion_jobs.enqueue_ingestion_job(
            request_db,
            document_id="document-1",
            job_type="url",
            payload={"url": "https://example.com"},
        )
        request_db.commit()
        job_id = job.id
        request_session_id = id(request_db)

    processor_calls = []
    main_thread_id = threading.get_ident()

    def processor(db, claimed_job):
        processor_calls.append((id(db), threading.get_ident(), claimed_job.id))
        claimed_job.document.status = "ready"
        db.commit()

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=session_factory,
            processor=processor,
            concurrency=1,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            await wait_for_job_status(session_factory, job_id, "completed")
        finally:
            await worker.stop()

    asyncio.run(scenario())

    assert processor_calls == [(
        processor_calls[0][0],
        processor_calls[0][1],
        job_id,
    )]
    assert processor_calls[0][0] != request_session_id
    assert processor_calls[0][1] != main_thread_id


def test_slow_processor_does_not_delay_an_event_loop_heartbeat(job_database):
    """Blocking model work runs in a worker thread, not on the event loop.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        add_document(db, "document-1")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-1",
            job_type="url",
            payload={"url": "https://example.com"},
        )
        db.commit()
        job_id = job.id

    processor_started = threading.Event()
    release_processor = threading.Event()

    def slow_processor(db, claimed_job):
        processor_started.set()
        release_processor.wait(timeout=2)
        claimed_job.document.status = "ready"
        db.commit()

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=session_factory,
            processor=slow_processor,
            concurrency=1,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            while not processor_started.is_set():
                await asyncio.sleep(0.005)
            heartbeats = 0
            deadline = asyncio.get_running_loop().time() + 0.06
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
                heartbeats += 1
            assert heartbeats >= 4
        finally:
            release_processor.set()
            await worker.stop()

        await wait_for_job_status(session_factory, job_id, "completed")

    asyncio.run(scenario())


def test_graceful_shutdown_leaves_unclaimed_work_queued(job_database):
    """Stopping waits for active work but never consumes the next queued job.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        for document_id in ("document-1", "document-2"):
            add_document(db, document_id)
            ingestion_jobs.enqueue_ingestion_job(
                db,
                document_id=document_id,
                job_type="url",
                payload={"url": "https://example.com/%s" % document_id},
            )
            db.commit()

    processor_started = threading.Event()
    release_processor = threading.Event()

    def blocking_processor(db, claimed_job):
        processor_started.set()
        release_processor.wait(timeout=2)
        claimed_job.document.status = "ready"
        db.commit()

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=session_factory,
            processor=blocking_processor,
            concurrency=1,
            poll_interval=0.01,
        )
        await worker.start()
        while not processor_started.is_set():
            await asyncio.sleep(0.005)

        stop_task = asyncio.create_task(worker.stop())
        await asyncio.sleep(0.03)
        assert not stop_task.done()
        release_processor.set()
        await stop_task

    asyncio.run(scenario())

    with session_factory() as db:
        states = [
            row.status
            for row in db.query(models.IngestionJob)
            .order_by(models.IngestionJob.created_at, models.IngestionJob.id)
            .all()
        ]
    assert states == ["completed", "queued"]


def test_worker_never_exceeds_configured_concurrency(job_database):
    """The next queued job waits until one configured slot is free.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    job_ids = []
    with session_factory() as db:
        for index in range(3):
            document_id = "document-%s" % index
            add_document(db, document_id)
            job = ingestion_jobs.enqueue_ingestion_job(
                db,
                document_id=document_id,
                job_type="url",
                payload={"url": "https://example.com/%s" % index},
            )
            db.commit()
            job_ids.append(job.id)

    lock = threading.Lock()
    release = threading.Event()
    two_started = threading.Event()
    active = 0
    maximum_active = 0
    started_ids = []

    def blocking_processor(db, claimed_job):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            started_ids.append(claimed_job.id)
            if len(started_ids) == 2:
                two_started.set()
        release.wait(timeout=2)
        claimed_job.document.status = "ready"
        db.commit()
        with lock:
            active -= 1

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=session_factory,
            processor=blocking_processor,
            concurrency=2,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            while not two_started.is_set():
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.04)
            assert len(started_ids) == 2
            release.set()
            for job_id in job_ids:
                await wait_for_job_status(
                    session_factory,
                    job_id,
                    "completed",
                )
        finally:
            release.set()
            await worker.stop()

    asyncio.run(scenario())

    assert maximum_active == 2
    assert set(started_ids) == set(job_ids)


def test_notify_from_request_thread_wakes_the_worker_loop(job_database):
    """A sync request thread can safely wake a worker on the asyncio loop.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    queued_id = []

    def processor(db, claimed_job):
        claimed_job.document.status = "ready"
        db.commit()

    def enqueue_from_thread(worker):
        with session_factory() as db:
            add_document(db, "document-thread")
            job = ingestion_jobs.enqueue_ingestion_job(
                db,
                document_id="document-thread",
                job_type="url",
                payload={"url": "https://example.com/thread"},
            )
            db.commit()
            queued_id.append(job.id)
        worker.notify()

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=session_factory,
            processor=processor,
            concurrency=1,
            poll_interval=5,
        )
        await worker.start()
        try:
            await asyncio.to_thread(enqueue_from_thread, worker)
            assert await wait_for_job_status(
                session_factory,
                queued_id[0],
                "completed",
                timeout=1,
            ) == "completed"
        finally:
            await worker.stop()

    asyncio.run(scenario())
