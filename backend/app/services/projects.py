"""Project CRUD service operations."""
import copy
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
import structlog

from app.db.models import (
    AudioOverview,
    Conversation,
    Document,
    Note,
    Project,
    ProjectDocument,
    ProjectMember,
    User,
)
from app.schemas import (
    PROJECT_COVER_EMOJIS,
    ChatSettings,
    ProjectCreate,
    ProjectUpdate,
)

logger = structlog.get_logger()

# Given to a project created without a name. Such a project takes the title its
# generated overview suggests; see services.project_overview.
UNTITLED_PROJECT_NAME = "Untitled notebook"


class ProjectService:
    """Service for project operations."""

    @staticmethod
    def project_document_query(db: Session, project_id: Optional[str] = None):
        """Return linked sources owned by the project owner or a current member.

        Args:
            db: Database session.
            project_id: Optional project whose linked sources are being read.

        Returns:
            A query of linked documents with a source owner authorized to share.
        """
        query = db.query(Document).join(
            ProjectDocument,
            ProjectDocument.document_id == Document.id,
        ).join(
            Project,
            Project.id == ProjectDocument.project_id,
        ).outerjoin(
            ProjectMember,
            and_(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == Document.user_id,
            ),
        ).filter(
            or_(
                Document.user_id == Project.user_id,
                ProjectMember.user_id.isnot(None),
            ),
        )
        if project_id is not None:
            query = query.filter(Project.id == project_id)
        return query

    @staticmethod
    def default_cover_emoji(project_id: str) -> str:
        """Choose a stable cover emoji from the project id.

        Args:
            project_id: UUID assigned to the project.

        Returns:
            One supported emoji, stable for this id.
        """
        return PROJECT_COVER_EMOJIS[
            int(project_id.replace("-", ""), 16) % len(PROJECT_COVER_EMOJIS)
        ]
    
    @staticmethod
    def create_project(db: Session, project_data: ProjectCreate, user_id: str) -> Project:
        """Create a new project owned by the given account.

        Args:
            db: Database session
            project_data: Name, description and metadata
            user_id: Account that will own the project

        Returns:
            The created project
        """
        project_id = str(uuid.uuid4())
        
        project = Project(
            id=project_id,
            user_id=user_id,
            name=project_data.name or UNTITLED_PROJECT_NAME,
            description=project_data.description,
            meta_json=project_data.meta_json or {},
            cover_emoji=ProjectService.default_cover_emoji(project_id),
            auto_title=project_data.name is None,
        )
        
        db.add(project)
        db.commit()
        db.refresh(project)
        
        logger.info("Project created", project_id=project_id, name=project.name)
        return project

    @staticmethod
    def duplicate_project(db: Session, project: Project, user_id: str) -> Project:
        """Copy a project and its caller-owned sources and notes atomically.

        Args:
            db: Database session.
            project: Source project, already checked for ownership.
            user_id: Account that owns both the source and duplicate.

        Returns:
            The newly stored project.
        """
        documents = (
            db.query(ProjectDocument.document_id)
            .join(Document, Document.id == ProjectDocument.document_id)
            .filter(
                ProjectDocument.project_id == project.id,
                Document.user_id == user_id,
            )
            .all()
        )
        notes = db.query(Note).filter(Note.project_id == project.id).all()
        duplicate_id = str(uuid.uuid4())
        duplicate = Project(
            id=duplicate_id,
            user_id=user_id,
            name=f"{project.name} (copy)",
            description=project.description,
            meta_json=copy.deepcopy(project.meta_json or {}),
            chat_role=project.chat_role,
            chat_instructions=project.chat_instructions,
            answer_length=project.answer_length,
            cover_emoji=ProjectService.default_cover_emoji(duplicate_id),
        )
        links = [
            ProjectDocument(project_id=duplicate_id, document_id=row.document_id)
            for row in documents
        ]
        copied_notes = []
        for note in notes:
            payload = copy.deepcopy(note.payload_json)
            if isinstance(payload, dict) and "project_id" in payload:
                # Studio actions use this id for follow-up operations like export.
                payload["project_id"] = duplicate_id
                if "project_name" in payload:
                    payload["project_name"] = duplicate.name
            copied_notes.append(Note(
                id=str(uuid.uuid4()),
                project_id=duplicate_id,
                title=note.title,
                content=note.content,
                origin=note.origin,
                source_message_id=note.source_message_id,
                studio_kind=note.studio_kind,
                payload_json=payload,
            ))

        try:
            db.add_all([duplicate, *links, *copied_notes])
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(duplicate)

        logger.info("Project duplicated", source_project_id=project.id, project_id=duplicate_id)
        return duplicate
    
    @staticmethod
    def get_project(db: Session, project_id: str, user_id: str) -> Optional[Project]:
        """Get a project with counts scoped to the caller's conversations.

        Args:
            db: Database session.
            project_id: Project to load.
            user_id: Account whose private conversations are counted.

        Returns:
            The project, or None when it does not exist.
        """
        project = db.query(Project).filter(Project.id == project_id).first()
        
        if project:
            # Add counts
            project.document_count = ProjectService.project_document_query(
                db, project_id
            ).count()
            conversations = db.query(func.count(Conversation.id)).filter(
                Conversation.project_id == project_id,
            )
            conversations = conversations.filter(
                or_(Conversation.user_id == user_id, Conversation.user_id.is_(None))
                if project.user_id == user_id
                else Conversation.user_id == user_id
            )
            project.conversation_count = conversations.scalar() or 0
        
        return project
    
    @staticmethod
    def get_projects(
        db: Session, 
        user_id: str,
        skip: int = 0, 
        limit: int = 100,
        search: Optional[str] = None
    ) -> tuple[List[Project], int]:
        """Get one account's projects, paginated.

        `user_id` is positional and has no default on purpose: a listing that
        forgets it would quietly return projects the caller cannot see.

        Args:
            db: Database session
            user_id: Account whose projects to return
            skip: Offset
            limit: Page size
            search: Optional name/description filter

        Returns:
            The page of owned and shared projects and the visible total.
        """
        query = db.query(Project).outerjoin(
            ProjectMember,
            ProjectMember.project_id == Project.id,
        ).filter(
            or_(Project.user_id == user_id, ProjectMember.user_id == user_id)
        ).distinct()
        
        # Apply search filter if provided
        if search:
            query = query.filter(
                Project.name.contains(search) | 
                Project.description.contains(search)
            )
        
        # Get total count
        total = query.count()
        
        # Get paginated results
        projects = query.order_by(Project.created_at.desc(), Project.id)\
            .offset(skip)\
            .limit(limit)\
            .all()
        
        # Add counts for each project
        for project in projects:
            project.document_count = ProjectService.project_document_query(
                db, project.id
            ).count()
            conversations = db.query(func.count(Conversation.id)).filter(
                Conversation.project_id == project.id,
            )
            conversations = conversations.filter(
                or_(Conversation.user_id == user_id, Conversation.user_id.is_(None))
                if project.user_id == user_id
                else Conversation.user_id == user_id
            )
            project.conversation_count = conversations.scalar() or 0
        
        return projects, total

    @staticmethod
    def get_project_members(db: Session, project: Project) -> list[dict]:
        """Return the owner and stored members with their effective roles.

        Args:
            db: Database session.
            project: Project whose member list is requested.

        Returns:
            Owner first, followed by members ordered by username.
        """
        result = []
        owner = db.query(User).filter(User.id == project.user_id).first()
        if owner is not None:
            result.append({
                "user_id": owner.id,
                "username": owner.username,
                "email": owner.email,
                "role": "owner",
                "created_at": project.created_at,
            })

        members = db.query(ProjectMember, User).join(
            User, User.id == ProjectMember.user_id
        ).filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id != project.user_id,
        ).order_by(User.username).all()
        result.extend({
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "role": membership.role,
            "created_at": membership.created_at,
        } for membership, user in members)
        return result

    @staticmethod
    def add_project_member(
        db: Session,
        project: Project,
        username: Optional[str],
        email: Optional[str],
        role: str,
    ) -> dict:
        """Add one existing account to a project.

        Args:
            db: Database session.
            project: Project, already checked for owner access.
            username: Exact username, or None when adding by email.
            email: Exact email, or None when adding by username.
            role: Requested viewer or editor role.

        Returns:
            The stored member response fields.

        Raises:
            LookupError: If the account does not exist.
            ValueError: If the owner is targeted or membership already exists.
        """
        account = db.query(User).filter(
            User.username == username if username is not None else User.email == email
        ).first()
        if account is None:
            raise LookupError("User not found")
        if account.id == project.user_id:
            raise ValueError("Project owner is already a member")
        if db.query(ProjectMember).filter_by(
            project_id=project.id,
            user_id=account.id,
        ).first() is not None:
            raise ValueError("User is already a member")

        membership = ProjectMember(
            project_id=project.id,
            user_id=account.id,
            role=role,
        )
        db.add(membership)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValueError("User is already a member")
        db.refresh(membership)
        return {
            "user_id": account.id,
            "username": account.username,
            "email": account.email,
            "role": membership.role,
            "created_at": membership.created_at,
        }

    @staticmethod
    def update_project_member(
        db: Session,
        project_id: str,
        user_id: str,
        role: str,
    ) -> Optional[dict]:
        """Change one stored membership's role.

        Args:
            db: Database session.
            project_id: Project containing the membership.
            user_id: Member account id.
            role: New viewer or editor role.

        Returns:
            Updated member response fields, or None when no membership exists.
        """
        membership = db.query(ProjectMember).filter_by(
            project_id=project_id,
            user_id=user_id,
        ).first()
        if membership is None:
            return None
        membership.role = role
        db.commit()
        db.refresh(membership)
        account = db.query(User).filter(User.id == user_id).first()
        return {
            "user_id": account.id,
            "username": account.username,
            "email": account.email,
            "role": membership.role,
            "created_at": membership.created_at,
        }

    @staticmethod
    def remove_project_member(db: Session, project_id: str, user_id: str) -> bool:
        """Remove a stored membership from a project.

        Args:
            db: Database session.
            project_id: Project containing the membership.
            user_id: Member account id.

        Returns:
            Whether a membership row was removed.
        """
        membership = db.query(ProjectMember).filter_by(
            project_id=project_id,
            user_id=user_id,
        ).first()
        if membership is None:
            return False
        db.delete(membership)
        db.commit()
        return True
    
    @staticmethod
    def update_project(
        db: Session, 
        project_id: str, 
        project_update: ProjectUpdate
    ) -> Optional[Project]:
        """Update a project."""
        project = db.query(Project).filter(Project.id == project_id).first()
        
        if not project:
            return None
        
        # Update fields if provided
        if project_update.name is not None and project_update.name != project.name:
            project.name = project_update.name
            project.auto_title = False
        if project_update.description is not None:
            project.description = project_update.description
        if project_update.meta_json is not None:
            project.meta_json = project_update.meta_json
        if "cover_emoji" in project_update.model_fields_set:
            project.cover_emoji = project_update.cover_emoji
        if "cover_color" in project_update.model_fields_set:
            project.cover_color = project_update.cover_color
        
        db.commit()
        db.refresh(project)
        
        logger.info("Project updated", project_id=project_id)
        return project
    
    @staticmethod
    def get_chat_settings(project: Project) -> ChatSettings:
        """Read a project's chat settings.

        Args:
            project: The project row.

        Returns:
            Its settings, with "default" for any never set.
        """
        return ChatSettings(
            role=project.chat_role or "default",
            instructions=project.chat_instructions or "",
            answer_length=project.answer_length or "default",
        )

    @staticmethod
    def update_chat_settings(
        db: Session, project: Project, chat_settings: ChatSettings
    ) -> ChatSettings:
        """Replace a project's chat settings.

        Args:
            db: Database session
            project: The project row, already checked for ownership
            chat_settings: The new settings

        Returns:
            The settings as stored.
        """
        project.chat_role = chat_settings.role
        project.chat_instructions = chat_settings.instructions
        project.answer_length = chat_settings.answer_length
        db.commit()
        db.refresh(project)

        logger.info("Project chat settings updated", project_id=project.id)
        return ProjectService.get_chat_settings(project)

    @staticmethod
    def delete_project(db: Session, project_id: str) -> bool:
        """Delete a project."""
        project = db.query(Project).filter(Project.id == project_id).first()
        
        if not project:
            return False
        
        audio_paths = [
            overview.file_path
            for overview in db.query(AudioOverview).filter(
                AudioOverview.project_id == project_id,
            ).all()
        ]
        db.delete(project)
        db.commit()

        # Generated files live outside SQLite, so the row cascade cannot remove them.
        from app.services.audio_overview import remove_audio_file

        for audio_path in audio_paths:
            remove_audio_file(audio_path)
        
        logger.info("Project deleted", project_id=project_id)
        return True
    
    @staticmethod
    def get_project_documents(
        db: Session, 
        project_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[Document]:
        """Get documents for a project."""
        documents = ProjectService.project_document_query(db, project_id)\
            .order_by(Document.created_at.desc())\
            .offset(skip)\
            .limit(limit)\
            .all()
        
        # Add chunk counts
        for doc in documents:
            doc.chunk_count = len(doc.chunks) if doc.chunks else 0
        
        return documents
    
    @staticmethod
    def add_document_to_project(
        db: Session,
        project_id: str,
        document_id: str
    ) -> bool:
        """Add a document to a project."""
        # Check if project and document exist
        project = db.query(Project).filter(Project.id == project_id).first()
        document = db.query(Document).filter(Document.id == document_id).first()
        
        if not project or not document:
            return False
        
        # Check if already linked
        existing = db.query(ProjectDocument).filter(
            ProjectDocument.project_id == project_id,
            ProjectDocument.document_id == document_id
        ).first()
        
        if existing:
            return True  # Already linked
        
        # Create link
        link = ProjectDocument(
            project_id=project_id,
            document_id=document_id
        )
        db.add(link)
        db.commit()
        
        logger.info("Document added to project", 
                   project_id=project_id, 
                   document_id=document_id)
        return True
    
    @staticmethod
    def remove_document_from_project(
        db: Session,
        project_id: str,
        document_id: str
    ) -> bool:
        """Remove a document from a project."""
        link = db.query(ProjectDocument).filter(
            ProjectDocument.project_id == project_id,
            ProjectDocument.document_id == document_id
        ).first()
        
        if not link:
            return False
        
        db.delete(link)
        db.commit()
        
        logger.info("Document removed from project", 
                   project_id=project_id, 
                   document_id=document_id)
        return True
    
    @staticmethod
    def get_project_conversations(
        db: Session,
        project_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[Conversation]:
        """Get conversations for a project."""
        conversations = db.query(Conversation)\
            .filter(Conversation.project_id == project_id)\
            .order_by(Conversation.updated_at.desc())\
            .offset(skip)\
            .limit(limit)\
            .all()
        
        # Add message counts
        for conv in conversations:
            conv.message_count = len(conv.messages) if conv.messages else 0
        
        return conversations
