"""Project management router."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.config import get_settings
from app.schemas import (
    ChatSettings, ProjectCreate, ProjectUpdate, ProjectResponse, 
    ProjectListResponse, DocumentResponse, ProjectMemberCreate,
    ProjectMemberUpdate, ProjectMemberResponse, ProjectAnalyticsResponse,
    ProjectTagsUpdate, ProjectSourceGroupAssignmentRequest,
    ProjectSourceGroupCreate, ProjectSourceGroupResponse,
    ProjectSourceGroupUpdate, WatchedFolderRequest, WatchedFolderResponse,
)
from app.db.models import User
from app.services.projects import ProjectService
from app.services.trash import TrashService
from app.routers.auth import get_current_user
from app.routers.ownership import project_role, require_document, require_project
from app.services.project_analytics import get_project_analytics
from app.services.watched_folders import resolve_watched_folder
from app.services.llm import is_model_available

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
                tags=getattr(p, 'tags', []),
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
        tags=ProjectService.get_project_tags(db, current_user.id, project.id),
    )


@router.put("/projects/{project_id}/tags", response_model=list[str])
def update_project_tags(
    project_id: str,
    request: ProjectTagsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[str]:
    """Replace the caller's private tags on a project they can view.

    Args:
        project_id: Project whose tags are being changed.
        request: Replacement tag list.
        db: Database session.
        current_user: Signed-in account that owns these tags.

    Returns:
        The caller's saved tags.
    """
    require_project(db, project_id, current_user, min_role="viewer")
    return ProjectService.replace_project_tags(
        db,
        project_id,
        current_user.id,
        request.tags,
    )


@router.get(
    "/projects/{project_id}/source-groups",
    response_model=list[ProjectSourceGroupResponse],
)
def list_source_groups(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List shared source groups visible to the project member.

    Args:
        project_id: Project whose groups are requested.
        db: Database session.
        current_user: Signed-in project member.

    Returns:
        Groups with the document ids assigned to each.
    """
    require_project(db, project_id, current_user, min_role="viewer")
    return ProjectService.get_source_groups(db, project_id)


@router.post(
    "/projects/{project_id}/source-groups",
    response_model=ProjectSourceGroupResponse,
    status_code=201,
)
def create_source_group(
    project_id: str,
    request: ProjectSourceGroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectSourceGroupResponse:
    """Create a source group shared by project members.

    Args:
        project_id: Project that owns the new group.
        request: Validated group name.
        db: Database session.
        current_user: Signed-in project owner or editor.

    Returns:
        The created, initially empty group.
    """
    require_project(db, project_id, current_user, min_role="editor")
    try:
        group = ProjectService.create_source_group(db, project_id, request.name)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ProjectSourceGroupResponse(
        id=group.id,
        name=group.name,
        document_ids=[],
    )


@router.patch(
    "/projects/{project_id}/source-groups/{group_id}",
    response_model=ProjectSourceGroupResponse,
)
def rename_source_group(
    project_id: str,
    group_id: str,
    request: ProjectSourceGroupUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectSourceGroupResponse:
    """Rename one project source group.

    Args:
        project_id: Project that owns the group.
        group_id: Group being renamed.
        request: Validated replacement name.
        db: Database session.
        current_user: Signed-in project owner or editor.

    Returns:
        The renamed group and its current source ids.
    """
    require_project(db, project_id, current_user, min_role="editor")
    try:
        group = ProjectService.rename_source_group(
            db,
            project_id,
            group_id,
            request.name,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if group is None:
        raise HTTPException(status_code=404, detail="Source group not found")
    document_ids = next(
        entry["document_ids"]
        for entry in ProjectService.get_source_groups(db, project_id)
        if entry["id"] == group_id
    )
    return ProjectSourceGroupResponse(
        id=group.id,
        name=group.name,
        document_ids=document_ids,
    )


@router.delete("/projects/{project_id}/source-groups/{group_id}")
def delete_source_group(
    project_id: str,
    group_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Delete a source group while keeping its sources in the project.

    Args:
        project_id: Project that owns the group.
        group_id: Group being deleted.
        db: Database session.
        current_user: Signed-in project owner or editor.

    Returns:
        A success status after assignments have been cleared.
    """
    require_project(db, project_id, current_user, min_role="editor")
    if not ProjectService.delete_source_group(db, project_id, group_id):
        raise HTTPException(status_code=404, detail="Source group not found")
    return {"status": "success"}


@router.put(
    "/projects/{project_id}/documents/{document_id}/group",
    response_model=list[ProjectSourceGroupResponse],
)
def assign_source_group(
    project_id: str,
    document_id: str,
    request: ProjectSourceGroupAssignmentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Move one project source into a group or back to ungrouped.

    Args:
        project_id: Project containing the source.
        document_id: Source being moved.
        request: Group id in this project, or null to ungroup.
        db: Database session.
        current_user: Signed-in project owner or editor.

    Returns:
        The project's groups and their updated source ids.
    """
    require_project(db, project_id, current_user, min_role="editor")
    require_document(db, document_id, current_user)
    if not ProjectService.assign_source_group(
        db,
        project_id,
        document_id,
        request.group_id,
    ):
        raise HTTPException(status_code=404, detail="Project source or group not found")
    return ProjectService.get_source_groups(db, project_id)


@router.get(
    "/projects/{project_id}/analytics",
    response_model=ProjectAnalyticsResponse,
)
async def get_project_analytics_route(
    project_id: str,
    days: int = Query(7),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return owner-only project usage analytics.

    Args:
        project_id: Project id from the request.
        days: Number of UTC calendar days to include.
        db: Database session.
        current_user: Signed-in project owner.

    Returns:
        Activity, rating, citation, and uncited-source summaries.
    """
    if days not in (7, 30, 90):
        raise HTTPException(status_code=422, detail="days must be 7, 30, or 90")
    require_project(db, project_id, current_user)
    return get_project_analytics(db, project_id, current_user.id, days)


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
        conversation_count=getattr(project, 'conversation_count', 0),
        tags=ProjectService.get_project_tags(db, current_user.id, project.id),
    )


@router.get(
    "/projects/{project_id}/watched-folder",
    response_model=WatchedFolderResponse,
)
def get_watched_folder(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WatchedFolderResponse:
    """Return watched-folder settings to the project owner only.

    Args:
        project_id: Project whose watch setting is being read.
        db: Database session.
        current_user: Signed-in project owner.

    Returns:
        Whether server-side watching is configured and the project path.
    """
    project = require_project(db, project_id, current_user, min_role="owner")
    return WatchedFolderResponse(
        enabled=bool(get_settings().watched_folder_root),
        path=project.watched_folder,
    )


@router.put(
    "/projects/{project_id}/watched-folder",
    response_model=WatchedFolderResponse,
)
def update_watched_folder(
    project_id: str,
    request: WatchedFolderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WatchedFolderResponse:
    """Set or clear a project folder within the configured server root.

    Args:
        project_id: Project to update.
        request: Server path selected by the owner, or null to clear it.
        db: Database session.
        current_user: Signed-in project owner.

    Returns:
        The new owner-only watched-folder setting.
    """
    project = require_project(db, project_id, current_user, min_role="owner")
    path = (request.path or "").strip()
    root = get_settings().watched_folder_root
    if path and not root:
        raise HTTPException(
            status_code=503,
            detail="Server-side folder watching is not configured",
        )
    if path:
        try:
            project.watched_folder = str(resolve_watched_folder(root, path))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    else:
        project.watched_folder = None
    db.commit()
    return WatchedFolderResponse(enabled=bool(root), path=project.watched_folder)


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
        tags=ProjectService.get_project_tags(db, current_user.id, duplicate.id),
    )


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Move one of the caller's projects to Trash.

    Args:
        project_id: Project to trash.
        db: Database session.
        current_user: Authenticated project owner.

    Returns:
        A confirmation.
    """
    project = require_project(db, project_id, current_user)
    TrashService.trash_project(db, project)
    
    return {"status": "success", "message": "Project moved to trash"}


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
    if (
        "model" in chat_settings.model_fields_set
        and chat_settings.model is not None
        and not is_model_available(chat_settings.model)
    ):
        raise HTTPException(status_code=422, detail="Model is not available")
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
            last_synced_at=doc.last_synced_at,
            last_sync_changed=doc.last_sync_changed,
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
