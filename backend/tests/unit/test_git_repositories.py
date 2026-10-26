from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base, Document, GitRepository, IngestionJob, Project, ProjectDocument
from app.services import git_repositories
from app.services import document_files
from app.services.git_repositories import (
    GitRepositoryLimitError,
    GitRepositoryUnavailableError,
    GitRepositoryService,
    parse_git_tree,
    validate_git_url,
)


@pytest.fixture
def git_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        project = Project(id="project-1", name="Git sources", user_id="user-1")
        db.add(project)
        db.commit()
        yield db, project
    engine.dispose()


def tree_entry(path, oid, size, mode="100644", kind="blob"):
    return {
        "path": path,
        "oid": oid,
        "size": size,
        "mode": mode,
        "kind": kind,
    }


def test_validate_git_url_requires_public_https_without_credentials(monkeypatch):
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )

    assert validate_git_url("https://github.com/org/repo.git")[0] == (
        "https://github.com/org/repo.git"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_git_url("http://github.com/org/repo.git")
    with pytest.raises(ValueError, match="credentials"):
        validate_git_url("https://user:secret@github.com/org/repo.git")


def test_parse_git_tree_skips_non_regular_files_and_obsidian_settings():
    raw = (
        b"100644 blob " + b"a" * 40 + b"\tREADME.md\0"
        b"100755 blob " + b"b" * 40 + b"\tsrc/main.py\0"
        b"120000 blob " + b"c" * 40 + b"\tlinked.md\0"
        b"160000 commit " + b"d" * 40 + b"\tmodules/child\0"
        b"100644 blob " + b"e" * 40 + b"\t.obsidian/config.md\0"
        b"100644 blob " + b"f" * 40 + b"\timage.png\0"
        b"100644 blob " + b"1" * 40 + b"\t../outside.md\0"
    )

    assert parse_git_tree(raw) == [
        tree_entry("README.md", "a" * 40, None),
        tree_entry("src/main.py", "b" * 40, None, mode="100755"),
    ]


def test_git_process_pins_dns_and_keeps_token_out_of_arguments(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "app-process-secret")
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "1")
    monkeypatch.setenv("GIT_TRACE2_EVENT", "/tmp/git-trace")
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda _url: ("https://github.com/org/repo.git", ["93.184.216.34"]),
    )
    calls = []

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))

        def poll(self):
            return self.returncode

        def wait(self, **_kwargs):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(git_repositories.subprocess, "Popen", Process)
    service = GitRepositoryService(Settings())
    with service._open_remote(
        "https://github.com/org/repo.git",
        "one-time-token",
    ):
        pass

    args, options = calls[0]
    environment = options["env"]
    config = {
        environment["GIT_CONFIG_KEY_%s" % index]: environment[
            "GIT_CONFIG_VALUE_%s" % index
        ]
        for index in range(int(environment["GIT_CONFIG_COUNT"]))
    }
    assert "--depth=1" in args
    assert "--filter=blob:none" in args
    assert "one-time-token" not in " ".join(args)
    assert "one-time-token" not in config["http.extraheader"]
    assert "OPENAI_API_KEY" not in environment
    assert "GIT_SSL_NO_VERIFY" not in environment
    assert "GIT_TRACE2_EVENT" not in environment
    assert config["http.curloptResolve"] == "github.com:443:93.184.216.34"
    assert config["http.followRedirects"] == "false"
    assert config["http.sslVerify"] == "true"
    assert config["protocol.allow"] == "never"
    assert config["protocol.https.allow"] == "always"


def test_blob_reader_stops_at_the_per_file_limit(monkeypatch, tmp_path):
    class Process:
        def __init__(self):
            self.stdout = BytesIO(b"12345")
            self.returncode = None
            self.killed = False

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, **_kwargs):
            self.returncode = self.returncode or 0
            return self.returncode

        def poll(self):
            return self.returncode

    process = Process()
    monkeypatch.setattr(git_repositories.subprocess, "Popen", lambda *_args, **_kwargs: process)

    with pytest.raises(GitRepositoryLimitError, match="file size limit"):
        GitRepositoryService(Settings())._read_blob(
            tmp_path,
            "a" * 40,
            {},
            max_bytes=4,
        )

    assert process.killed is True


def test_blob_reader_kills_a_git_process_that_stalls(monkeypatch, tmp_path):
    class Process:
        def __init__(self):
            self.returncode = None
            self.killed = False
            self.reads = 0

            class SlowStream:
                def read(inner_self, _size):
                    if self.reads:
                        return b""
                    time.sleep(0.05)
                    self.reads += 1
                    return b"x"

                def close(inner_self):
                    pass

            self.stdout = SlowStream()

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, **_kwargs):
            self.returncode = self.returncode or 0
            return self.returncode

    process = Process()
    monkeypatch.setattr(git_repositories, "GIT_BLOB_READ_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(git_repositories.subprocess, "Popen", lambda *_args, **_kwargs: process)

    with pytest.raises(GitRepositoryUnavailableError, match="timed out"):
        GitRepositoryService(Settings())._read_blob(
            tmp_path,
            "a" * 40,
            {},
            max_bytes=4,
        )

    assert process.killed is True


class SnapshotGitRepositoryService(GitRepositoryService):
    def __init__(self, settings, snapshots):
        super().__init__(settings)
        self.snapshots = snapshots
        self.read_oids = []
        self.read_limits = []
        self.received_tokens = []

    @contextmanager
    def _open_remote(self, url, token):
        self.received_tokens.append(token)
        yield Path("/fake/repo"), {}

    def _list_tree(self, _repository_path, _environment, _include_glob, _exclude_glob):
        return self.snapshots[0][0], self.snapshots[0][1]

    def _read_blob(self, _repository_path, oid, _environment, max_bytes):
        self.read_oids.append(oid)
        self.read_limits.append(max_bytes)
        content = self.snapshots[0][2][oid]
        if len(content) > max_bytes:
            raise GitRepositoryLimitError("Repository file exceeds the configured file size limit")
        return content

    def advance(self):
        self.snapshots.pop(0)


def test_import_sync_and_limits_use_durable_jobs_without_storing_token(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(document_files, "UPLOAD_DIR", upload_dir)
    markdown_v1 = b"---\ntitle: Start\n---\nFirst version"
    markdown_v2 = b"---\ntitle: Start\n---\nUpdated version"
    first_oid = "a" * 40
    second_oid = "b" * 40
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=1, max_git_repo_files=4),
        [
            (
                "commit-1",
                [
                    tree_entry("welcome.md", first_oid, len(markdown_v1)),
                    tree_entry("private/draft.md", "c" * 40, 6),
                ],
                {first_oid: markdown_v1},
            ),
            (
                "commit-2",
                [tree_entry("welcome.md", second_oid, len(markdown_v2))],
                {second_oid: markdown_v2},
            ),
        ],
    )

    repository, initial = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
        include_glob="**/*.md",
        exclude_glob="private/**",
        token="short-lived-token",
    )
    db.commit()
    document = db.query(Document).one()
    document_id = document.id
    old_path = Path(document.source_url)
    assert initial["added"] == 1
    assert document.source_url and old_path.read_bytes() == markdown_v1
    assert db.query(ProjectDocument).count() == 1
    first_job = db.query(IngestionJob).one()
    assert first_job.job_type == "file"
    first_job.status = "completed"
    document.status = "ready"
    db.commit()

    service.advance()
    updated, changes = service.sync_repository(
        db,
        project,
        repository,
        token="short-lived-token",
    )
    db.commit()
    db.refresh(document)
    assert updated.id == repository.id
    assert document.id == document_id == db.query(Document).one().id
    assert changes["updated"] == 1
    assert document.source_url != str(old_path)
    assert Path(document.source_url).read_bytes() == markdown_v2
    assert not old_path.exists()
    assert sorted(job.job_type for job in db.query(IngestionJob).all()) == ["file", "resync"]
    assert service.received_tokens == ["short-lived-token", "short-lived-token"]
    assert "short-lived-token" not in str(repository.manifest_json)
    assert "token" not in GitRepository.__table__.columns


def test_blob_reads_finish_before_reserving_sqlite_writer(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", tmp_path / "uploads")
    oid = "a" * 40
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=1),
        [("commit", [tree_entry("note.md", oid, 4)], {oid: b"note"})],
    )
    reserve = git_repositories._reserve_sqlite_enqueue_transaction

    def reserve_after_download(session):
        assert service.read_oids, "remote file I/O must finish before reserving SQLite's writer"
        reserve(session)

    monkeypatch.setattr(
        git_repositories,
        "_reserve_sqlite_enqueue_transaction",
        reserve_after_download,
    )

    repository, counts = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
    )

    assert repository.head_commit == "commit"
    assert counts["added"] == 1


def test_import_accepts_tree_entries_without_reported_blob_sizes(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", upload_dir)
    content = b"# Note\nBody"
    oid = "a" * 40
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=1),
        [("commit", [tree_entry("note.md", oid, None)], {oid: content})],
    )

    repository, counts = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
    )

    assert counts["added"] == 1
    assert repository.head_commit == "commit"
    assert Path(db.query(Document).one().source_url).read_bytes() == content


@pytest.mark.parametrize(
    "entries,limit,match",
    [
        (
            [tree_entry("one.md", "a" * 40, 1), tree_entry("two.md", "b" * 40, 1)],
            1,
            "file count",
        ),
        ([tree_entry("large.md", "a" * 40, 1_048_577)], 4, "file size"),
    ],
)
def test_repository_limits_fail_before_persisting_sources(
    git_db,
    monkeypatch,
    tmp_path,
    entries,
    limit,
    match,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", upload_dir)
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=1, max_git_repo_files=limit),
        [("commit", entries, {})],
    )

    with pytest.raises(GitRepositoryLimitError, match=match):
        service.import_repository(
            db,
            project,
            "https://github.com/org/repo.git",
            include_glob="**/*.md",
            exclude_glob="",
            token=None,
        )

    assert db.query(GitRepository).count() == 0
    assert db.query(Document).count() == 0
    assert db.query(IngestionJob).count() == 0
    assert not upload_dir.exists()
    assert service.read_oids == []


def test_sync_marks_removed_paths_and_can_reimport_the_same_document_id(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(document_files, "UPLOAD_DIR", upload_dir)

    class RetrievalIndex:
        def delete_document(self, _db, _document_id):
            pass

    monkeypatch.setattr(
        git_repositories,
        "get_retrieval_index",
        lambda: RetrievalIndex(),
    )
    content = b"# Note\nBody"
    oid = "a" * 40
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=1),
        [
            ("commit-1", [tree_entry("note.md", oid, len(content))], {oid: content}),
            ("commit-2", [], {}),
            ("commit-3", [tree_entry("note.md", oid, len(content))], {oid: content}),
        ],
    )
    repository, _ = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
        token=None,
    )
    document = db.query(Document).one()
    document_id = document.id
    job = db.query(IngestionJob).one()
    job.status = "completed"
    document.status = "ready"
    db.commit()

    service.advance()
    _, removed = service.sync_repository(db, project, repository)
    assert removed["removed"] == 1
    assert document.status == "error"
    assert document.error_message == "This file was removed from the Git repository."
    assert repository.manifest_json["note.md"]["removed"] is True

    service.advance()
    _, restored = service.sync_repository(db, project, repository)
    assert restored["updated"] == 1
    assert document.id == document_id
    assert document.error_message is None
    assert repository.manifest_json["note.md"]["removed"] is False


def test_sync_does_not_update_a_source_moved_out_of_its_project(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", tmp_path / "uploads")
    first = b"old"
    updated = b"new content"
    first_oid = "a" * 40
    updated_oid = "b" * 40
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=1),
        [
            ("commit-1", [tree_entry("note.md", first_oid, len(first))], {first_oid: first}),
            ("commit-2", [tree_entry("note.md", updated_oid, len(updated))], {updated_oid: updated}),
        ],
    )
    repository, _ = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
    )
    original = db.query(Document).one()
    original_id = original.id
    db.query(ProjectDocument).filter(
        ProjectDocument.project_id == project.id,
        ProjectDocument.document_id == original.id,
    ).delete()
    other_project = Project(id="other-project", name="Other", user_id="user-1")
    db.add(other_project)
    db.add(ProjectDocument(
        project_id=other_project.id,
        document_id=original.id,
        shared_by_user_id="user-1",
    ))
    first_job = db.query(IngestionJob).one()
    first_job.status = "completed"
    db.commit()

    service.advance()
    _, counts = service.sync_repository(db, project, repository)

    assert counts["added"] == 1
    assert counts["updated"] == 0
    assert original.id == original_id
    assert original.source_url.endswith("_" + first_oid[:12] + ".md")
    assert db.query(Document).count() == 2
    assert repository.manifest_json["note.md"]["document_id"] != original_id


def test_sync_unlinks_removed_git_source_without_breaking_a_shared_project_source(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(document_files, "UPLOAD_DIR", upload_dir)
    removed_from_index = []

    class RetrievalIndex:
        def delete_document(self, _db, document_id):
            removed_from_index.append(document_id)

    monkeypatch.setattr(
        git_repositories,
        "get_retrieval_index",
        lambda: RetrievalIndex(),
    )
    content = b"# Note\nBody"
    oid = "a" * 40
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=1),
        [
            ("commit-1", [tree_entry("note.md", oid, len(content))], {oid: content}),
            ("commit-2", [], {}),
        ],
    )
    repository, _ = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
    )
    document = db.query(Document).one()
    document.status = "ready"
    job = db.query(IngestionJob).one()
    job.status = "completed"
    other_project = Project(id="other-project", name="Other", user_id="user-1")
    db.add(other_project)
    db.add(ProjectDocument(
        project_id=other_project.id,
        document_id=document.id,
        shared_by_user_id="user-1",
    ))
    db.commit()

    service.advance()
    _, counts = service.sync_repository(db, project, repository)

    assert counts["removed"] == 1
    assert document.status == "ready"
    assert Path(document.source_url).is_file()
    assert db.query(ProjectDocument).filter_by(
        project_id=project.id,
        document_id=document.id,
    ).count() == 0
    assert db.query(ProjectDocument).filter_by(
        project_id=other_project.id,
        document_id=document.id,
    ).count() == 1
    assert removed_from_index == []
    assert repository.manifest_json["note.md"]["removed"] is True


def test_clone_stops_when_the_downloaded_pack_exceeds_its_limit(monkeypatch):
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    service = GitRepositoryService(SimpleNamespace(
        max_file_size_bytes=10,
        max_git_repo_files=5,
        max_git_repo_size_bytes=1,
    ))
    killed = []

    def fake_run(args, **_kwargs):
        repository_path = Path(args[-1])
        pack_dir = repository_path / ".git" / "objects" / "pack"
        pack_dir.mkdir(parents=True)
        (pack_dir / "tmp_pack").write_bytes(b"too large")
        return git_repositories.subprocess.CompletedProcess(args, 0, b"", b"")

    class Process:
        def __init__(self, args, **_kwargs):
            repository_path = Path(args[-1])
            pack_dir = repository_path / ".git" / "objects" / "pack"
            pack_dir.mkdir(parents=True)
            (pack_dir / "tmp_pack").write_bytes(b"too large")
            self.returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            killed.append(True)
            self.returncode = -9

        def wait(self, **_kwargs):
            return self.returncode

    monkeypatch.setattr(git_repositories.subprocess, "Popen", Process)
    monkeypatch.setattr(git_repositories.subprocess, "run", fake_run)

    with pytest.raises(GitRepositoryLimitError, match="download exceeds"):
        with service._open_remote("https://github.com/org/repo.git", None):
            pass

    assert killed == [True]


def test_sync_enforces_total_size_for_unchanged_and_new_files(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(document_files, "UPLOAD_DIR", upload_dir)
    first_content = b"a" * 600_000
    second_content = b"b" * 500_000
    first_oid = "a" * 40
    second_oid = "b" * 40
    service = SnapshotGitRepositoryService(
        SimpleNamespace(
            max_file_size_bytes=1_048_576,
            max_git_repo_files=10,
            max_git_repo_size_mb=1,
            max_git_repo_size_bytes=1_048_576,
        ),
        [
            ("commit-1", [tree_entry("note.md", first_oid, None)], {first_oid: first_content}),
            (
                "commit-2",
                [
                    tree_entry("note.md", first_oid, None),
                    tree_entry("new.md", second_oid, None),
                ],
                {second_oid: second_content},
            ),
        ],
    )
    repository, _ = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
    )
    document = db.query(Document).one()
    job = db.query(IngestionJob).one()
    job.status = "completed"
    document.status = "ready"
    db.commit()

    service.advance()
    with pytest.raises(GitRepositoryLimitError, match="total file size limit"):
        service.sync_repository(db, project, repository)

    assert db.query(Document).count() == 1
    assert db.query(IngestionJob).count() == 1
    assert list(upload_dir.iterdir()) == [Path(document.source_url)]


def test_sync_retries_a_failed_import_when_the_blob_has_not_changed(
    git_db,
    monkeypatch,
    tmp_path,
):
    db, project = git_db
    monkeypatch.setattr(
        git_repositories,
        "resolve_public_http_url",
        lambda url: (url, ["93.184.216.34"]),
    )
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(git_repositories, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(document_files, "UPLOAD_DIR", upload_dir)
    content = b"x" * 1_048_576
    oid = "a" * 40
    service = SnapshotGitRepositoryService(
        Settings(max_file_size_mb=2, max_git_repo_size_mb=1),
        [("commit", [tree_entry("note.md", oid, None)], {oid: content})],
    )
    repository, _ = service.import_repository(
        db,
        project,
        "https://github.com/org/repo.git",
    )
    document = db.query(Document).one()
    first_job = db.query(IngestionJob).one()
    first_job.status = "failed"
    document.status = "error"
    document.error_message = "embedding failed"
    db.commit()

    _, counts = service.sync_repository(db, project, repository)

    jobs = db.query(IngestionJob).order_by(IngestionJob.created_at, IngestionJob.id).all()
    assert counts["updated"] == 1
    assert counts["unchanged"] == 0
    assert document.error_message is None
    assert [(job.job_type, job.status) for job in jobs] == [
        ("file", "failed"),
        ("resync", "queued"),
    ]
