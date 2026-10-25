"""Durable claim and lifespan behavior for audio overview work."""
import asyncio

from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from app.db.models import AudioOverview, Base, Project
from app.services.audio_overview_jobs import (
    AudioOverviewWorker,
    claim_next_audio_overview,
    recover_abandoned_audio_overviews,
)


def database(tmp_path):
    engine = create_engine(
        "sqlite:///%s" % (tmp_path / "audio-jobs.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(Project(id="audio-project", name="Project"))
        db.add(AudioOverview(
            id="audio-job",
            project_id="audio-project",
            options_json={},
            script_json=[],
        ))
        db.commit()
    return engine, sessions


def test_claim_is_atomic_and_startup_recovers_running_rows(tmp_path):
    engine, sessions = database(tmp_path)
    try:
        assert claim_next_audio_overview(sessions) == "audio-job"
        assert claim_next_audio_overview(sessions) is None
        with sessions() as db:
            assert db.get(AudioOverview, "audio-job").status == "running"

        recover_abandoned_audio_overviews(sessions)
        with sessions() as db:
            assert db.get(AudioOverview, "audio-job").status == "queued"
    finally:
        engine.dispose()


def test_worker_runs_claimed_work_and_drains_on_stop(tmp_path):
    engine, sessions = database(tmp_path)

    def finish(overview_id):
        with sessions() as db:
            db.execute(
                update(AudioOverview)
                .where(AudioOverview.id == overview_id)
                .values(status="ready")
            )
            db.commit()

    async def run():
        worker = AudioOverviewWorker(sessions, processor=finish, poll_interval=0.01)
        await worker.start()
        for _ in range(200):
            with sessions() as db:
                if db.get(AudioOverview, "audio-job").status == "ready":
                    break
            await asyncio.sleep(0.01)
        await worker.stop()

    try:
        asyncio.run(run())
        with sessions() as db:
            assert db.get(AudioOverview, "audio-job").status == "ready"
    finally:
        engine.dispose()
