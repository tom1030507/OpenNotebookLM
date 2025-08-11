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
from app.services.documents import DocumentService
from app.services.projects import ProjectService
from app.config import get_settings

router = APIRouter()
logger = structlog.get_logger()
settings = get_settings()

# Initialize document service
document_service = DocumentService()


@router.post("/projects/{project_id}/upload", response_model=FileUploadResponse)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Upload a file to a project.
    
    Supports PDF files for now.
    """
    # Check if project exists
    project = ProjectService.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
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
    db: Session = Depends(get_db)
):
    """Add a URL document to a project."""
    # Check if project exists
    project = ProjectService.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        # Process the URL
        document = await document_service.process_url(
            db=db,
            project_id=project_id,
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
    db: Session = Depends(get_db)
):
    """Add a YouTube video transcript to a project."""
    # Check if project exists
    project = ProjectService.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
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
    db: Session = Depends(get_db)
):
    """Get the processing status of a document."""
    document = document_service.get_document_status(db, doc_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
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
    db: Session = Depends(get_db)
):
    """Get document details."""
    document = document_service.get_document_status(db, doc_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
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
    db: Session = Depends(get_db)
):
    """Delete a document."""
    success = document_service.delete_document(db, doc_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {"status": "success", "message": "Document deleted successfully"}
