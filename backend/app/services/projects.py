"""Project CRUD service operations."""
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
import structlog

from app.db.models import Project, ProjectDocument, Document, Conversation
from app.schemas import ProjectCreate, ProjectUpdate

logger = structlog.get_logger()


class ProjectService:
    """Service for project operations."""
    
    @staticmethod
    def create_project(db: Session, project_data: ProjectCreate) -> Project:
        """Create a new project."""
        project_id = str(uuid.uuid4())
        
        project = Project(
            id=project_id,
            name=project_data.name,
            description=project_data.description,
            meta_json=project_data.meta_json or {}
        )
        
        db.add(project)
        db.commit()
        db.refresh(project)
        
        logger.info("Project created", project_id=project_id, name=project_data.name)
        return project
    
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
        skip: int = 0, 
        limit: int = 100,
        search: Optional[str] = None
    ) -> tuple[List[Project], int]:
        """Get list of projects with pagination."""
        query = db.query(Project)
        
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
        if project_update.name is not None:
            project.name = project_update.name
        if project_update.description is not None:
            project.description = project_update.description
        if project_update.meta_json is not None:
            project.meta_json = project_update.meta_json
        
        db.commit()
        db.refresh(project)
        
        logger.info("Project updated", project_id=project_id)
        return project
    
    @staticmethod
    def delete_project(db: Session, project_id: str) -> bool:
        """Delete a project."""
        project = db.query(Project).filter(Project.id == project_id).first()
        
        if not project:
            return False
        
        # Cascade delete will handle related records
        db.delete(project)
        db.commit()
        
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
