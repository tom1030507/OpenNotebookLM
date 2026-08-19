"""Document ingestion router."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.schemas import (
    FileUploadResponse, URLUploadRequest, YouTubeUploadRequest,
    DocumentResponse, DocumentStatusResponse
)
from app.db.models import User
from app.services.documents import DocumentService
from app.config import get_settings
from app.routers.auth import get_current_user
from app.routers.ownership import require_document, require_project

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()
settings = get_settings()

# Initialize document service
document_service = DocumentService()


@router.post("/projects/{project_id}/upload", response_model=FileUploadResponse)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Upload a file to one of the caller's projects.
    
    Supports PDF files for now.
    """
    require_project(db, project_id, current_user)
    
    # Validate file type
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400, 
            detail="Only PDF files are supported in this version"
        )
    
    # Check file size
    file_size = 0
    contents = await file.read()
    file_size = len(contents)
    await file.seek(0)  # Reset file pointer
    
    if file_size > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum of {settings.max_file_size_mb}MB"
        )
    
    try:
        # Process the upload
        document = await document_service.process_pdf_upload(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            file=file.file,
            filename=file.filename,
            title=title
        )
        
        return FileUploadResponse(
            doc_id=document.id,
            status=document.status,
            message="File uploaded successfully. Processing started."
        )
        
    except Exception as e:
        logger.error("File upload failed", 
                    project_id=project_id,
                    filename=file.filename,
                    error=str(e))
        raise HTTPException(status_code=500, detail="File upload failed")


@router.post("/projects/{project_id}/upload-url", response_model=FileUploadResponse)
async def upload_url(
    project_id: str,
    request: URLUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a URL document to one of the caller's projects."""
    require_project(db, project_id, current_user)
    
    try:
        # Process the URL
        document = await document_service.process_url(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            url=request.url,
            title=request.title
        )
        
        return FileUploadResponse(
            doc_id=document.id,
            status=document.status,
            message="URL added successfully. Content extraction started."
        )
        
    except Exception as e:
        logger.error("URL processing failed",
                    project_id=project_id,
                    url=request.url,
                    error=str(e))
        raise HTTPException(status_code=500, detail="URL processing failed")


@router.post("/projects/{project_id}/upload-youtube", response_model=FileUploadResponse)
async def upload_youtube(
    project_id: str,
    request: YouTubeUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a YouTube video transcript to one of the caller's projects."""
    require_project(db, project_id, current_user)
    
    if not settings.enable_yt_transcription:
        raise HTTPException(
            status_code=400,
            detail="YouTube transcription is disabled"
        )
    
    try:
        # Process the YouTube URL
        document = await document_service.process_youtube(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            youtube_url=request.youtube_url,
            title=request.title
        )
        
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
