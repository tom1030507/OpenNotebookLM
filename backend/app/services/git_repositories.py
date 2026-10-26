"""Import selected regular files from HTTPS Git repositories."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import urlsplit

import structlog
from sqlalchemy.orm import Session

from app.adapters.office import SUPPORTED_CODE_EXTENSIONS
from app.config import Settings, get_settings
from app.db.models import (
    Chunk,
    Document,
    GitRepository,
    IngestionJob,
    Project,
    ProjectDocument,
)
from app.services.document_files import UPLOAD_DIR, resolve_stored_file
from app.services.ingestion_jobs import (
    ACTIVE_JOB_STATUSES,
    _reserve_sqlite_enqueue_transaction,
    enqueue_ingestion_job_with_result,
    notify_ingestion_worker,
)
from app.services.retrieval_index import get_retrieval_index
from app.utils.network import UnsafeURLError, resolve_public_http_url
from app.utils.time import utc_now

logger = structlog.get_logger()
DEFAULT_INCLUDE_GLOB = "**/*"
SUPPORTED_REPOSITORY_EXTENSIONS = frozenset({".md", ".txt", *SUPPORTED_CODE_EXTENSIONS})
_GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40,64}$")
_REMOVED_MESSAGE = "This file was removed from the Git repository."
MAX_GIT_TREE_OUTPUT_BYTES = 64 * 1024 * 1024
GIT_BLOB_READ_TIMEOUT_SECONDS = 60
# shortcut: skip trees above 64 MiB of metadata; raise this if very large file lists are needed.


class GitRepositoryLimitError(ValueError):
    """Raised when a selected repository exceeds a configured import cap."""


class GitRepositoryUnavailableError(RuntimeError):
    """Raised when Git cannot fetch or read the remote repository."""


class GitRepositoryConflictError(RuntimeError):
    """Raised when the project already tracks the requested remote URL."""


def validate_git_url(url: str) -> tuple[str, list[str]]:
    """Require a credential-free HTTPS URL that resolves only to public IPs.

    Args:
        url: User-supplied HTTPS Git remote.

    Returns:
        The normalized URL and its validated public IP addresses.

    Raises:
        ValueError: If the URL is malformed, unsafe, or not HTTPS.
    """
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise ValueError("Enter a valid Git repository URL")
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() != "https":
            raise ValueError("Git repository URLs must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Git repository URL credentials are not allowed")
        if parsed.query or parsed.fragment:
            raise ValueError("Git repository URLs cannot include a query or fragment")
        return resolve_public_http_url(url.strip())
    except UnsafeURLError as error:
        raise ValueError(str(error)) from error
    except (TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("Git repository"):
            raise
        raise ValueError("Enter a valid Git repository URL") from error


def parse_git_tree(raw: bytes) -> list[dict]:
    """Keep safe, supported regular blobs from ``git ls-tree -r -z`` output.

    Args:
        raw: NUL-delimited output from ``git ls-tree -r -z``.

    Returns:
        Supported source entries with path, object id, mode, and type.
    """
    entries = []
    for record in raw.split(b"\0"):
        if not record or b"\t" not in record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        try:
            mode, kind, oid = metadata.decode("ascii").split()
            path = path_bytes.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        relative_path = PurePosixPath(path)
        if (
            kind != "blob"
            or mode not in {"100644", "100755"}
            or not _GIT_OBJECT_ID.fullmatch(oid)
            or relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or ".obsidian" in relative_path.parts
            or relative_path.suffix.lower() not in SUPPORTED_REPOSITORY_EXTENSIONS
        ):
            continue
        entries.append({
            "path": path,
            "oid": oid,
            "size": None,
            "mode": mode,
            "kind": kind,
        })
    return entries


def matches_git_glob(path: str, pattern: str) -> bool:
    """Match a repository-relative path, including root files for ``**/``.

    Args:
        path: POSIX path stored in the Git tree.
        pattern: One pathlib-style glob.

    Returns:
        Whether the path matches the glob.
    """
    target = PurePosixPath(path)
    return target.match(pattern) or (
        pattern.startswith("**/") and target.match(pattern[3:])
    )


def git_environment(
    url: str,
    addresses: list[str],
    token: str | None,
    temporary_directory: str,
) -> dict[str, str]:
    """Build an ephemeral Git environment with HTTPS and pinned DNS settings.

    Args:
        url: Already validated remote URL.
        addresses: Public IPs returned by the URL validator.
        token: Optional access token used for this operation only.
        temporary_directory: Private directory used for HOME and temp files.

    Returns:
        Child process environment; secrets are not stored in a file or argv.
    """
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    port = parsed.port or 443
    address = addresses[0]
    if ":" in address:
        address = "[%s]" % address
    config = [
        ("http.curloptResolve", "%s:%s:%s" % (hostname, port, address)),
        ("http.followRedirects", "false"),
        ("http.proxy", ""),
        ("http.sslVerify", "true"),
        ("protocol.allow", "never"),
        ("protocol.https.allow", "always"),
        ("core.hooksPath", os.devnull),
        ("http.lowSpeedLimit", "1000"),
        ("http.lowSpeedTime", "30"),
    ]
    if token:
        auth = base64.b64encode(
            ("x-access-token:" + token).encode("utf-8")
        ).decode("ascii")
        config.append(("http.extraheader", "AUTHORIZATION: basic " + auth))

    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": temporary_directory,
        "TMPDIR": temporary_directory,
        "TEMP": temporary_directory,
        "TMP": temporary_directory,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": str(len(config)),
    }
    for name in (
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "CURL_CA_BUNDLE",
        "SYSTEMROOT",
        "WINDIR",
    ):
        if name in os.environ:
            environment[name] = os.environ[name]
    for index, (key, value) in enumerate(config):
        environment["GIT_CONFIG_KEY_%s" % index] = key
        environment["GIT_CONFIG_VALUE_%s" % index] = value
    return environment


class GitRepositoryService:
    """Clone a shallow remote snapshot and queue selected files as sources."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Use the supplied or process-wide repository size limits.

        Args:
            settings: Optional settings with Git and per-file caps.

        Returns:
            None.
        """
        self.settings = settings or get_settings()

    def import_repository(
        self,
        db: Session,
        project: Project,
        url: str,
        include_glob: str = DEFAULT_INCLUDE_GLOB,
        exclude_glob: str = "",
        token: str | None = None,
    ) -> tuple[GitRepository, dict]:
        """Create and import a project-scoped repository source.

        Args:
            db: Database transaction for the source and durable jobs.
            project: Authorized project receiving the sources.
            url: HTTPS Git remote.
            include_glob: One glob applied to repository-relative paths.
            exclude_glob: Optional glob that takes precedence over inclusion.
            token: Optional token, discarded after this request.

        Returns:
            The new repository and import counts.
        """
        normalized_url, _addresses = validate_git_url(url)
        include_glob = self._validate_glob(include_glob or DEFAULT_INCLUDE_GLOB)
        exclude_glob = self._validate_glob(exclude_glob or "")
        if db.query(GitRepository.id).filter(
            GitRepository.project_id == project.id,
            GitRepository.url == normalized_url,
        ).first():
            raise GitRepositoryConflictError("This repository is already connected")
        repository = GitRepository(
            id=str(uuid.uuid4()),
            project_id=project.id,
            url=normalized_url,
            include_glob=include_glob,
            exclude_glob=exclude_glob,
            manifest_json={},
        )
        counts = self._sync(db, project, repository, token, is_new=True)
        return repository, counts

    def sync_repository(
        self,
        db: Session,
        project: Project,
        repository: GitRepository,
        token: str | None = None,
    ) -> tuple[GitRepository, dict]:
        """Fetch the latest shallow snapshot and queue changed source blobs.

        Args:
            db: Database transaction for the source and durable jobs.
            project: Authorized project that owns the repository.
            repository: Repository already scoped to that project.
            token: Optional token, discarded after this request.

        Returns:
            The repository and counts for changed, unchanged, and removed files.
        """
        if repository.project_id != project.id:
            raise ValueError("Git repository not found")
        return repository, self._sync(db, project, repository, token, is_new=False)

    @staticmethod
    def _load_sync_state(
        db: Session,
        project: Project,
        repository: GitRepository,
        is_new: bool,
    ) -> dict:
        """Load the database snapshot used to plan a repository sync.

        Args:
            db: Database session.
            project: Project that owns the repository.
            repository: Repository being imported or synchronized.
            is_new: Whether this operation creates the repository row.

        Returns:
            Manifest, linked documents, job state, and a concurrency fingerprint.
        """
        if is_new:
            if db.query(GitRepository.id).filter(
                GitRepository.project_id == project.id,
                GitRepository.url == repository.url,
            ).first():
                raise GitRepositoryConflictError("This repository is already connected")
            manifest = dict(repository.manifest_json or {})
        else:
            current = db.query(GitRepository).populate_existing().filter(
                GitRepository.id == repository.id,
                GitRepository.project_id == project.id,
            ).first()
            if current is None:
                raise GitRepositoryConflictError(
                    "Repository changed during sync; try again"
                )
            manifest = dict(current.manifest_json or {})

        previous_ids = {
            item.get("document_id")
            for item in manifest.values()
            if isinstance(item, dict) and item.get("document_id")
        }
        linked_ids = {
            row[0]
            for row in db.query(ProjectDocument.document_id).filter(
                ProjectDocument.project_id == project.id,
                ProjectDocument.document_id.in_(previous_ids or {""}),
            ).all()
        }
        shared_ids = {
            row[0]
            for row in db.query(ProjectDocument.document_id).filter(
                ProjectDocument.project_id != project.id,
                ProjectDocument.document_id.in_(linked_ids or {""}),
            ).all()
        }
        tracked = {
            document.id: document
            for document in db.query(Document).populate_existing().filter(
                Document.id.in_(linked_ids or {""})
            ).all()
        }
        active_ids = {
            row[0]
            for row in db.query(IngestionJob.document_id).filter(
                IngestionJob.document_id.in_(previous_ids or {""}),
                IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
            ).all()
        }
        latest_source_jobs = {}
        for document_id, status in db.query(
            IngestionJob.document_id,
            IngestionJob.status,
        ).filter(
            IngestionJob.document_id.in_(previous_ids or {""}),
            IngestionJob.job_type.in_(("file", "resync")),
            IngestionJob.status.in_(("completed", "failed")),
        ).order_by(
            IngestionJob.created_at.desc(),
            IngestionJob.id.desc(),
        ).all():
            latest_source_jobs.setdefault(document_id, status)
        failed_ids = {
            document_id
            for document_id, status in latest_source_jobs.items()
            if status == "failed"
        }
        document_state = tuple(
            (
                document.id,
                document.deleted_at,
                document.source_url,
                document.status,
                document.error_message,
                document.title,
                document.meta_json,
            )
            for document in sorted(tracked.values(), key=lambda item: item.id)
        )
        signature = (
            repository.head_commit,
            repository.url,
            repository.include_glob,
            repository.exclude_glob,
            manifest,
            frozenset(linked_ids),
            frozenset(shared_ids),
            frozenset(active_ids),
            frozenset(failed_ids),
            document_state,
        )
        return {
            "manifest": manifest,
            "tracked": tracked,
            "shared_ids": shared_ids,
            "active_ids": active_ids,
            "failed_ids": failed_ids,
            "signature": signature,
        }

    def _sync(
        self,
        db: Session,
        project: Project,
        repository: GitRepository,
        token: str | None,
        is_new: bool,
    ) -> dict:
        include_glob = repository.include_glob or DEFAULT_INCLUDE_GLOB
        exclude_glob = repository.exclude_glob or ""
        staged_files = []
        installed_files = []
        staged_by_path = {}
        old_files = []
        target_files = set()
        queued = 0
        total_file_bytes = 0
        counts = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0}
        commit_attempted = False
        try:
            initial_state = self._load_sync_state(db, project, repository, is_new)
            include_glob = repository.include_glob or DEFAULT_INCLUDE_GLOB
            exclude_glob = repository.exclude_glob or ""
            with self._open_remote(repository.url, token) as (repository_path, environment):
                head_commit, entries = self._list_tree(
                    repository_path,
                    environment,
                    include_glob,
                    exclude_glob,
                )
                selected = [
                    entry for entry in entries
                    if matches_git_glob(entry["path"], include_glob)
                    and not (exclude_glob and matches_git_glob(entry["path"], exclude_glob))
                ]
                if len(selected) > self.settings.max_git_repo_files:
                    raise GitRepositoryLimitError(
                        "Repository selects more than the configured file count limit (%s)"
                        % self.settings.max_git_repo_files
                    )
                for entry in selected:
                    if (
                        entry["size"] is not None
                        and entry["size"] > self.settings.max_file_size_bytes
                    ):
                        raise GitRepositoryLimitError(
                            "Repository file exceeds the configured file size limit: %s"
                            % entry["path"]
                        )
                if not selected and is_new:
                    raise ValueError("No supported files matched the repository glob")

                manifest = initial_state["manifest"]
                tracked = initial_state["tracked"]
                active_ids = initial_state["active_ids"]
                failed_ids = initial_state["failed_ids"]
                staged_total_bytes = 0
                for entry in selected:
                    path = entry["path"]
                    previous = manifest.get(path)
                    previous = previous if isinstance(previous, dict) else {}
                    document = tracked.get(previous.get("document_id"))
                    if document is not None and document.deleted_at is not None:
                        continue
                    same_blob = (
                        document is not None
                        and previous.get("oid") == entry["oid"]
                        and not previous.get("removed")
                    )
                    if same_blob and (
                        document.id in active_ids or document.id not in failed_ids
                    ):
                        size = previous.get("size")
                        if not isinstance(size, int):
                            size = (document.meta_json or {}).get("file_size")
                        if isinstance(size, int):
                            if size > self.settings.max_file_size_bytes:
                                raise GitRepositoryLimitError(
                                    "Repository file exceeds the configured file size limit: %s"
                                    % path
                                )
                            staged_total_bytes += size
                            if staged_total_bytes > self.settings.max_git_repo_size_bytes:
                                raise GitRepositoryLimitError(
                                    "Repository exceeds the configured total file size limit (%s MB)"
                                    % self.settings.max_git_repo_size_mb
                                )
                    if document is not None and document.id in active_ids:
                        continue
                    if same_blob and document.id not in failed_ids:
                        continue

                    remaining_bytes = (
                        self.settings.max_git_repo_size_bytes - staged_total_bytes
                    )
                    read_limit = min(self.settings.max_file_size_bytes, remaining_bytes)
                    try:
                        content = self._read_blob(
                            repository_path,
                            entry["oid"],
                            environment,
                            read_limit,
                        )
                    except GitRepositoryLimitError as error:
                        if remaining_bytes < self.settings.max_file_size_bytes:
                            raise GitRepositoryLimitError(
                                "Repository exceeds the configured total file size limit (%s MB)"
                                % self.settings.max_git_repo_size_mb
                            ) from error
                        raise
                    if entry["size"] is not None and len(content) != entry["size"]:
                        raise GitRepositoryUnavailableError(
                            "Git returned a file with an inconsistent size"
                        )
                    staged_total_bytes += len(content)
                    document_id = document.id if document is not None else str(uuid.uuid4())
                    extension = PurePosixPath(path).suffix.lower()
                    target = UPLOAD_DIR / (
                        "%s_%s%s" % (document_id, entry["oid"][:12], extension)
                    )
                    staged_path = UPLOAD_DIR / (".git-source-stage-%s" % uuid.uuid4().hex)
                    self._write_blob(staged_path, content)
                    staged_files.append(staged_path)
                    staged_by_path[path] = (document_id, target, len(content), staged_path)
                    target_files.add(target.resolve())

                _reserve_sqlite_enqueue_transaction(db)
                current_state = self._load_sync_state(db, project, repository, is_new)
                if current_state["signature"] != initial_state["signature"]:
                    raise GitRepositoryConflictError(
                        "Repository changed while files were being staged; try syncing again"
                    )
                manifest = current_state["manifest"]
                tracked = current_state["tracked"]
                shared_ids = current_state["shared_ids"]
                active_ids = current_state["active_ids"]
                failed_ids = current_state["failed_ids"]
                total_file_bytes = 0
                new_manifest = {}
                selected_paths = {entry["path"] for entry in selected}

                for path, previous in manifest.items():
                    if path in selected_paths or not isinstance(previous, dict):
                        continue
                    document = tracked.get(previous.get("document_id"))
                    if document is None or document.deleted_at is not None:
                        continue
                    if document.id in active_ids:
                        new_manifest[path] = previous
                        continue
                    if document.id in shared_ids:
                        db.query(ProjectDocument).filter(
                            ProjectDocument.project_id == project.id,
                            ProjectDocument.document_id == document.id,
                        ).delete(synchronize_session=False)
                        counts["removed"] += 1
                        new_manifest[path] = {**previous, "removed": True}
                        continue
                    if not previous.get("removed"):
                        get_retrieval_index().delete_document(db, document.id)
                        for chunk in db.query(Chunk).filter(
                            Chunk.document_id == document.id
                        ).all():
                            db.delete(chunk)
                        document.status = "error"
                        document.error_message = _REMOVED_MESSAGE
                        document.last_synced_at = utc_now()
                        document.last_sync_changed = True
                        counts["removed"] += 1
                    new_manifest[path] = {**previous, "removed": True}

                for entry in selected:
                    path = entry["path"]
                    previous = manifest.get(path)
                    previous = previous if isinstance(previous, dict) else {}
                    document = tracked.get(previous.get("document_id"))
                    if document is not None and document.deleted_at is not None:
                        new_manifest[path] = previous
                        continue
                    same_blob = (
                        document is not None
                        and previous.get("oid") == entry["oid"]
                        and not previous.get("removed")
                    )
                    if same_blob and (
                        document.id in active_ids or document.id not in failed_ids
                    ):
                        size = previous.get("size")
                        if not isinstance(size, int):
                            size = (document.meta_json or {}).get("file_size")
                        if isinstance(size, int):
                            if size > self.settings.max_file_size_bytes:
                                raise GitRepositoryLimitError(
                                    "Repository file exceeds the configured file size limit: %s"
                                    % path
                                )
                            total_file_bytes += size
                            if total_file_bytes > self.settings.max_git_repo_size_bytes:
                                raise GitRepositoryLimitError(
                                    "Repository exceeds the configured total file size limit (%s MB)"
                                    % self.settings.max_git_repo_size_mb
                                )
                    if document is not None and document.id in active_ids:
                        new_manifest[path] = previous
                        continue
                    if (
                        same_blob
                        and document.id not in failed_ids
                    ):
                        document.last_synced_at = utc_now()
                        document.last_sync_changed = False
                        new_manifest[path] = previous
                        counts["unchanged"] += 1
                        continue

                    staged = staged_by_path.get(path)
                    if staged is None:
                        raise GitRepositoryConflictError(
                            "Repository changed while files were being staged; try syncing again"
                        )
                    document_id, target, content_size, staged_path = staged
                    total_file_bytes += content_size
                    installed_files.append((target, target.exists()))
                    os.replace(staged_path, target)
                    extension = PurePosixPath(path).suffix.lower()
                    if document is None:
                        document = Document(
                            id=document_id,
                            user_id=project.user_id,
                            title=PurePosixPath(path).name,
                            source_type=extension[1:],
                            source_url=str(target),
                            status="queued",
                            meta_json={
                                "filename": path,
                                "file_extension": extension,
                                "file_size": content_size,
                                "git_repository_id": repository.id,
                                "git_path": path,
                                "git_blob": entry["oid"],
                            },
                        )
                        db.add(document)
                        db.add(ProjectDocument(
                            project_id=project.id,
                            document_id=document.id,
                            shared_by_user_id=project.user_id,
                        ))
                        enqueue_ingestion_job_with_result(
                            db,
                            document_id=document.id,
                            job_type="file",
                            payload={"file_path": str(target)},
                        )
                        counts["added"] += 1
                        queued += 1
                    else:
                        old_file = resolve_stored_file(document.source_url)
                        if old_file is not None:
                            old_files.append(old_file)
                        previous_status = document.status
                        previous_error_message = document.error_message
                        document.source_url = str(target)
                        document.error_message = None
                        document.meta_json = {
                            **(document.meta_json or {}),
                            "filename": path,
                            "file_extension": extension,
                            "file_size": content_size,
                            "git_repository_id": repository.id,
                            "git_path": path,
                            "git_blob": entry["oid"],
                        }
                        enqueue_ingestion_job_with_result(
                            db,
                            document_id=document.id,
                            job_type="resync",
                            payload={
                                "file_path": str(target),
                                "previous_status": previous_status,
                                "previous_error_message": previous_error_message,
                            },
                            force_new=True,
                        )
                        counts["updated"] += 1
                        queued += 1
                    new_manifest[path] = {
                        "document_id": document_id,
                        "oid": entry["oid"],
                        "size": content_size,
                        "removed": False,
                    }

                repository.head_commit = head_commit
                repository.manifest_json = new_manifest
                repository.last_synced_at = utc_now()
                if is_new:
                    db.add(repository)
                db.flush()
                commit_attempted = True
                db.commit()
        except Exception:
            db.rollback()
            if not commit_attempted:
                for path in staged_files:
                    path.unlink(missing_ok=True)
                for path, existed in installed_files:
                    if not existed:
                        path.unlink(missing_ok=True)
            raise

        for path in old_files:
            if path not in target_files:
                path.unlink(missing_ok=True)
        if queued:
            try:
                notify_ingestion_worker()
            except Exception as error:
                logger.warning(
                    "Could not wake ingestion worker after Git import",
                    repository_id=repository.id,
                    error=str(error),
                )
        counts["commit"] = repository.head_commit
        return counts

    @contextmanager
    def _open_remote(self, url: str, token: str | None):
        """Shallow-clone one validated remote without checking out its files."""
        normalized_url, addresses = validate_git_url(url)
        with tempfile.TemporaryDirectory(prefix="git-source-") as temporary:
            environment = git_environment(normalized_url, addresses, token, temporary)
            repository_path = Path(temporary) / "repo"
            self._run_git(
                [
                    "clone",
                    "--no-checkout",
                    "--depth=1",
                    "--filter=blob:none",
                    "--no-tags",
                    "--single-branch",
                    "--",
                    normalized_url,
                    str(repository_path),
                ],
                None,
                environment,
                timeout=120,
                max_pack_bytes=self.settings.max_git_repo_size_bytes,
            )
            yield repository_path, environment

    def _list_tree(
        self,
        repository_path: Path,
        environment: dict[str, str],
        include_glob: str,
        exclude_glob: str,
    ):
        """Stream the tree so oversized repositories fail before loading it all."""
        commit = self._run_git(
            ["rev-parse", "HEAD"], repository_path, environment, timeout=30
        ).stdout.decode("ascii", errors="replace").strip()
        if not _GIT_OBJECT_ID.fullmatch(commit):
            raise GitRepositoryUnavailableError("Git returned an invalid commit id")
        try:
            process = subprocess.Popen(
                ["git", "ls-tree", "--full-tree", "-r", "-z", commit],
                cwd=str(repository_path),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise GitRepositoryUnavailableError("Git repository operation failed") from error

        entries = []
        pending = b""
        output_size = 0
        try:
            while chunk := process.stdout.read(64 * 1024):
                output_size += len(chunk)
                if output_size > MAX_GIT_TREE_OUTPUT_BYTES:
                    process.kill()
                    process.wait()
                    raise GitRepositoryLimitError(
                        "Repository tree exceeds the configured scan size limit"
                    )
                records = (pending + chunk).split(b"\0")
                pending = records.pop()
                for record in records:
                    entry = parse_git_tree(record + b"\0")
                    if not entry:
                        continue
                    item = entry[0]
                    if (
                        matches_git_glob(item["path"], include_glob)
                        and not (
                            exclude_glob
                            and matches_git_glob(item["path"], exclude_glob)
                        )
                    ):
                        entries.append(item)
                        if len(entries) > self.settings.max_git_repo_files:
                            process.kill()
                            process.wait()
                            raise GitRepositoryLimitError(
                                "Repository selects more than the configured file count limit (%s)"
                                % self.settings.max_git_repo_files
                            )
            if pending:
                entries.extend(parse_git_tree(pending + b"\0"))
            if process.wait(timeout=60) != 0:
                raise GitRepositoryUnavailableError("Git repository operation failed")
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise GitRepositoryUnavailableError(
                "Git repository operation timed out"
            ) from error
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            if process.stdout:
                process.stdout.close()
        return commit, entries

    def _read_blob(
        self,
        repository_path: Path,
        oid: str,
        environment: dict[str, str],
        max_bytes: int,
    ) -> bytes:
        """Read one selected blob, stopping as soon as it exceeds the byte cap."""
        try:
            process = subprocess.Popen(
                ["git", "cat-file", "blob", oid],
                cwd=str(repository_path),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise GitRepositoryUnavailableError("Git repository operation failed") from error

        chunks = []
        size = 0
        timed_out = threading.Event()

        def stop_slow_reader():
            if process.poll() is None:
                timed_out.set()
                process.kill()

        deadline = threading.Timer(GIT_BLOB_READ_TIMEOUT_SECONDS, stop_slow_reader)
        deadline.daemon = True
        deadline.start()
        try:
            while True:
                block = process.stdout.read(min(1024 * 1024, max_bytes - size + 1))
                if not block:
                    break
                size += len(block)
                if size > max_bytes:
                    process.kill()
                    process.wait()
                    raise GitRepositoryLimitError(
                        "Repository file exceeds the configured file size limit"
                    )
                chunks.append(block)
            if process.wait(timeout=60) != 0:
                if timed_out.is_set():
                    raise GitRepositoryUnavailableError(
                        "Git repository operation timed out"
                    )
                raise GitRepositoryUnavailableError("Git repository file could not be read")
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise GitRepositoryUnavailableError(
                "Git repository operation timed out"
            ) from error
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            deadline.cancel()
            if process.stdout:
                process.stdout.close()
        return b"".join(chunks)

    @staticmethod
    def _write_blob(target: Path, content: bytes) -> None:
        """Atomically save a blob under its document id and Git object id."""
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".git-source-",
            dir=target.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            os.replace(temporary_name, target)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_glob(pattern: str) -> str:
        """Bound glob input before it reaches path matching."""
        if len(pattern) > 512:
            raise ValueError("Repository globs cannot exceed 512 characters")
        return pattern

    @staticmethod
    def _run_git(args, cwd, environment, timeout, max_pack_bytes=None):
        """Run Git with captured output and stable public errors."""
        command = ["git", *args]
        if max_pack_bytes is not None:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(cwd) if cwd else None,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError as error:
                raise GitRepositoryUnavailableError(
                    "Git is unavailable on this server"
                ) from error
            except OSError as error:
                raise GitRepositoryUnavailableError(
                    "Git repository operation failed"
                ) from error

            pack_directory = Path(args[-1]) / ".git" / "objects" / "pack"
            deadline = time.monotonic() + timeout

            def current_pack_bytes():
                total = 0
                try:
                    for pack in pack_directory.iterdir():
                        try:
                            total += pack.stat().st_size
                        except FileNotFoundError:
                            pass
                except FileNotFoundError:
                    pass
                return total

            try:
                while process.poll() is None:
                    if current_pack_bytes() > max_pack_bytes:
                        process.kill()
                        process.wait()
                        raise GitRepositoryLimitError(
                            "Repository download exceeds the configured total size limit"
                        )
                    if time.monotonic() >= deadline:
                        process.kill()
                        process.wait()
                        raise GitRepositoryUnavailableError(
                            "Git repository operation timed out"
                        )
                    time.sleep(0.05)
                if process.returncode != 0:
                    raise GitRepositoryUnavailableError(
                        "Git repository operation failed or timed out"
                    )
                if current_pack_bytes() > max_pack_bytes:
                    raise GitRepositoryLimitError(
                        "Repository download exceeds the configured total size limit"
                    )
                return subprocess.CompletedProcess(command, process.returncode)
            except Exception:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                raise

        try:
            return subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=timeout,
            )
        except FileNotFoundError as error:
            raise GitRepositoryUnavailableError("Git is unavailable on this server") from error
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise GitRepositoryUnavailableError(
                "Git repository operation failed or timed out"
            ) from error
