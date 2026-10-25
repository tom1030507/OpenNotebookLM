"""Project CRUD service operations."""
import copy
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
import structlog

from app.db.models import (
    AudioOverview,
    Conversation,
    Document,
    Note,
    Project,
    ProjectDocument,
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
    def get_project(db: Session, project_id: str) -> Optional[Project]:
        """Get a project by ID."""
        project = db.query(Project).filter(Project.id == project_id).first()
        
        if project:
            # Add counts
            project.document_count = db.query(func.count(ProjectDocument.document_id))\
                .filter(ProjectDocument.project_id == project_id).scalar() or 0
            project.conversation_count = db.query(func.count(Conversation.id))\
                .filter(Conversation.project_id == project_id).scalar() or 0
        
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
        forgets it would quietly return every account's projects, which is the
        bug this parameter exists to prevent.

        Args:
            db: Database session
            user_id: Account whose projects to return
            skip: Offset
            limit: Page size
            search: Optional name/description filter

        Returns:
            The page of projects and the total for this account
        """
        query = db.query(Project).filter(Project.user_id == user_id)
        
        # Apply search filter if provided
        if search:
            query = query.filter(
                Project.name.contains(search) | 
                Project.description.contains(search)
            )
        
        # Get total count
        total = query.count()
        
        # Get paginated results
        projects = query.order_by(Project.created_at.desc())\
            .offset(skip)\
            .limit(limit)\
            .all()
        
        # Add counts for each project
        for project in projects:
            project.document_count = db.query(func.count(ProjectDocument.document_id))\
                .filter(ProjectDocument.project_id == project.id).scalar() or 0
            project.conversation_count = db.query(func.count(Conversation.id))\
                .filter(Conversation.project_id == project.id).scalar() or 0
        
        return projects, total
    
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
        documents = db.query(Document)\
            .join(ProjectDocument)\
            .filter(ProjectDocument.project_id == project_id)\
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
