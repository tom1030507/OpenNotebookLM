"""Document ingestion router."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.schemas import (
    FileUploadResponse, URLUploadRequest, YouTubeUploadRequest,
    DocumentResponse, DocumentStatusResponse
)
from app.db.models import User
from app.services.documents import DocumentService, UploadTooLargeError
from app.config import get_settings
from app.routers.auth import get_current_user
from app.routers.ownership import require_document, require_project
from app.routers.rate_limit import (
    acquire_account_lease,
    enforce_account_rate_limit,
    get_concurrency_limiter,
    get_rate_limiter,
)
from app.services.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter
from app.utils.network import UnsafeURLError

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()
settings = get_settings()

# Initialize document service
document_service = DocumentService()


def _begin_ingestion(
    user_id: str,
    request_limiter: SlidingWindowRateLimiter,
    concurrency_limiter: ConcurrencyLimiter,
):
    """Apply the per-account import rate and active-operation boundaries.

    Args:
        user_id: Authenticated account identifier.
        request_limiter: Sliding-window request limiter.
        concurrency_limiter: Active-operation limiter.

    Returns:
        A lease the route must release in ``finally``.
    """
    if settings.rate_limit_enabled:
        enforce_account_rate_limit(
            request_limiter,
            "ingest",
            user_id,
            limit=10,
            window_seconds=60,
        )
    return acquire_account_lease(concurrency_limiter, "ingest", user_id)


@router.post("/projects/{project_id}/upload", response_model=FileUploadResponse)
async def upload_file(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
):
    """Stream a PDF into one of the caller's projects.

    Args:
        project_id: Project receiving the document.
        request: Incoming request, used for early Content-Length rejection.
        file: Multipart PDF upload.
        title: Optional document title.
        db: Database session.
        current_user: Authenticated caller.
        request_limiter: Per-account ingestion request limiter.
        concurrency_limiter: Per-account active-ingestion limiter.

    Returns:
        Created document identifier and queued status.
    """
    require_project(db, project_id, current_user)

    declared_length = request.headers.get("Content-Length")
    if declared_length is not None:
        try:
            declared_bytes = int(declared_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if declared_bytes < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if declared_bytes > settings.max_file_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File size exceeds maximum of {settings.max_file_size_mb}MB",
            )
    
    # Validate file type
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400, 
            detail="Only PDF files are supported in this version"
        )
    
    # Starlette has already counted the multipart part while spooling it. Use
    # that count for an early refusal, then the service enforces the same limit
    # again while copying in bounded blocks so a missing size cannot bypass it.
    if file.size is not None and file.size > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum of {settings.max_file_size_mb}MB"
        )
    lease = _begin_ingestion(
        current_user.id,
        request_limiter,
        concurrency_limiter,
    )
    lease_transferred = False
    try:
        # Process the upload
        document = await document_service.process_pdf_upload(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            file=file.file,
            filename=file.filename,
            title=title,
            completion_callback=lease.release,
        )
        lease_transferred = True
        
        return FileUploadResponse(
            doc_id=document.id,
            status=document.status,
            message="File uploaded successfully. Processing started."
        )
        
    except UploadTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        logger.error("File upload failed", 
                    project_id=project_id,
                    filename=file.filename,
                    error=str(e))
        raise HTTPException(status_code=500, detail="File upload failed")
    finally:
        if not lease_transferred:
            lease.release()


@router.post("/projects/{project_id}/upload-url", response_model=FileUploadResponse)
async def upload_url(
    project_id: str,
    request: URLUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
):
    """Add a bounded public URL document to one caller-owned project.

    Args:
        project_id: Project receiving the document.
        request: URL and optional title.
        db: Database session.
        current_user: Authenticated caller.
        request_limiter: Per-account ingestion request limiter.
        concurrency_limiter: Per-account active-ingestion limiter.

    Returns:
        Created document identifier and queued status.
    """
    require_project(db, project_id, current_user)
    
    lease = _begin_ingestion(
        current_user.id,
        request_limiter,
        concurrency_limiter,
    )
    lease_transferred = False
    try:
        # Process the URL
        document = await document_service.process_url(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            url=request.url,
            title=request.title,
            completion_callback=lease.release,
        )
        lease_transferred = True
        
        return FileUploadResponse(
            doc_id=document.id,
            status=document.status,
            message="URL added successfully. Content extraction started."
        )
        
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("URL processing failed",
                    project_id=project_id,
                    url=request.url,
                    error=str(e))
        raise HTTPException(status_code=500, detail="URL processing failed")
    finally:
        if not lease_transferred:
            lease.release()


@router.post("/projects/{project_id}/upload-youtube", response_model=FileUploadResponse)
async def upload_youtube(
    project_id: str,
    request: YouTubeUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
):
    """Add a YouTube transcript to one caller-owned project.

    Args:
        project_id: Project receiving the document.
        request: Video URL and optional title.
        db: Database session.
        current_user: Authenticated caller.
        request_limiter: Per-account ingestion request limiter.
        concurrency_limiter: Per-account active-ingestion limiter.

    Returns:
        Created document identifier and queued status.
    """
    require_project(db, project_id, current_user)
    
    if not settings.enable_yt_transcription:
        raise HTTPException(
            status_code=400,
            detail="YouTube transcription is disabled"
        )
    lease = _begin_ingestion(
        current_user.id,
        request_limiter,
        concurrency_limiter,
    )
    lease_transferred = False
    try:
        # Process the YouTube URL
        document = await document_service.process_youtube(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            youtube_url=request.youtube_url,
            title=request.title,
            completion_callback=lease.release,
        )
        lease_transferred = True
        
        return FileUploadResponse(
            doc_id=document.id,
            status=document.status,
            message="YouTube video added successfully. Transcript extraction started."
        )
        
    except Exception as e:
        logger.error("YouTube processing failed",
                    project_id=project_id,
                    youtube_url=request.youtube_url,
                    error=str(e))
        raise HTTPException(status_code=500, detail="YouTube processing failed")
    finally:
        if not lease_transferred:
            lease.release()


@router.get("/docs/{doc_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get the processing status of one of the caller's documents."""
    document = require_document(db, doc_id, current_user)
    
    # Calculate progress (simple estimation)
    progress = None
    if document.status == "queued":
        progress = 0.0
    elif document.status == "processing":
        progress = 0.5
    elif document.status == "ready":
        progress = 1.0
    elif document.status == "error":
        progress = 0.0
    
    return DocumentStatusResponse(
        id=document.id,
        status=document.status,
        meta=document.meta_json,
        error_message=document.error_message,
        progress=progress
    )


@router.get("/docs/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get details of one of the caller's documents."""
    document = require_document(db, doc_id, current_user)
    
    # Count chunks if available
    chunk_count = len(document.chunks) if document.chunks else 0
    
    return DocumentResponse(
        id=document.id,
        title=document.title,
        source_type=document.source_type,
        source_url=document.source_url,
        meta_json=document.meta_json,
        status=document.status,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
        chunk_count=chunk_count
    )


@router.delete("/docs/{doc_id}")
async def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete one of the caller's documents."""
    require_document(db, doc_id, current_user)
    success = document_service.delete_document(db, doc_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {"status": "success", "message": "Document deleted successfully"}
