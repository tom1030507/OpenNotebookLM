"""Tests for durable ingestion job persistence and worker lifecycle."""
import asyncio
import importlib.util
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db import models
from app.services import ingestion_jobs
from app.services.rate_limit import ConcurrencyLimiter
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


def test_persisted_retry_respects_the_callers_outer_rollback(job_database):
    """A retry savepoint cannot commit outside its caller's transaction.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-rollback-retry")
        failed = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/failed"},
        )
        failed.status = "failed"
        failed.attempts = 1
        failed.last_error = {"type": "RuntimeError", "message": "offline"}
        failed.completed_at = utc_now()
        document.status = "error"
        document.error_message = "offline"
        db.commit()
        failed_job_id = failed.id

    with session_factory() as db:
        result = ingestion_jobs.enqueue_ingestion_job_with_result(
            db,
            document_id="document-rollback-retry",
            job_type="url",
            payload={"url": "https://example.com/retry"},
        )
        retry_job_id = result.job.id
        assert result.created_new_active
        db.rollback()

    with session_factory() as db:
        assert db.get(models.IngestionJob, retry_job_id) is None
        assert db.query(models.IngestionJob).count() == 1
        failed = db.get(models.IngestionJob, failed_job_id)
        assert failed.status == "failed"
        document = db.get(models.Document, "document-rollback-retry")
        assert document.status == "error"
        assert document.error_message == "offline"


def test_public_enqueue_commit_failure_does_not_persist_retry(job_database):
    """The public enqueue wrapper leaves commit ownership with its caller.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    engine, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-public-commit-failure")
        failed = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/failed"},
        )
        failed.status = "failed"
        failed.completed_at = utc_now()
        document.status = "error"
        db.commit()

    class RejectCommitSession(Session):
        def commit(self):
            raise OperationalError(
                "COMMIT",
                {},
                RuntimeError("caller commit failed"),
            )

    rejecting_factory = sessionmaker(
        bind=engine,
        class_=RejectCommitSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    with rejecting_factory() as db:
        with pytest.raises(OperationalError, match="caller commit failed"):
            try:
                retry = ingestion_jobs.enqueue_ingestion_job(
                    db,
                    document_id="document-public-commit-failure",
                    job_type="url",
                    payload={"url": "https://example.com/retry"},
                )
                retry_job_id = retry.id
                db.commit()
            except Exception:
                db.rollback()
                raise

    with session_factory() as db:
        assert db.get(models.IngestionJob, retry_job_id) is None
        assert db.query(models.IngestionJob).count() == 1
        assert db.get(
            models.Document,
            "document-public-commit-failure",
        ).status == "error"


def test_concurrent_retries_share_one_job_and_keep_outer_pending_rows(
    job_database,
):
    """SQLite retry contenders serialize without losing caller-owned rows.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-eight-way-retry")
        failed = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/failed"},
        )
        failed.status = "failed"
        failed.completed_at = utc_now()
        document.status = "error"
        db.commit()

    contender_count = 8
    barrier = threading.Barrier(contender_count)

    def enqueue_contender(contender_number):
        with session_factory() as db:
            pending_id = "pending-outer-%s" % contender_number
            db.add(models.Document(
                id=pending_id,
                title=pending_id,
                source_type="url",
                status="queued",
            ))
            barrier.wait(timeout=2)
            result = ingestion_jobs.enqueue_ingestion_job_with_result(
                db,
                document_id="document-eight-way-retry",
                job_type="url",
                payload={"url": "https://example.com/retry"},
            )
            db.commit()
            return result.job.id, result.created_new_active, pending_id

    with ThreadPoolExecutor(max_workers=contender_count) as executor:
        results = list(executor.map(
            enqueue_contender,
            range(contender_count),
        ))

    job_ids = {job_id for job_id, _, _ in results}
    assert len(job_ids) == 1
    assert sum(created for _, created, _ in results) == 1
    with session_factory() as db:
        assert db.query(models.IngestionJob).count() == 2
        assert {
            db.get(models.Document, pending_id).id
            for _, _, pending_id in results
        } == {pending_id for _, _, pending_id in results}


def test_completed_enqueue_result_does_not_retain_an_unclaimable_lease(
    job_database,
):
    """A completed idempotent enqueue immediately releases its new slot.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-completed-result")
        completed = models.IngestionJob(
            id="completed-result-job",
            document_id=document.id,
            job_type="url",
            payload_json={"url": "https://example.com/completed"},
            status="completed",
            attempts=1,
            completed_at=utc_now(),
        )
        db.add(completed)
        db.commit()

        result = ingestion_jobs.enqueue_ingestion_job_with_result(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/completed"},
        )

    limiter = ConcurrencyLimiter(max_concurrent=1)
    ingestion_jobs.release_all_operation_leases()
    try:
        retained = ingestion_jobs.retain_enqueued_operation_lease(
            result,
            limiter.acquire("ingest:user"),
        )
        assert not result.created_new_active
        assert not retained
        assert limiter.active("ingest:user") == 0
    finally:
        ingestion_jobs.release_all_operation_leases()


def test_active_enqueue_result_cannot_replace_winner_lease_if_job_finishes(
    job_database,
):
    """An active duplicate keeps immutable non-ownership across completion.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-active-result")
        active = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/active"},
        )
        db.commit()
        result = ingestion_jobs.enqueue_ingestion_job_with_result(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/active"},
        )
        active.status = "completed"
        active.completed_at = utc_now()
        db.commit()

    limiter = ConcurrencyLimiter(max_concurrent=2)
    ingestion_jobs.release_all_operation_leases()
    try:
        assert ingestion_jobs.retain_operation_lease(
            active.id,
            limiter.acquire("ingest:user"),
        )
        assert limiter.active("ingest:user") == 1
        retained = ingestion_jobs.retain_enqueued_operation_lease(
            result,
            limiter.acquire("ingest:user"),
        )
        assert not result.created_new_active
        assert not retained
        assert limiter.active("ingest:user") == 1
        ingestion_jobs.release_operation_lease(active.id)
        assert limiter.active("ingest:user") == 0
    finally:
        ingestion_jobs.release_all_operation_leases()


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


def test_recovery_accepts_a_commit_acknowledgement_failure(job_database):
    """Startup proceeds when its abandoned-job commit was actually accepted.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    engine, setup_session_factory = job_database
    with setup_session_factory() as db:
        document = add_document(db, "document-recovery-ack")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/recovery-ack"},
        )
        job.status = "running"
        job.attempts = 1
        job.started_at = utc_now()
        document.status = "processing"
        db.commit()
        job_id = job.id

    class AcceptedThenRaisedSession(Session):
        failures_remaining = 1

        def commit(self):
            super().commit()
            if self.__class__.failures_remaining:
                self.__class__.failures_remaining -= 1
                raise OperationalError(
                    "COMMIT",
                    {},
                    RuntimeError("commit acknowledgement lost"),
                )

    recovery_factory = sessionmaker(
        bind=engine,
        class_=AcceptedThenRaisedSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    assert ingestion_jobs.recover_abandoned_jobs(recovery_factory) == 1
    with setup_session_factory() as db:
        recovered = db.get(models.IngestionJob, job_id)
        assert recovered.status == "queued"
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


def test_claim_accepts_a_matching_commit_acknowledgement_failure(job_database):
    """A durable running claim is dispatched when only its ACK was lost.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    engine, setup_session_factory = job_database
    with setup_session_factory() as db:
        document = add_document(db, "document-claim-ack")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/claim-ack"},
        )
        db.commit()
        job_id = job.id

    class AcceptedThenRaisedSession(Session):
        failures_remaining = 1

        def commit(self):
            super().commit()
            if self.__class__.failures_remaining:
                self.__class__.failures_remaining -= 1
                raise OperationalError(
                    "COMMIT",
                    {},
                    RuntimeError("claim acknowledgement lost"),
                )

    claim_factory = sessionmaker(
        bind=engine,
        class_=AcceptedThenRaisedSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    assert ingestion_jobs.claim_next_job(claim_factory) == job_id
    with setup_session_factory() as db:
        claimed = db.get(models.IngestionJob, job_id)
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.started_at is not None
        assert claimed.document.status == "processing"

    def processor(db, claimed_job):
        claimed_job.document.status = "ready"

    ingestion_jobs.IngestionJobWorker(
        session_factory=setup_session_factory,
        processor=processor,
    )._process_claimed_job(job_id)
    with setup_session_factory() as db:
        assert db.get(models.IngestionJob, job_id).status == "completed"


def test_claim_rejects_an_ack_for_a_superseded_attempt(job_database):
    """Fresh reconciliation cannot dispatch a claim whose token changed.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    engine, setup_session_factory = job_database
    with setup_session_factory() as db:
        document = add_document(db, "document-claim-superseded")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/claim-superseded"},
        )
        db.commit()
        job_id = job.id

    class AcceptedThenSupersededSession(Session):
        failures_remaining = 1

        def commit(self):
            super().commit()
            if self.__class__.failures_remaining:
                self.__class__.failures_remaining -= 1
                with Session(bind=engine) as concurrent_db:
                    superseded = concurrent_db.get(
                        models.IngestionJob,
                        job_id,
                    )
                    superseded.status = "queued"
                    superseded.started_at = None
                    superseded.document.status = "queued"
                    concurrent_db.commit()
                raise OperationalError(
                    "COMMIT",
                    {},
                    RuntimeError("claim acknowledgement lost"),
                )

    claim_factory = sessionmaker(
        bind=engine,
        class_=AcceptedThenSupersededSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    with pytest.raises(OperationalError, match="claim acknowledgement lost"):
        ingestion_jobs.claim_next_job(claim_factory)
    with setup_session_factory() as db:
        superseded = db.get(models.IngestionJob, job_id)
        assert superseded.status == "queued"
        assert superseded.started_at is None
        assert superseded.document.status == "queued"


def test_processor_releases_lease_for_an_already_terminal_job(job_database):
    """A reconciled claim cannot strand a lease if work already terminated.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        document = add_document(db, "document-terminal-before-process")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id=document.id,
            job_type="url",
            payload={"url": "https://example.com/terminal-before-process"},
        )
        job.status = "completed"
        job.completed_at = utc_now()
        document.status = "ready"
        db.commit()
        job_id = job.id

    limiter = ConcurrencyLimiter(max_concurrent=1)
    ingestion_jobs.release_all_operation_leases()
    ingestion_jobs.retain_operation_lease(
        job_id,
        limiter.acquire("ingest:user"),
    )
    worker = ingestion_jobs.IngestionJobWorker(
        session_factory=session_factory,
        processor=lambda *_args: pytest.fail("terminal job was processed"),
    )
    try:
        worker._process_claimed_job(job_id)
        assert limiter.active("ingest:user") == 0
    finally:
        ingestion_jobs.release_all_operation_leases()


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


def test_transient_claim_failure_does_not_kill_supervisor(
    job_database,
    monkeypatch,
):
    """One SQLite busy claim is retried without losing the retained worker.

    Args:
        job_database: Isolated file database fixture.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    _, session_factory = job_database
    with session_factory() as db:
        add_document(db, "document-transient-claim")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-transient-claim",
            job_type="url",
            payload={"url": "https://example.com/transient"},
        )
        db.commit()
        job_id = job.id

    real_claim = ingestion_jobs.claim_next_job
    claim_calls = 0

    def fail_once_claim(factory):
        nonlocal claim_calls
        claim_calls += 1
        if claim_calls == 1:
            raise OperationalError(
                "UPDATE ingestion_jobs",
                {},
                RuntimeError("database is locked"),
            )
        return real_claim(factory)

    def processor(db, claimed_job):
        claimed_job.document.status = "ready"
        db.commit()

    monkeypatch.setattr(ingestion_jobs, "claim_next_job", fail_once_claim)

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=session_factory,
            processor=processor,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await wait_for_job_status(
                session_factory,
                job_id,
                "completed",
                timeout=1,
            ) == "completed"
            assert worker._task is not None
            assert not worker._task.done()
        finally:
            await worker.stop()

    asyncio.run(scenario())
    assert claim_calls >= 2


def test_terminal_commit_failure_compensates_index_and_retains_lease(
    job_database,
):
    """An ambiguous completion is requeued without a searchable index.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    engine, setup_session_factory = job_database

    class FailCompletedCommitSession(Session):
        failures_remaining = 1
        failure_seen = threading.Event()

        def commit(self):
            terminal_dirty = any(
                isinstance(instance, models.IngestionJob)
                and instance.status == "completed"
                for instance in self.dirty
            )
            if terminal_dirty and self.__class__.failures_remaining:
                self.__class__.failures_remaining -= 1
                self.__class__.failure_seen.set()
                raise OperationalError(
                    "COMMIT",
                    {},
                    RuntimeError("terminal commit failed"),
                )
            return super().commit()

    worker_session_factory = sessionmaker(
        bind=engine,
        class_=FailCompletedCommitSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    with setup_session_factory() as db:
        add_document(db, "document-terminal-commit")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-terminal-commit",
            job_type="url",
            payload={"url": "https://example.com/terminal"},
        )
        db.commit()
        job_id = job.id

    def processor(db, claimed_job):
        chunk = models.Chunk(
            id="terminal-chunk",
            document_id=claimed_job.document_id,
            text="committed searchable text",
        )
        db.add(chunk)
        db.flush()
        db.add(models.Embedding(
            id="terminal-embedding",
            chunk_id=chunk.id,
            vector=b"vector",
            vector_json=[1.0],
            model_name="test-model",
        ))
        db.commit()
        claimed_job.document.status = "ready"

    limiter = ConcurrencyLimiter(max_concurrent=1)
    ingestion_jobs.release_all_operation_leases()
    ingestion_jobs.retain_operation_lease(
        job_id,
        limiter.acquire("ingest:user"),
    )

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=worker_session_factory,
            processor=processor,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await asyncio.to_thread(
                FailCompletedCommitSession.failure_seen.wait,
                1,
            )
            worker._stop_event.set()
            worker._wake_event.set()
            assert await wait_for_job_status(
                setup_session_factory,
                job_id,
                "queued",
            ) == "queued"
            with setup_session_factory() as db:
                persisted = db.get(models.IngestionJob, job_id)
                assert persisted.status == "queued"
                assert persisted.document.status == "queued"
                assert persisted.last_error["phase"] == "terminal_commit"
                assert db.query(models.Chunk).count() == 0
                assert db.query(models.Embedding).count() == 0
            assert limiter.active("ingest:user") == 1
        finally:
            await worker.stop()

    try:
        asyncio.run(scenario())
        assert limiter.active("ingest:user") == 0
        assert ingestion_jobs.recover_abandoned_jobs(
            setup_session_factory,
        ) == 0
        with setup_session_factory() as db:
            recovered = db.get(models.IngestionJob, job_id)
            assert recovered.status == "queued"
            assert recovered.document.status == "queued"
    finally:
        ingestion_jobs.release_all_operation_leases()


def test_failed_terminal_commit_compensates_partial_index_and_retains_lease(
    job_database,
):
    """A failed-state commit error requeues without processor checkpoints.

    Args:
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    engine, setup_session_factory = job_database

    class FailFailedCommitSession(Session):
        failures_remaining = 1
        failure_seen = threading.Event()

        def commit(self):
            failed_dirty = any(
                isinstance(instance, models.IngestionJob)
                and instance.status == "failed"
                for instance in self.dirty
            )
            if failed_dirty and self.__class__.failures_remaining:
                self.__class__.failures_remaining -= 1
                self.__class__.failure_seen.set()
                raise OperationalError(
                    "COMMIT",
                    {},
                    RuntimeError("failed-state commit failed"),
                )
            return super().commit()

    worker_session_factory = sessionmaker(
        bind=engine,
        class_=FailFailedCommitSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    with setup_session_factory() as db:
        add_document(db, "document-failed-terminal")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-failed-terminal",
            job_type="url",
            payload={"url": "https://example.com/failed-terminal"},
        )
        db.commit()
        job_id = job.id

    def processor(db, claimed_job):
        chunk = models.Chunk(
            id="failed-terminal-chunk",
            document_id=claimed_job.document_id,
            text="partial searchable text",
        )
        db.add(chunk)
        db.flush()
        db.add(models.Embedding(
            id="failed-terminal-embedding",
            chunk_id=chunk.id,
            vector=b"vector",
            vector_json=[1.0],
            model_name="test-model",
        ))
        db.commit()
        raise RuntimeError("processor failed after checkpoint")

    limiter = ConcurrencyLimiter(max_concurrent=1)
    ingestion_jobs.release_all_operation_leases()
    ingestion_jobs.retain_operation_lease(
        job_id,
        limiter.acquire("ingest:user"),
    )

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=worker_session_factory,
            processor=processor,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await asyncio.to_thread(
                FailFailedCommitSession.failure_seen.wait,
                1,
            )
            worker._stop_event.set()
            worker._wake_event.set()
            assert await wait_for_job_status(
                setup_session_factory,
                job_id,
                "queued",
            ) == "queued"
            with setup_session_factory() as db:
                persisted = db.get(models.IngestionJob, job_id)
                assert persisted.status == "queued"
                assert persisted.document.status == "queued"
                assert persisted.last_error["phase"] == "terminal_commit"
                assert db.query(models.Chunk).count() == 0
                assert db.query(models.Embedding).count() == 0
            assert limiter.active("ingest:user") == 1
        finally:
            await worker.stop()

    try:
        asyncio.run(scenario())
        assert limiter.active("ingest:user") == 0
        assert ingestion_jobs.recover_abandoned_jobs(
            setup_session_factory,
        ) == 0
    finally:
        ingestion_jobs.release_all_operation_leases()


@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_delete_during_terminal_compensation_releases_running_lease(
    terminal_status,
    job_database,
):
    """A delete after compensation's first read cannot strand its job lease.

    Args:
        terminal_status: Terminal commit whose acknowledgement fails.
        job_database: Isolated file database fixture.

    Returns:
        None.
    """
    engine, setup_session_factory = job_database

    class FailTerminalCommitSession(Session):
        failures_remaining = 1

        def commit(self):
            terminal_dirty = any(
                isinstance(instance, models.IngestionJob)
                and instance.status == terminal_status
                for instance in self.dirty
            )
            if terminal_dirty and self.__class__.failures_remaining:
                self.__class__.failures_remaining -= 1
                raise OperationalError(
                    "COMMIT",
                    {},
                    RuntimeError("terminal-state commit failed"),
                )
            return super().commit()

    worker_session_factory = sessionmaker(
        bind=engine,
        class_=FailTerminalCommitSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    with setup_session_factory() as db:
        add_document(db, "document-delete-during-compensation")
        job = ingestion_jobs.enqueue_ingestion_job(
            db,
            document_id="document-delete-during-compensation",
            job_type="url",
            payload={"url": "https://example.com/delete-compensation"},
        )
        db.commit()
        job_id = job.id

    def processor(db, claimed_job):
        chunk = models.Chunk(
            id="delete-compensation-chunk",
            document_id=claimed_job.document_id,
            text="partial searchable text",
        )
        db.add(chunk)
        db.flush()
        db.add(models.Embedding(
            id="delete-compensation-embedding",
            chunk_id=chunk.id,
            vector=b"vector",
            vector_json=[1.0],
            model_name="test-model",
        ))
        db.commit()
        if terminal_status == "failed":
            raise RuntimeError("processor failed after checkpoint")
        claimed_job.document.status = "ready"

    compensation_read = threading.Event()
    allow_compensation = threading.Event()

    def pause_before_compensation_requeue(
        _connection,
        _cursor,
        statement,
        _parameters,
        context,
        _executemany,
    ):
        normalized = " ".join(statement.lower().split())
        compiled_parameters = getattr(context, "compiled_parameters", ())
        new_status = (
            compiled_parameters[0].get("status")
            if compiled_parameters
            else None
        )
        if (
            normalized.startswith("update ingestion_jobs")
            and new_status == "queued"
            and not compensation_read.is_set()
        ):
            compensation_read.set()
            assert allow_compensation.wait(timeout=2)

    event.listen(
        engine,
        "before_cursor_execute",
        pause_before_compensation_requeue,
    )
    limiter = ConcurrencyLimiter(max_concurrent=1)
    ingestion_jobs.release_all_operation_leases()
    ingestion_jobs.retain_operation_lease(
        job_id,
        limiter.acquire("ingest:user"),
    )

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=worker_session_factory,
            processor=processor,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await asyncio.to_thread(compensation_read.wait, 1)

            def delete_document_and_job():
                with setup_session_factory() as db:
                    document = db.get(
                        models.Document,
                        "document-delete-during-compensation",
                    )
                    db.delete(document)
                    db.commit()

            await asyncio.to_thread(delete_document_and_job)
            allow_compensation.set()
            deadline = asyncio.get_running_loop().time() + 1
            while (
                limiter.active("ingest:user") != 0
                and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.01)
            assert limiter.active("ingest:user") == 0
            with setup_session_factory() as db:
                assert db.get(models.IngestionJob, job_id) is None
                assert db.query(models.Chunk).count() == 0
                assert db.query(models.Embedding).count() == 0
        finally:
            allow_compensation.set()
            await worker.stop()

    try:
        asyncio.run(scenario())
    finally:
        allow_compensation.set()
        ingestion_jobs.release_all_operation_leases()
        event.remove(
            engine,
            "before_cursor_execute",
            pause_before_compensation_requeue,
        )


def test_stop_cleans_global_state_after_unexpected_supervisor_failure(
    job_database,
    monkeypatch,
):
    """A failed supervisor cannot strand its global worker or quota lease.

    Args:
        job_database: Isolated file database fixture.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    _, session_factory = job_database
    limiter = ConcurrencyLimiter(max_concurrent=1)
    ingestion_jobs.release_all_operation_leases()
    ingestion_jobs.retain_operation_lease(
        "unexpected-supervisor-job",
        limiter.acquire("ingest:user"),
    )

    async def scenario():
        worker = ingestion_jobs.IngestionJobWorker(
            session_factory=session_factory,
            processor=lambda _db, _job: None,
            poll_interval=0.01,
        )

        async def fail_supervisor():
            raise RuntimeError("unexpected supervisor failure")

        monkeypatch.setattr(worker, "_run", fail_supervisor)
        await worker.start()
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="unexpected supervisor failure"):
            await worker.stop()
        assert worker._task is None
        assert worker._loop is None
        assert ingestion_jobs._active_worker is not worker

    try:
        asyncio.run(scenario())
        assert limiter.active("ingest:user") == 0
    finally:
        ingestion_jobs.release_all_operation_leases()
