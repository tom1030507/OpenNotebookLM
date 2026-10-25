"""Integration tests for durable document ingestion lifecycle."""
import asyncio
from io import BytesIO
from pathlib import Path
import threading
from types import SimpleNamespace
import zipfile

import pytest
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import create_database_engine
from app.db.models import (
    Base,
    Chunk,
    Document,
    Embedding,
    IngestionJob,
    Project,
    ProjectDocument,
    User,
)
from app.services.chunking import ChunkingService, ChunkLimitExceededError
from app.services.retrieval_index import get_retrieval_index
from app.services import documents as document_module
from app.services import ingestion_jobs as ingestion_job_module
from app.services.documents import DocumentService
from app.services.ingestion_jobs import (
    IngestionJobWorker,
    enqueue_ingestion_job,
    release_all_operation_leases,
    retain_operation_lease,
)
from app.services.rate_limit import ConcurrencyLimiter
from app.utils.network import UnsafeURLError


@pytest.fixture
def lifecycle_db():
    """Create an isolated database for enqueue boundary tests.

    Args:
        None.

    Returns:
        A Session connected to a shared in-memory SQLite database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    db = session_factory()
    db.add(Project(id="project-1", name="Durable imports"))
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def lifecycle_file_db(tmp_path):
    """Create a file database so reconciliation uses another connection.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        A Session connected to an isolated file SQLite database.
    """
    engine = create_database_engine(
        "sqlite:///%s" % (tmp_path / "lifecycle.db"),
        echo=False,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=True,
    )
    db = session_factory()
    db.add(Project(id="project-1", name="Durable imports"))
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


class MustNotChunk:
    """Fail if request-bound code reaches indexing."""

    def chunk_document(self, *args, **kwargs):
        """Reject request-thread chunking.

        Args:
            args: Unexpected positional arguments.
            kwargs: Unexpected keyword arguments.

        Returns:
            Never returns.
        """
        raise AssertionError("enqueue performed chunking")


class MustNotEmbed:
    """Fail if request-bound code reaches the model."""

    def embed_chunks(self, *args, **kwargs):
        """Reject request-thread embedding.

        Args:
            args: Unexpected positional arguments.
            kwargs: Unexpected keyword arguments.

        Returns:
            Never returns.
        """
        raise AssertionError("enqueue performed embedding")


def queued_service():
    """Build a service whose slow boundaries make eager work visible.

    Args:
        None.

    Returns:
        Document service with indexing boundaries that must stay untouched.
    """
    return DocumentService(
        chunking_service=MustNotChunk(),
        embedding_service=MustNotEmbed(),
    )


def test_reindex_uses_saved_chunks_and_the_current_title(lifecycle_db):
    """A re-index job refreshes vectors without extraction or rechunking.

    Args:
        lifecycle_db: Isolated database session.

    Returns:
        None.
    """
    class ReindexEmbeddings:
        def __init__(self):
            self.titles = []
            self.published = []

        def embed_chunks(self, db, document_id, force_regenerate=False):
            self.titles.append(db.get(Document, document_id).title)
            assert force_regenerate
            return [object()]

        def publish_document_index(self, db, document_id):
            self.published.append(document_id)

    document = Document(
        id="reindex-document",
        title="Renamed source",
        source_type="url",
        status="ready",
        content="Previously extracted content",
    )
    lifecycle_db.add(document)
    lifecycle_db.add(Chunk(
        id="reindex-chunk",
        document_id=document.id,
        text="Previously chunked content",
    ))
    lifecycle_db.commit()
    embeddings = ReindexEmbeddings()
    service = DocumentService(
        chunking_service=MustNotChunk(),
        embedding_service=embeddings,
    )

    status = service.process_ingestion_job(
        lifecycle_db,
        document_id=document.id,
        job_type="reindex",
        payload={},
    )

    assert status == "ready"
    assert document.status == "ready"
    assert embeddings.titles == ["Renamed source"]
    assert embeddings.published == [document.id]


def test_reindex_repeats_when_title_changes_during_embedding(lifecycle_db):
    """The vectors are regenerated if a rename lands during model inference.

    Args:
        lifecycle_db: Isolated database session.

    Returns:
        None.
    """
    class RenameDuringEmbedding:
        def __init__(self):
            self.titles = []

        def embed_chunks(self, db, document_id, force_regenerate=False):
            document = db.get(Document, document_id)
            self.titles.append(document.title)
            assert force_regenerate
            if len(self.titles) == 1:
                document.title = "Latest title"
                db.commit()
            return [object()]

        def publish_document_index(self, db, document_id):
            pass

    document = Document(
        id="reindex-race-document",
        title="Initial title",
        source_type="url",
        status="ready",
        content="Previously extracted content",
    )
    lifecycle_db.add(document)
    lifecycle_db.add(Chunk(
        id="reindex-race-chunk",
        document_id=document.id,
        text="Previously chunked content",
    ))
    lifecycle_db.commit()
    embeddings = RenameDuringEmbedding()
    payload = {}
    service = DocumentService(
        chunking_service=MustNotChunk(),
        embedding_service=embeddings,
    )

    service.process_ingestion_job(
        lifecycle_db,
        document_id=document.id,
        job_type="reindex",
        payload=payload,
    )

    assert embeddings.titles == ["Initial title", "Latest title"]
    assert payload["_indexed_title"] == "Latest title"


def test_file_job_extracts_using_the_persisted_extension_and_indexes_text(lifecycle_db):
    """A non-PDF file job dispatches by stored extension and reaches ready."""
    document = Document(
        id="file-job-document",
        title="Report",
        source_type="docx",
        source_url="uploads/file-job-document_report.docx",
        status="processing",
        meta_json={"file_extension": ".docx", "filename": "report.docx"},
    )
    lifecycle_db.add(document)
    lifecycle_db.commit()

    class OfficeExtractor:
        def __init__(self):
            self.calls = []

        def extract_text_from_file(self, file_path, file_extension):
            self.calls.append((file_path, file_extension))
            return {
                "text": "## Section\n\nSearchable report content.",
                "pages": [],
                "num_pages": 0,
                "metadata": {"format": "docx"},
            }

    class Embedder:
        def embed_chunks(self, db, document_id):
            chunks = db.query(Chunk).filter_by(document_id=document_id).all()
            embeddings = [
                Embedding(
                    id="%s-embedding" % chunk.id,
                    chunk_id=chunk.id,
                    vector_json=[0.1, 0.2],
                    model_name="fake-model",
                )
                for chunk in chunks
            ]
            db.add_all(embeddings)
            db.commit()
            return embeddings

    office = OfficeExtractor()
    service = DocumentService(
        chunking_service=ChunkingService(chunk_size=128, chunk_overlap=0),
        embedding_service=Embedder(),
        office_adapter=office,
    )
    service._publish_document_index = lambda db, document_id: None

    status = service.process_ingestion_job(
        lifecycle_db,
        document_id=document.id,
        job_type="file",
        payload={"file_path": document.source_url},
    )

    assert office.calls == [(document.source_url, ".docx")]
    assert status == document.status == "ready"
    assert document.content == "## Section\n\nSearchable report content."
    assert document.meta_json["metadata"] == {"format": "docx"}


def test_pdf_url_job_preserves_page_boundaries(lifecycle_db):
    url = "https://example.com/report.pdf"
    document = Document(
        id="pdf-url-document",
        title=url,
        source_type="url",
        source_url=url,
        status="queued",
    )
    lifecycle_db.add(document)
    lifecycle_db.commit()

    class PDFURLExtractor:
        def extract_content(self, source_url):
            assert source_url == url
            return {
                "text": "Remote report text",
                "title": "Remote report",
                "metadata": {"author": "Researcher"},
                "headings": [],
                "links": [],
                "pages": [{"page_num": 1, "text": "Remote report text"}],
                "num_pages": 1,
            }

    service = DocumentService(
        chunking_service=SimpleNamespace(
            chunk_document=lambda *_args, **_kwargs: [object()],
        ),
        embedding_service=SimpleNamespace(
            embed_chunks=lambda *_args, **_kwargs: [object()],
        ),
        pdf_adapter=object(),
        url_adapter=PDFURLExtractor(),
    )
    service._publish_document_index = lambda *_args, **_kwargs: None

    assert service.process_ingestion_job(
        lifecycle_db,
        document_id=document.id,
        job_type="url",
        payload={"url": url},
    ) == "ready"

    assert document.title == "Remote report"
    assert document.content == "Remote report text"
    assert document.meta_json["num_pages"] == 1
    assert document.meta_json["pages"] == [
        {"page_num": 1, "text": "Remote report text"}
    ]


def test_non_pdf_upload_persists_its_extension_and_a_file_job(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """The generalized upload path stores recoverable file-job state."""
    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(document_module, "notify_ingestion_worker", lambda: None)
    service = DocumentService(
        chunking_service=object(),
        embedding_service=object(),
    )

    document = asyncio.run(service.process_file_upload(
        db=lifecycle_db,
        project_id="project-1",
        user_id="user-1",
        file=BytesIO(b"# Research notes"),
        filename="notes.md",
        file_extension=".md",
    ))

    job = lifecycle_db.query(IngestionJob).filter_by(
        document_id=document.id,
    ).one()
    assert document.source_type == "md"
    assert document.meta_json["file_extension"] == ".md"
    assert document.source_url.endswith("_notes.md")
    assert job.job_type == "file"
    assert job.payload_json == {"file_path": document.source_url}


def test_audio_upload_rejects_overlong_file_before_creating_document_or_job(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """Audio preflight errors clean up the upload before durable enqueue."""
    from app.adapters.audio import InvalidAudioFileError
    from app.services.documents import InvalidUploadFileError

    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)

    class AudioProbe:
        def validate_file(self, file_path):
            raise InvalidAudioFileError("Audio is longer than the 30 minutes limit")

        def transcribe_file(self, file_path):
            raise AssertionError("an invalid upload must not reach Whisper")

    service = DocumentService(
        chunking_service=object(),
        embedding_service=object(),
        audio_adapter=AudioProbe(),
    )

    with pytest.raises(InvalidUploadFileError, match="30 minutes"):
        asyncio.run(service.process_file_upload(
            db=lifecycle_db,
            project_id="project-1",
            user_id="user-1",
            file=BytesIO(b"not an audio file"),
            filename="lecture.mp3",
            file_extension=".mp3",
        ))

    assert list(tmp_path.iterdir()) == []
    assert lifecycle_db.query(Document).count() == 0
    assert lifecycle_db.query(IngestionJob).count() == 0


def test_audio_file_job_transcribes_in_worker_and_stores_timestamp_metadata(
    lifecycle_file_db,
    tmp_path,
    monkeypatch,
):
    """The worker persists transcribing status and indexes timestamp sections."""
    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(document_module, "notify_ingestion_worker", lambda: None)
    lifecycle_file_db.add(User(
        id="user-1",
        username="audio-test-user",
        email="audio-test@example.com",
        hashed_password="not-a-real-hash",
    ))
    lifecycle_file_db.commit()
    visible_statuses = []

    class AudioTranscriber:
        document_id = None

        def validate_file(self, file_path):
            return 125

        def transcribe_file(self, file_path):
            with sessionmaker(
                bind=lifecycle_file_db.get_bind(),
                expire_on_commit=False,
            )() as observer:
                visible_statuses.append(
                    observer.get(Document, self.document_id).status
                )
            return {
                "text": (
                    "## 00:00:00\nWelcome to the lecture.\n"
                    "## 00:02:00\nThe key idea is searchable."
                ),
                "segments": [
                    {"start": 1.0, "end": 3.0, "duration": 2.0, "text": "Welcome."},
                    {"start": 121.0, "end": 124.0, "duration": 3.0, "text": "The key idea is searchable."},
                ],
                "duration": 125,
                "language": "en",
                "metadata": {"model": "base", "transcription_source": "whisper"},
            }

    class Embedder:
        def embed_chunks(self, db, document_id):
            chunks = (
                db.query(Chunk)
                .filter(Chunk.document_id == document_id)
                .order_by(Chunk.start_offset, Chunk.id)
                .all()
            )
            embeddings = [
                Embedding(
                    id="audio-embedding-%s" % index,
                    chunk_id=chunk.id,
                    vector_json=[float(index)],
                    model_name="fake-model",
                )
                for index, chunk in enumerate(chunks)
            ]
            db.add_all(embeddings)
            db.commit()
            return embeddings

    audio = AudioTranscriber()
    service = DocumentService(
        chunking_service=ChunkingService(chunk_size=128, chunk_overlap=0),
        embedding_service=Embedder(),
        audio_adapter=audio,
    )

    document = asyncio.run(service.process_file_upload(
        db=lifecycle_file_db,
        project_id="project-1",
        user_id="user-1",
        file=BytesIO(b"audio bytes"),
        filename="lecture.mp3",
        file_extension=".mp3",
    ))
    audio.document_id = document.id
    job = lifecycle_file_db.query(IngestionJob).filter_by(
        document_id=document.id,
    ).one()
    assert visible_statuses == []

    status = service.process_ingestion_job(
        lifecycle_file_db,
        document_id=document.id,
        job_type=job.job_type,
        payload=job.payload_json,
    )

    chunks = lifecycle_file_db.query(Chunk).filter_by(
        document_id=document.id,
    ).order_by(Chunk.start_offset).all()
    assert status == document.status == "ready"
    assert visible_statuses == ["transcribing"]
    assert document.content.startswith("## 00:00:00")
    assert document.meta_json["segments"][1]["start"] == 121.0
    assert [chunk.heading_path for chunk in chunks] == ["00:00:00", "00:02:00"]
    assert lifecycle_file_db.query(Embedding).join(Chunk).filter(
        Chunk.document_id == document.id,
    ).count() == len(chunks)
    search_results = get_retrieval_index().lexical_search(
        lifecycle_file_db,
        "searchable",
        document_ids=[document.id],
    )
    assert [result.chunk_id for result in search_results] == [chunks[1].id]

    stored_path = Path(document.source_url)
    assert stored_path.is_file()
    assert service.delete_document(lifecycle_file_db, document.id) is True
    assert not stored_path.exists()


def test_image_upload_runs_ocr_and_indexes_searchable_text(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """A validated image is persisted, OCRed by its file job, and chunked."""
    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(document_module, "notify_ingestion_worker", lambda: None)
    image_bytes = BytesIO()
    Image.new("RGB", (120, 80), "white").save(image_bytes, format="PNG")
    recognized_text = (
        "This scanned report contains important searchable OCR text. " * 3
    )

    class ImageOCR:
        max_image_pixels = 40_000_000

        def __init__(self):
            self.paths = []

        def validate_image_file(self, file_path):
            with Image.open(file_path) as image:
                image.verify()

        def extract_text_from_image(self, file_path, filename):
            self.paths.append((file_path, filename))
            return {
                "text": "# %s\n\n%s" % (filename, recognized_text),
                "pages": [{"page_num": 1, "text": recognized_text}],
                "num_pages": 1,
                "metadata": {"ocr_engine": "RapidOCR", "ocr_pages": 1},
            }

    class Embedder:
        def embed_chunks(self, db, document_id):
            return [object()]

    ocr = ImageOCR()
    service = DocumentService(
        chunking_service=ChunkingService(chunk_size=300, chunk_overlap=0),
        embedding_service=Embedder(),
        ocr_adapter=ocr,
    )
    assert service.pdf_adapter.ocr_adapter is ocr
    assert service.pdf_adapter.ocr_enabled is True
    service._publish_document_index = lambda db, document_id: None

    document = asyncio.run(service.process_file_upload(
        db=lifecycle_db,
        project_id="project-1",
        user_id="user-1",
        file=BytesIO(image_bytes.getvalue()),
        filename="scan.png",
        file_extension=".png",
    ))
    job = lifecycle_db.query(IngestionJob).filter_by(
        document_id=document.id,
    ).one()

    status = service.process_ingestion_job(
        lifecycle_db,
        document_id=document.id,
        job_type=job.job_type,
        payload=job.payload_json,
    )

    chunks = lifecycle_db.query(Chunk).filter_by(document_id=document.id).all()
    assert status == document.status == "ready"
    assert document.source_type == "png"
    assert document.content.startswith("# scan.png")
    assert recognized_text in document.content
    assert any(recognized_text[:70] in chunk.text for chunk in chunks)
    assert ocr.paths == [(document.source_url, "scan.png")]
    assert document.meta_json["metadata"]["ocr_engine"] == "RapidOCR"


def test_malformed_image_upload_leaves_no_file_document_or_job(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """Malformed images fail before a durable ingestion job is created."""
    from app.adapters.ocr import OCRAdapter
    from app.services.documents import InvalidUploadFileError

    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    service = DocumentService(
        chunking_service=object(),
        embedding_service=object(),
        ocr_adapter=OCRAdapter(str(tmp_path / "models")),
    )

    with pytest.raises(InvalidUploadFileError, match="valid image"):
        asyncio.run(service.process_file_upload(
            db=lifecycle_db,
            project_id="project-1",
            user_id="user-1",
            file=BytesIO(b"not a PNG image"),
            filename="broken.png",
            file_extension=".png",
        ))

    assert list(tmp_path.iterdir()) == []
    assert lifecycle_db.query(Document).count() == 0
    assert lifecycle_db.query(IngestionJob).count() == 0


def test_image_upload_is_refused_when_ocr_is_disabled(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """Disabling OCR also disables image sources at the upload boundary."""
    from app.services.documents import InvalidUploadFileError

    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(document_module.get_settings(), "ocr_enabled", False)
    service = DocumentService(chunking_service=object(), embedding_service=object())
    assert service.pdf_adapter.ocr_enabled is False

    with pytest.raises(InvalidUploadFileError, match="OCR is disabled"):
        asyncio.run(service.process_file_upload(
            db=lifecycle_db,
            project_id="project-1",
            user_id="user-1",
            file=BytesIO(b"ignored"),
            filename="scan.png",
            file_extension=".png",
        ))

    assert list(tmp_path.iterdir()) == []
    assert lifecycle_db.query(Document).count() == 0
    assert lifecycle_db.query(IngestionJob).count() == 0


def test_non_pdf_upload_refuses_invalid_office_bytes_without_a_queued_row(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """A mismatched Office package leaves no file, document, or job behind."""
    from app.services.documents import InvalidUploadFileError

    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    service = DocumentService(
        chunking_service=object(),
        embedding_service=object(),
    )

    with pytest.raises(InvalidUploadFileError, match="valid Office document"):
        asyncio.run(service.process_file_upload(
            db=lifecycle_db,
            project_id="project-1",
            user_id="user-1",
            file=BytesIO(b"MZ executable content"),
            filename="renamed.docx",
            file_extension=".docx",
        ))

    assert list(tmp_path.iterdir()) == []
    assert lifecycle_db.query(Document).count() == 0
    assert lifecycle_db.query(IngestionJob).count() == 0


def test_non_pdf_upload_refuses_epub_without_package_document(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """A superficially valid EPUB is rejected before file or job persistence."""
    from app.services.documents import InvalidUploadFileError

    package = BytesIO()
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"/>',
        )

    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    service = DocumentService(
        chunking_service=object(),
        embedding_service=object(),
    )

    with pytest.raises(InvalidUploadFileError, match="package rootfile"):
        asyncio.run(service.process_file_upload(
            db=lifecycle_db,
            project_id="project-1",
            user_id="user-1",
            file=BytesIO(package.getvalue()),
            filename="book.epub",
            file_extension=".epub",
        ))

    assert list(tmp_path.iterdir()) == []
    assert lifecycle_db.query(Document).count() == 0
    assert lifecycle_db.query(IngestionJob).count() == 0


class StaticURLAdapter:
    """Return stable content without a network dependency."""

    def extract_content(self, url):
        """Return enough text to produce several deterministic chunks.

        Args:
            url: Source URL recorded by the document.

        Returns:
            Complete URL adapter result used by DocumentService.
        """
        return {
            "text": "alpha beta gamma delta epsilon zeta eta theta iota kappa",
            "title": "Stable article",
            "metadata": {"url": url},
            "headings": [],
            "links": [],
        }


class CommitThenFailEmbeddingService:
    """Simulate a crash after one embedding has already committed."""

    def __init__(self):
        """Fail only the first indexing attempt.

        Args:
            None.

        Returns:
            None.
        """
        self.calls = 0

    def embed_chunks(self, db, document_id):
        """Persist real rows, failing after the first row on attempt one.

        Args:
            db: Worker-owned Session.
            document_id: Document whose chunks should be embedded.

        Returns:
            Persisted embedding rows on a successful retry.
        """
        self.calls += 1
        records = []
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.start_offset, Chunk.id)
            .all()
        )
        for index, chunk in enumerate(chunks):
            record = Embedding(
                id="embedding-%s-%s" % (self.calls, index),
                chunk_id=chunk.id,
                vector=b"vector",
                vector_json=[float(index)],
                model_name="test-model",
            )
            db.add(record)
            records.append(record)
            db.commit()
            if self.calls == 1 and index == 0:
                raise RuntimeError("embedding worker crashed")
        return records


class StableEmbeddingService:
    """Persist one deterministic embedding for every committed chunk."""

    def embed_chunks(self, db, document_id):
        """Create searchable rows without loading an ML model.

        Args:
            db: Worker-owned Session.
            document_id: Document whose chunks should be embedded.

        Returns:
            Persisted embedding rows.
        """
        records = []
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.start_offset, Chunk.id)
            .all()
        )
        for index, chunk in enumerate(chunks):
            record = Embedding(
                id="stable-embedding-%s" % index,
                chunk_id=chunk.id,
                vector=b"vector",
                vector_json=[float(index)],
                model_name="test-model",
            )
            db.add(record)
            records.append(record)
        db.commit()
        return records


async def wait_for_terminal_job(session_factory, job_id, timeout=3):
    """Wait for a worker to persist completed or failed.

    Args:
        session_factory: Factory bound to the test file database.
        job_id: Job whose state is observed.
        timeout: Maximum seconds to wait.

    Returns:
        Persisted terminal status.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        with session_factory() as db:
            status = db.get(IngestionJob, job_id).status
            if status in {"completed", "failed"}:
                return status
        await asyncio.sleep(0.01)
    raise AssertionError("job %s did not terminate" % job_id)


def test_url_enqueue_returns_without_extraction(lifecycle_db):
    """A URL request persists source references and returns queued immediately.

    Args:
        lifecycle_db: Isolated database Session.

    Returns:
        None.
    """
    calls = []

    class ExternalURLAdapter:
        def extract_content(self, url):
            calls.append(url)
            return {
                "text": "external body",
                "title": "External",
                "metadata": {},
                "headings": [],
                "links": [],
            }

    service = queued_service()
    service.url_adapter = ExternalURLAdapter()
    try:
        document = asyncio.run(service.process_url(
            db=lifecycle_db,
            project_id="project-1",
            user_id=None,
            url="https://example.com/article",
            title="Queued URL",
        ))
    finally:
        service.executor.shutdown(wait=True)

    assert calls == []
    assert document.status == "queued"
    job = lifecycle_db.query(IngestionJob).one()
    assert job.document_id == document.id
    assert job.job_type == "url"
    assert job.payload_json == {"url": "https://example.com/article"}
    assert lifecycle_db.query(ProjectDocument).count() == 1


def test_pdf_enqueue_only_streams_the_recoverable_upload(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """A PDF request writes the upload but defers extraction and indexing.

    Args:
        lifecycle_db: Isolated database Session.
        tmp_path: Per-test upload directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    calls = []

    class ExternalPDFAdapter:
        def extract_text_from_file(self, path):
            calls.append(path)
            return {"text": "pdf body", "num_pages": 1}

    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    service = queued_service()
    service.pdf_adapter = ExternalPDFAdapter()
    try:
        document = asyncio.run(service.process_pdf_upload(
            db=lifecycle_db,
            project_id="project-1",
            user_id=None,
            file=BytesIO(b"small pdf"),
            filename="source.pdf",
        ))
    finally:
        service.executor.shutdown(wait=True)

    assert calls == []
    job = lifecycle_db.query(IngestionJob).one()
    assert job.job_type == "pdf"
    assert job.payload_json == {"file_path": document.source_url}
    assert (tmp_path / document.source_url.split("/")[-1]).exists()


def test_youtube_enqueue_returns_without_transcript_fetch(lifecycle_db):
    """A YouTube request persists the URL without fetching a transcript.

    Args:
        lifecycle_db: Isolated database Session.

    Returns:
        None.
    """
    calls = []

    class ExternalYouTubeAdapter:
        def extract_transcript(self, url):
            calls.append(url)
            return {"text": "transcript", "video_id": "video"}

    service = queued_service()
    service.youtube_adapter = ExternalYouTubeAdapter()
    try:
        document = asyncio.run(service.process_youtube(
            db=lifecycle_db,
            project_id="project-1",
            user_id=None,
            youtube_url="https://youtu.be/video",
        ))
    finally:
        service.executor.shutdown(wait=True)

    assert calls == []
    assert document.status == "queued"
    job = lifecycle_db.query(IngestionJob).one()
    assert job.job_type == "youtube"
    assert job.payload_json == {"youtube_url": "https://youtu.be/video"}


def test_pdf_commit_failure_releases_lease_and_removes_exact_upload(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """A failed enqueue commit leaves neither a slot nor a partial upload.

    Args:
        lifecycle_db: Isolated database Session.
        tmp_path: Per-test upload directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    limiter = ConcurrencyLimiter(max_concurrent=1)
    lease = limiter.acquire("ingest:user")
    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        lifecycle_db,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("commit failed")),
    )
    service = queued_service()
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            asyncio.run(service.process_pdf_upload(
                db=lifecycle_db,
                project_id="project-1",
                user_id=None,
                file=BytesIO(b"partial"),
                filename="source.pdf",
                operation_lease=lease,
            ))
    finally:
        service.executor.shutdown(wait=True)

    assert limiter.active("ingest:user") == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("source_type", ["pdf", "url", "youtube"])
def test_enqueue_accepts_a_commit_acknowledgement_failure(
    source_type,
    lifecycle_file_db,
    tmp_path,
    monkeypatch,
):
    """A durable document/job pair is success when only its commit ACK fails.

    Args:
        source_type: Durable enqueue entry point under test.
        lifecycle_file_db: Isolated file database Session.
        tmp_path: Per-test upload directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    original_commit = lifecycle_file_db.commit
    failures_remaining = 1

    def accepted_then_raised_commit():
        nonlocal failures_remaining
        original_commit()
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("commit acknowledgement lost")

    monkeypatch.setattr(
        lifecycle_file_db,
        "commit",
        accepted_then_raised_commit,
    )
    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    notifications = []
    monkeypatch.setattr(
        document_module,
        "notify_ingestion_worker",
        lambda: notifications.append("notified"),
    )
    limiter = ConcurrencyLimiter(max_concurrent=1)
    lease = limiter.acquire("ingest:user")
    release_all_operation_leases()
    service = queued_service()
    try:
        if source_type == "pdf":
            document = asyncio.run(service.process_pdf_upload(
                db=lifecycle_file_db,
                project_id="project-1",
                user_id=None,
                file=BytesIO(b"durable after lost acknowledgement"),
                filename="source.pdf",
                operation_lease=lease,
            ))
        elif source_type == "url":
            document = asyncio.run(service.process_url(
                db=lifecycle_file_db,
                project_id="project-1",
                user_id=None,
                url="https://example.com/commit-ack",
                operation_lease=lease,
            ))
        else:
            document = asyncio.run(service.process_youtube(
                db=lifecycle_file_db,
                project_id="project-1",
                user_id=None,
                youtube_url="https://youtu.be/commit-ack",
                operation_lease=lease,
            ))

        fresh_factory = sessionmaker(
            bind=lifecycle_file_db.get_bind(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        with fresh_factory() as fresh_db:
            persisted = fresh_db.get(Document, document.id)
            job = fresh_db.query(IngestionJob).filter(
                IngestionJob.document_id == document.id,
            ).one()
            assert persisted.status == "queued"
            assert job.status == "queued"
            assert fresh_db.query(ProjectDocument).filter(
                ProjectDocument.document_id == document.id,
            ).count() == 1
            if source_type == "pdf":
                assert Path(persisted.source_url).exists()
        assert notifications == ["notified"]
        assert limiter.active("ingest:user") == 1
    finally:
        release_all_operation_leases()
        service.executor.shutdown(wait=True)

    assert limiter.active("ingest:user") == 0


@pytest.mark.parametrize("source_type", ["pdf", "url", "youtube"])
def test_duplicate_enqueue_commit_failure_preserves_winner_lease(
    source_type,
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """A duplicate request rollback cannot release the active winner's slot.

    Args:
        source_type: Durable enqueue entry point under test.
        lifecycle_db: Isolated database Session.
        tmp_path: Per-test upload directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    lifecycle_db.add(Document(
        id="winner-document",
        title="Existing active source",
        source_type=source_type,
        source_url="https://example.com/winner",
        status="queued",
    ))
    lifecycle_db.commit()
    winner_job = IngestionJob(
        id="winner-job",
        document_id="winner-document",
        job_type=source_type,
        payload_json={"source": "winner"},
        status="queued",
    )
    lifecycle_db.add(winner_job)
    lifecycle_db.commit()

    limiter = ConcurrencyLimiter(max_concurrent=2)
    release_all_operation_leases()
    retain_operation_lease(
        winner_job.id,
        limiter.acquire("ingest:user"),
    )
    duplicate_lease = limiter.acquire("ingest:user")
    duplicate_result = SimpleNamespace(
        job=winner_job,
        created_new_active=False,
    )

    monkeypatch.setattr(
        document_module,
        "enqueue_ingestion_job",
        lambda *_args, **_kwargs: winner_job,
        raising=False,
    )
    monkeypatch.setattr(
        document_module,
        "enqueue_ingestion_job_with_result",
        lambda *_args, **_kwargs: duplicate_result,
        raising=False,
    )
    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        lifecycle_db,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("duplicate commit failed")),
    )
    service = queued_service()

    try:
        with pytest.raises(
            document_module.EnqueueCommitUncertainError,
            match="inconsistent state",
        ):
            if source_type == "pdf":
                asyncio.run(service.process_pdf_upload(
                    db=lifecycle_db,
                    project_id="project-1",
                    user_id=None,
                    file=BytesIO(b"duplicate"),
                    filename="duplicate.pdf",
                    operation_lease=duplicate_lease,
                ))
            elif source_type == "url":
                asyncio.run(service.process_url(
                    db=lifecycle_db,
                    project_id="project-1",
                    user_id=None,
                    url="https://example.com/duplicate",
                    operation_lease=duplicate_lease,
                ))
            else:
                asyncio.run(service.process_youtube(
                    db=lifecycle_db,
                    project_id="project-1",
                    user_id=None,
                    youtube_url="https://youtu.be/duplicate",
                    operation_lease=duplicate_lease,
                ))

        assert limiter.active("ingest:user") == 1
    finally:
        release_all_operation_leases()
        service.executor.shutdown(wait=True)

    assert limiter.active("ingest:user") == 0


def test_committed_pdf_survives_process_local_notify_failure(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """Polling recovery owns a committed upload even if wakeup fails.

    Args:
        lifecycle_db: Isolated database Session.
        tmp_path: Per-test upload directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    limiter = ConcurrencyLimiter(max_concurrent=1)
    lease = limiter.acquire("ingest:user")
    monkeypatch.setattr(document_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        document_module,
        "notify_ingestion_worker",
        lambda: (_ for _ in ()).throw(RuntimeError("wakeup failed")),
    )
    service = queued_service()
    try:
        document = asyncio.run(service.process_pdf_upload(
            db=lifecycle_db,
            project_id="project-1",
            user_id=None,
            file=BytesIO(b"durable"),
            filename="source.pdf",
            operation_lease=lease,
        ))
        assert lifecycle_db.query(IngestionJob).count() == 1
        assert lifecycle_db.get(Document, document.id).status == "queued"
        assert list(tmp_path.iterdir()) == [tmp_path / Path(document.source_url).name]
        assert limiter.active("ingest:user") == 1
    finally:
        release_all_operation_leases()
        service.executor.shutdown(wait=True)

    assert limiter.active("ingest:user") == 0


def test_deleting_queued_document_releases_its_operation_lease(lifecycle_db):
    """A queued job cannot retain a quota slot after its document is deleted.

    Args:
        lifecycle_db: Isolated database Session.

    Returns:
        None.
    """
    limiter = ConcurrencyLimiter(max_concurrent=1)
    lease = limiter.acquire("ingest:user")
    service = queued_service()
    try:
        document = asyncio.run(service.process_url(
            db=lifecycle_db,
            project_id="project-1",
            user_id=None,
            url="https://example.com/delete",
            operation_lease=lease,
        ))
        assert limiter.active("ingest:user") == 1

        assert service.delete_document(lifecycle_db, document.id)
        assert lifecycle_db.query(IngestionJob).count() == 0
        assert limiter.active("ingest:user") == 0
    finally:
        release_all_operation_leases()
        service.executor.shutdown(wait=True)


def test_deleting_image_document_removes_its_source_file(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """Deleting an OCR source removes its uploaded image after commit."""
    source_path = tmp_path / "scan.webp"
    source_path.write_bytes(b"image data")
    lifecycle_db.add(Document(
        id="document-delete-image",
        title="Scan",
        source_type="webp",
        source_url=str(source_path),
        status="ready",
    ))
    lifecycle_db.commit()

    class RetrievalIndex:
        def delete_document(self, db, document_id):
            return None

    monkeypatch.setattr(
        document_module,
        "get_retrieval_index",
        lambda: RetrievalIndex(),
    )

    assert DocumentService(
        chunking_service=object(),
        embedding_service=object(),
    ).delete_document(lifecycle_db, "document-delete-image")
    assert not source_path.exists()


def test_failed_document_delete_keeps_pdf_and_lease(
    lifecycle_db,
    tmp_path,
    monkeypatch,
):
    """A database refusal cannot destroy the source of a still-durable job.

    Args:
        lifecycle_db: Isolated database Session.
        tmp_path: Per-test source directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"recoverable")
    lifecycle_db.add(Document(
        id="document-delete-fails",
        title="Recoverable PDF",
        source_type="pdf",
        source_url=str(source_path),
        status="queued",
    ))
    lifecycle_db.commit()
    job = enqueue_ingestion_job(
        lifecycle_db,
        document_id="document-delete-fails",
        job_type="pdf",
        payload={"file_path": str(source_path)},
    )
    lifecycle_db.commit()
    limiter = ConcurrencyLimiter(max_concurrent=1)
    retain_operation_lease(job.id, limiter.acquire("ingest:user"))
    monkeypatch.setattr(
        lifecycle_db,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("delete commit failed")),
    )
    service = queued_service()
    try:
        with pytest.raises(RuntimeError, match="delete commit failed"):
            service.delete_document(lifecycle_db, "document-delete-fails")
        lifecycle_db.rollback()
        assert source_path.exists()
        assert lifecycle_db.get(Document, "document-delete-fails") is not None
        assert limiter.active("ingest:user") == 1
    finally:
        release_all_operation_leases()
        service.executor.shutdown(wait=True)


def test_successful_document_delete_removes_pdf_after_commit(
    lifecycle_db,
    tmp_path,
):
    """A committed delete removes its exact PDF and queued operation slot.

    Args:
        lifecycle_db: Isolated database Session.
        tmp_path: Per-test source directory.

    Returns:
        None.
    """
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"delete after commit")
    lifecycle_db.add(Document(
        id="document-delete-succeeds",
        title="Disposable PDF",
        source_type="pdf",
        source_url=str(source_path),
        status="queued",
    ))
    lifecycle_db.commit()
    job = enqueue_ingestion_job(
        lifecycle_db,
        document_id="document-delete-succeeds",
        job_type="pdf",
        payload={"file_path": str(source_path)},
    )
    lifecycle_db.commit()
    limiter = ConcurrencyLimiter(max_concurrent=1)
    retain_operation_lease(job.id, limiter.acquire("ingest:user"))
    service = queued_service()
    try:
        assert service.delete_document(
            lifecycle_db,
            "document-delete-succeeds",
        )
        assert not source_path.exists()
        assert limiter.active("ingest:user") == 0
    finally:
        release_all_operation_leases()
        service.executor.shutdown(wait=True)


def test_document_delete_accepts_a_commit_acknowledgement_failure(
    lifecycle_file_db,
    tmp_path,
    monkeypatch,
):
    """A committed delete finishes file and lease cleanup when its ACK fails.

    Args:
        lifecycle_file_db: Isolated file database Session.
        tmp_path: Per-test source directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    source_path = tmp_path / "delete-ack-source.pdf"
    source_path.write_bytes(b"delete after durable commit")
    lifecycle_file_db.add(Document(
        id="document-delete-ack",
        title="Delete acknowledgement",
        source_type="pdf",
        source_url=str(source_path),
        status="queued",
    ))
    lifecycle_file_db.commit()
    job = enqueue_ingestion_job(
        lifecycle_file_db,
        document_id="document-delete-ack",
        job_type="pdf",
        payload={"file_path": str(source_path)},
    )
    lifecycle_file_db.commit()
    limiter = ConcurrencyLimiter(max_concurrent=1)
    release_all_operation_leases()
    retain_operation_lease(job.id, limiter.acquire("ingest:user"))
    original_commit = lifecycle_file_db.commit
    failures_remaining = 1

    def accepted_then_raised_commit():
        nonlocal failures_remaining
        original_commit()
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("delete acknowledgement lost")

    monkeypatch.setattr(
        lifecycle_file_db,
        "commit",
        accepted_then_raised_commit,
    )
    service = queued_service()
    try:
        assert service.delete_document(
            lifecycle_file_db,
            "document-delete-ack",
        )
        fresh_factory = sessionmaker(
            bind=lifecycle_file_db.get_bind(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        with fresh_factory() as fresh_db:
            assert fresh_db.get(Document, "document-delete-ack") is None
            assert fresh_db.get(IngestionJob, job.id) is None
        assert not source_path.exists()
        assert limiter.active("ingest:user") == 0
    finally:
        release_all_operation_leases()
        service.executor.shutdown(wait=True)


def test_delete_claim_race_keeps_running_lease_until_processor_finishes(
    tmp_path,
):
    """A stale queued snapshot cannot release a job that won the claim race.

    Args:
        tmp_path: Per-test file database directory.

    Returns:
        None.
    """
    engine = create_database_engine(
        "sqlite:///%s" % (tmp_path / "delete-claim-race.db"),
        echo=False,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    with session_factory() as db:
        db.add(Document(
            id="document-delete-claim-race",
            title="Delete claim race",
            source_type="url",
            source_url="https://example.com/delete-race",
            status="queued",
        ))
        db.commit()
        job = enqueue_ingestion_job(
            db,
            document_id="document-delete-claim-race",
            job_type="url",
            payload={"url": "https://example.com/delete-race"},
        )
        db.commit()
        job_id = job.id

    snapshot_ready = threading.Event()
    allow_delete = threading.Event()
    processor_started = threading.Event()
    release_processor = threading.Event()

    def pause_before_atomic_delete(
        _connection,
        _cursor,
        statement,
        _parameters,
        context,
        _executemany,
    ):
        normalized = " ".join(statement.lower().split())
        if (
            context.execution_options.get("delete_claim_race")
            and normalized.startswith("delete from ingestion_jobs")
            and "status" in normalized
            and not snapshot_ready.is_set()
        ):
            snapshot_ready.set()
            assert allow_delete.wait(timeout=2)

    def pause_after_legacy_snapshot(
        _connection,
        _cursor,
        statement,
        _parameters,
        context,
        _executemany,
    ):
        normalized = " ".join(statement.lower().split())
        if (
            context.execution_options.get("delete_claim_race")
            and normalized.startswith("select")
            and "from ingestion_jobs" in normalized
            and not snapshot_ready.is_set()
        ):
            snapshot_ready.set()
            assert allow_delete.wait(timeout=2)

    event.listen(engine, "before_cursor_execute", pause_before_atomic_delete)
    event.listen(engine, "after_cursor_execute", pause_after_legacy_snapshot)

    limiter = ConcurrencyLimiter(max_concurrent=1)
    release_all_operation_leases()
    retain_operation_lease(
        job_id,
        limiter.acquire("ingest:user"),
    )
    service = queued_service()

    def blocking_processor(db, claimed_job):
        document = claimed_job.document
        processor_started.set()
        release_processor.wait(timeout=2)
        document.status = "ready"
        db.commit()

    def delete_document():
        with session_factory() as db:
            db.connection(execution_options={"delete_claim_race": True})
            return service.delete_document(
                db,
                "document-delete-claim-race",
            )

    async def scenario():
        delete_task = asyncio.create_task(asyncio.to_thread(delete_document))
        assert await asyncio.to_thread(snapshot_ready.wait, 1)

        worker = IngestionJobWorker(
            session_factory=session_factory,
            processor=blocking_processor,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await asyncio.to_thread(processor_started.wait, 1)
            allow_delete.set()
            assert await delete_task
            assert limiter.active("ingest:user") == 1
        finally:
            allow_delete.set()
            release_processor.set()
            await worker.stop()

    try:
        asyncio.run(scenario())
        assert limiter.active("ingest:user") == 0
    finally:
        allow_delete.set()
        release_processor.set()
        release_all_operation_leases()
        event.remove(
            engine,
            "before_cursor_execute",
            pause_before_atomic_delete,
        )
        event.remove(
            engine,
            "after_cursor_execute",
            pause_after_legacy_snapshot,
        )
        service.executor.shutdown(wait=True)
        engine.dispose()


def test_retry_removes_partial_index_before_rebuilding(tmp_path):
    """A crash after a partial embedding commit cannot leave duplicates.

    Args:
        tmp_path: Per-test file database directory.

    Returns:
        None.
    """
    engine = create_engine(
        "sqlite:///%s" % (tmp_path / "retry.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    embedding_service = CommitThenFailEmbeddingService()
    service = DocumentService(
        chunking_service=ChunkingService(chunk_size=18, chunk_overlap=0),
        embedding_service=embedding_service,
    )
    service.url_adapter = StaticURLAdapter()

    with session_factory() as db:
        db.add(Document(
            id="document-1",
            title="Retry source",
            source_type="url",
            source_url="https://example.com/retry",
            status="queued",
        ))
        db.commit()
        first = enqueue_ingestion_job(
            db,
            document_id="document-1",
            job_type="url",
            payload={"url": "https://example.com/retry"},
        )
        db.commit()
        first_id = first.id

    async def scenario():
        worker = IngestionJobWorker(
            session_factory=session_factory,
            processor=lambda db, job: service.process_ingestion_job(
                db,
                document_id=job.document_id,
                job_type=job.job_type,
                payload=job.payload_json,
            ),
            concurrency=1,
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await wait_for_terminal_job(
                session_factory,
                first_id,
            ) == "failed"

            with session_factory() as db:
                assert db.query(Chunk).count() == 0
                assert db.query(Embedding).count() == 0
                failed = db.get(IngestionJob, first_id)
                assert failed.document.status == "error"
                assert failed.last_error == {
                    "type": "RuntimeError",
                    "message": "embedding worker crashed",
                }
                retry = enqueue_ingestion_job(
                    db,
                    document_id="document-1",
                    job_type="url",
                    payload={"url": "https://example.com/retry"},
                )
                db.commit()
                retry_id = retry.id

            assert await wait_for_terminal_job(
                session_factory,
                retry_id,
            ) == "completed"
        finally:
            await worker.stop()

    try:
        asyncio.run(scenario())
        with session_factory() as db:
            chunks = db.query(Chunk).all()
            embeddings = db.query(Embedding).all()
            assert len(chunks) >= 2
            assert len(embeddings) == len(chunks)
            assert {embedding.chunk_id for embedding in embeddings} == {
                chunk.id for chunk in chunks
            }
            assert db.get(Document, "document-1").status == "ready"
            assert [
                job.status
                for job in db.query(IngestionJob)
                .order_by(IngestionJob.created_at, IngestionJob.id)
                .all()
            ] == ["failed", "completed"]
    finally:
        service.executor.shutdown(wait=True)
        engine.dispose()


def test_chunk_ceiling_failure_keeps_actionable_metadata(tmp_path):
    """Durable failure preserves the chunk-ceiling contract and no index.

    Args:
        tmp_path: Per-test file database directory.

    Returns:
        None.
    """
    class OverLimitChunker:
        def chunk_document(self, db, document_id, max_chunks):
            raise ChunkLimitExceededError(1001, max_chunks)

    engine = create_engine(
        "sqlite:///%s" % (tmp_path / "over-limit.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    service = DocumentService(
        chunking_service=OverLimitChunker(),
        embedding_service=MustNotEmbed(),
        max_chunks_per_doc=1000,
    )
    service.url_adapter = StaticURLAdapter()
    with session_factory() as db:
        db.add(Document(
            id="document-limit",
            title="Too large",
            source_type="url",
            source_url="https://example.com/large",
            status="queued",
        ))
        db.commit()
        job = enqueue_ingestion_job(
            db,
            document_id="document-limit",
            job_type="url",
            payload={"url": "https://example.com/large"},
        )
        db.commit()
        job_id = job.id

    async def scenario():
        worker = IngestionJobWorker(
            session_factory=session_factory,
            processor=lambda db, claimed_job: service.process_ingestion_job(
                db,
                document_id=claimed_job.document_id,
                job_type=claimed_job.job_type,
                payload=claimed_job.payload_json,
            ),
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await wait_for_terminal_job(
                session_factory,
                job_id,
            ) == "failed"
        finally:
            await worker.stop()

    try:
        asyncio.run(scenario())
        with session_factory() as db:
            failed = db.get(IngestionJob, job_id)
            assert failed.last_error["type"] == "ChunkLimitExceededError"
            assert failed.document.status == "error"
            assert failed.document.meta_json["indexing_failure"] == {
                "code": "chunk_limit_exceeded",
                "chunk_count": 1001,
                "max_chunks": 1000,
                "action": (
                    "Split it into smaller sources or ask your administrator to "
                    "raise the per-source chunk limit."
                ),
            }
            assert db.query(Chunk).count() == 0
            assert db.query(Embedding).count() == 0
    finally:
        service.executor.shutdown(wait=True)
        engine.dispose()


def test_successful_retry_clears_stale_chunk_ceiling_metadata(tmp_path):
    """A recovered source cannot remain labeled as over-limit after success.

    Args:
        tmp_path: Per-test file database directory.

    Returns:
        None.
    """
    class FailOnceChunker:
        def __init__(self):
            self.calls = 0
            self.delegate = ChunkingService(
                chunk_size=18,
                chunk_overlap=0,
            )

        def chunk_document(self, db, document_id, max_chunks):
            self.calls += 1
            if self.calls == 1:
                raise ChunkLimitExceededError(1001, max_chunks)
            return self.delegate.chunk_document(
                db,
                document_id,
                max_chunks=max_chunks,
            )

    engine = create_engine(
        "sqlite:///%s" % (tmp_path / "chunk-limit-retry.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    service = DocumentService(
        chunking_service=FailOnceChunker(),
        embedding_service=StableEmbeddingService(),
        max_chunks_per_doc=1000,
    )
    service.url_adapter = StaticURLAdapter()
    with session_factory() as db:
        db.add(Document(
            id="document-limit-retry",
            title="Retry after limit",
            source_type="url",
            source_url="https://example.com/limit-retry",
            status="queued",
            meta_json={"preserved": True},
        ))
        db.commit()
        first_job = enqueue_ingestion_job(
            db,
            document_id="document-limit-retry",
            job_type="url",
            payload={"url": "https://example.com/limit-retry"},
        )
        db.commit()
        first_job_id = first_job.id

    async def scenario():
        worker = IngestionJobWorker(
            session_factory=session_factory,
            processor=lambda db, job: service.process_ingestion_job(
                db,
                document_id=job.document_id,
                job_type=job.job_type,
                payload=job.payload_json,
            ),
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await wait_for_terminal_job(
                session_factory,
                first_job_id,
            ) == "failed"
            with session_factory() as db:
                failed_document = db.get(Document, "document-limit-retry")
                assert "indexing_failure" in failed_document.meta_json
                retry_job = enqueue_ingestion_job(
                    db,
                    document_id=failed_document.id,
                    job_type="url",
                    payload={"url": "https://example.com/limit-retry"},
                )
                db.commit()
                retry_job_id = retry_job.id

            assert await wait_for_terminal_job(
                session_factory,
                retry_job_id,
            ) == "completed"
        finally:
            await worker.stop()

    try:
        asyncio.run(scenario())
        with session_factory() as db:
            recovered_document = db.get(Document, "document-limit-retry")
            assert recovered_document.status == "ready"
            assert recovered_document.meta_json["preserved"] is True
            assert "indexing_failure" not in recovered_document.meta_json
            assert db.query(Chunk).count() > 0
            assert db.query(Embedding).count() == db.query(Chunk).count()
    finally:
        service.executor.shutdown(wait=True)
        engine.dispose()


def test_unsafe_url_refusal_becomes_a_durable_failed_job(tmp_path):
    """Worker-side SSRF refusal leaves no searchable partial index.

    Args:
        tmp_path: Per-test file database directory.

    Returns:
        None.
    """
    class RefusingURLAdapter:
        def extract_content(self, url):
            raise UnsafeURLError("URL destination must be globally routable")

    engine = create_engine(
        "sqlite:///%s" % (tmp_path / "unsafe-url.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    service = DocumentService(
        chunking_service=MustNotChunk(),
        embedding_service=MustNotEmbed(),
    )
    service.url_adapter = RefusingURLAdapter()
    with session_factory() as db:
        db.add(Document(
            id="document-unsafe",
            title="Unsafe URL",
            source_type="url",
            source_url="http://127.0.0.1/admin",
            status="queued",
        ))
        db.commit()
        job = enqueue_ingestion_job(
            db,
            document_id="document-unsafe",
            job_type="url",
            payload={"url": "http://127.0.0.1/admin"},
        )
        db.commit()
        job_id = job.id

    async def scenario():
        worker = IngestionJobWorker(
            session_factory=session_factory,
            processor=lambda db, claimed_job: service.process_ingestion_job(
                db,
                document_id=claimed_job.document_id,
                job_type=claimed_job.job_type,
                payload=claimed_job.payload_json,
            ),
            poll_interval=0.01,
        )
        await worker.start()
        try:
            assert await wait_for_terminal_job(
                session_factory,
                job_id,
            ) == "failed"
        finally:
            await worker.stop()

    try:
        asyncio.run(scenario())
        with session_factory() as db:
            failed = db.get(IngestionJob, job_id)
            assert failed.last_error == {
                "type": "UnsafeURLError",
                "message": "URL destination must be globally routable",
            }
            assert failed.document.status == "error"
            assert db.query(Chunk).count() == 0
            assert db.query(Embedding).count() == 0
    finally:
        service.executor.shutdown(wait=True)
        engine.dispose()
