"""Project management router."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.schemas import (
    ProjectCreate, ProjectUpdate, ProjectResponse, 
    ProjectListResponse, DocumentResponse, ConversationResponse
)
from app.services.projects import ProjectService

router = APIRouter()
logger = structlog.get_logger()


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db)
):
    """Create a new project."""
    try:
        project = ProjectService.create_project(db, project_data)
        return ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            meta_json=project.meta_json,
            created_at=project.created_at,
            updated_at=project.updated_at,
            document_count=0,
            conversation_count=0
        )
    except Exception as e:
        logger.error("Failed to create project", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create project")


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List all projects with pagination."""
    try:
        skip = (page - 1) * per_page
        projects, total = ProjectService.get_projects(db, skip=skip, limit=per_page, search=search)
        
        project_responses = [
            ProjectResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                meta_json=p.meta_json,
                created_at=p.created_at,
                updated_at=p.updated_at,
                document_count=getattr(p, 'document_count', 0),
                conversation_count=getattr(p, 'conversation_count', 0)
            ) for p in projects
        ]
        
        return ProjectListResponse(
            projects=project_responses,
            total=total,
            page=page,
            per_page=per_page
        )
    except Exception as e:
        logger.error("Failed to list projects", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list projects")


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific project by ID."""
    project = ProjectService.get_project(db, project_id)
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        meta_json=project.meta_json,
        created_at=project.created_at,
        updated_at=project.updated_at,
        document_count=getattr(project, 'document_count', 0),
        conversation_count=getattr(project, 'conversation_count', 0)
    )


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db)
):
    """Update a project."""
    project = ProjectService.update_project(db, project_id, project_update)
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        meta_json=project.meta_json,
        created_at=project.created_at,
        updated_at=project.updated_at,
        document_count=getattr(project, 'document_count', 0),
        conversation_count=getattr(project, 'conversation_count', 0)
    )


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db)
):
    """Delete a project."""
    success = ProjectService.delete_project(db, project_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {"status": "success", "message": "Project deleted successfully"}


@router.get("/projects/{project_id}/documents", response_model=list[DocumentResponse])
async def get_project_documents(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get documents associated with a project."""
    # First check if project exists
    project = ProjectService.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    documents = ProjectService.get_project_documents(db, project_id, skip=skip, limit=limit)
    
    return [
        DocumentResponse(
            id=doc.id,
            title=doc.title,
            source_type=doc.source_type,
            source_url=doc.source_url,
            meta_json=doc.meta_json,
            status=doc.status,
            error_message=doc.error_message,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            chunk_count=getattr(doc, 'chunk_count', 0)
        ) for doc in documents
    ]


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationResponse])
async def get_project_conversations(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get conversations associated with a project."""
    # First check if project exists
    project = ProjectService.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    conversations = ProjectService.get_project_conversations(db, project_id, skip=skip, limit=limit)
    
    return [
        ConversationResponse(
            id=conv.id,
            project_id=conv.project_id,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=getattr(conv, 'message_count', 0)
        ) for conv in conversations
    ]


@router.post("/projects/{project_id}/documents/{document_id}")
async def add_document_to_project(
    project_id: str,
    document_id: str,
    db: Session = Depends(get_db)
):
    """Add a document to a project."""
    success = ProjectService.add_document_to_project(db, project_id, document_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Project or document not found")
    
    return {"status": "success", "message": "Document added to project"}


@router.delete("/projects/{project_id}/documents/{document_id}")
async def remove_document_from_project(
    project_id: str,
    document_id: str,
    db: Session = Depends(get_db)
):
    """Remove a document from a project."""
    success = ProjectService.remove_document_from_project(db, project_id, document_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Link not found")
    
    return {"status": "success", "message": "Document removed from project"}
