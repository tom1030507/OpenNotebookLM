"""Project management router."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.schemas import (
    ChatSettings, ProjectCreate, ProjectUpdate, ProjectResponse, 
    ProjectListResponse, DocumentResponse, ProjectMemberCreate,
    ProjectMemberUpdate, ProjectMemberResponse,
)
from app.db.models import User
from app.services.projects import ProjectService
from app.routers.auth import get_current_user
from app.routers.ownership import project_role, require_document, require_project

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new project owned by the caller."""
    try:
        project = ProjectService.create_project(db, project_data, current_user.id)
        return ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            meta_json=project.meta_json,
            cover_emoji=project.cover_emoji,
            cover_color=project.cover_color,
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List the caller's projects with pagination."""
    try:
        skip = (page - 1) * per_page
        projects, total = ProjectService.get_projects(
            db, current_user.id, skip=skip, limit=per_page, search=search
        )
        
        project_responses = [
            ProjectResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                meta_json=p.meta_json,
                cover_emoji=p.cover_emoji,
                cover_color=p.cover_color,
                created_at=p.created_at,
                updated_at=p.updated_at,
                document_count=getattr(p, 'document_count', 0),
                conversation_count=getattr(p, 'conversation_count', 0),
                role=project_role(db, p, current_user),
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get one of the caller's projects by ID."""
    require_project(db, project_id, current_user, min_role="viewer")
    project = ProjectService.get_project(db, project_id, current_user.id)
    
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        meta_json=project.meta_json,
        cover_emoji=project.cover_emoji,
        cover_color=project.cover_color,
        created_at=project.created_at,
        updated_at=project.updated_at,
        document_count=getattr(project, 'document_count', 0),
        conversation_count=getattr(project, 'conversation_count', 0),
        role=project_role(db, project, current_user),
    )


@router.get(
    "/projects/{project_id}/members",
    response_model=list[ProjectMemberResponse],
)
async def list_project_members(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the owner and members of one owned project.

    Args:
        project_id: Project id.
        db: Database session.
        current_user: Signed-in owner.

    Returns:
        Owner and member identities with their project roles.
    """
    project = require_project(db, project_id, current_user)
    return ProjectService.get_project_members(db, project)


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=201,
)
async def add_project_member(
    project_id: str,
    member: ProjectMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add an existing account to one owned project.

    Args:
        project_id: Project id.
        member: Account identifier and role.
        db: Database session.
        current_user: Signed-in owner.

    Returns:
        The stored member.

    Raises:
        HTTPException: 404 for inaccessible project/account, or 409 for duplicates.
    """
    project = require_project(db, project_id, current_user)
    try:
        return ProjectService.add_project_member(
            db, project, member.username, member.email, member.role
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.patch(
    "/projects/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
)
async def update_project_member(
    project_id: str,
    user_id: str,
    member: ProjectMemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change a member's role in one owned project.

    Args:
        project_id: Project id.
        user_id: Member account id.
        member: New viewer or editor role.
        db: Database session.
        current_user: Signed-in owner.

    Returns:
        The updated member.
    """
    require_project(db, project_id, current_user)
    updated = ProjectService.update_project_member(
        db, project_id, user_id, member.role
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return updated


@router.delete("/projects/{project_id}/members/{user_id}")
async def remove_project_member(
    project_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a member from one owned project.

    Args:
        project_id: Project id.
        user_id: Member account id.
        db: Database session.
        current_user: Signed-in owner.

    Returns:
        A success status.
    """
    require_project(db, project_id, current_user)
    if not ProjectService.remove_project_member(db, project_id, user_id):
        raise HTTPException(status_code=404, detail="Member not found")
    return {"status": "success", "message": "Project member removed"}


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update one of the caller's projects."""
    require_project(db, project_id, current_user)
    project = ProjectService.update_project(db, project_id, project_update)
    
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        meta_json=project.meta_json,
        cover_emoji=project.cover_emoji,
        cover_color=project.cover_color,
        created_at=project.created_at,
        updated_at=project.updated_at,
        document_count=getattr(project, 'document_count', 0),
        conversation_count=getattr(project, 'conversation_count', 0)
    )


@router.post("/projects/{project_id}/duplicate", response_model=ProjectResponse)
async def duplicate_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Duplicate one of the caller's projects.

    Args:
        project_id: Source project id.
        db: Database session.
        current_user: Signed-in project owner.

    Returns:
        The new project and its document/conversation counts.
    """
    source = require_project(db, project_id, current_user)
    try:
        duplicate = ProjectService.duplicate_project(db, source, current_user.id)
    except Exception as e:
        logger.error("Failed to duplicate project", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to duplicate project")

    duplicate = ProjectService.get_project(db, duplicate.id, current_user.id)
    return ProjectResponse(
        id=duplicate.id,
        name=duplicate.name,
        description=duplicate.description,
        meta_json=duplicate.meta_json,
        cover_emoji=duplicate.cover_emoji,
        cover_color=duplicate.cover_color,
        created_at=duplicate.created_at,
        updated_at=duplicate.updated_at,
        document_count=getattr(duplicate, "document_count", 0),
        conversation_count=getattr(duplicate, "conversation_count", 0),
    )


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete one of the caller's projects."""
    require_project(db, project_id, current_user)
    ProjectService.delete_project(db, project_id)
    
    return {"status": "success", "message": "Project deleted successfully"}


@router.get("/projects/{project_id}/chat-settings", response_model=ChatSettings)
async def get_chat_settings(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get the chat settings of one of the caller's projects."""
    project = require_project(db, project_id, current_user, min_role="viewer")
    return ProjectService.get_chat_settings(project)


@router.put("/projects/{project_id}/chat-settings", response_model=ChatSettings)
async def update_chat_settings(
    project_id: str,
    chat_settings: ChatSettings,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Replace the chat settings of one of the caller's projects."""
    project = require_project(db, project_id, current_user, min_role="editor")
    return ProjectService.update_chat_settings(db, project, chat_settings)


@router.get("/projects/{project_id}/documents", response_model=list[DocumentResponse])
async def get_project_documents(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get documents in one of the caller's projects."""
    require_project(db, project_id, current_user, min_role="viewer")
    
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
            chunk_count=getattr(doc, 'chunk_count', 0),
            is_owned_by_caller=doc.user_id == current_user.id,
        ) for doc in documents
    ]


@router.post("/projects/{project_id}/documents/{document_id}")
async def add_document_to_project(
    project_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add one of the caller's documents to one of the caller's projects."""
    # Both ends are checked. Authorising only the project would let a caller
    # attach someone else's document to their own project and then read it
    # through the project's document list.
    require_project(db, project_id, current_user, min_role="editor")
    require_document(db, document_id, current_user, owner_only=True)

    success = ProjectService.add_document_to_project(db, project_id, document_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Project or document not found")
    
    return {"status": "success", "message": "Document added to project"}


@router.delete("/projects/{project_id}/documents/{document_id}")
async def remove_document_from_project(
    project_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove a document from one of the caller's projects."""
    require_project(db, project_id, current_user, min_role="editor")
    success = ProjectService.remove_document_from_project(db, project_id, document_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Link not found")
    
    return {"status": "success", "message": "Document removed from project"}
