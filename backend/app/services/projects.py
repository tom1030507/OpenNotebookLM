"""Project CRUD service operations."""
import copy
import uuid
from typing import Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
import structlog

from app.db.models import (
    AudioOverview,
    Conversation,
    Document,
    Message,
    Note,
    Project,
    ProjectDocument,
    ProjectMember,
    ProjectSourceGroup,
    UserProjectTag,
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
        """Return linked sources authorized by the owner or a project member.

        Args:
            db: Database session.
            project_id: Optional project whose linked sources are being read.

        Returns:
            A query of linked documents the project may still read.
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
            Project.deleted_at.is_(None),
            Document.deleted_at.is_(None),
            or_(
                Document.user_id == Project.user_id,
                ProjectMember.user_id.isnot(None),
                ProjectDocument.shared_by_user_id == Document.user_id,
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
    def _remap_document_ids(value: Any, document_ids: dict[str, str]) -> Any:
        """Copy JSON data while changing references to sources in a project.

        Args:
            value: JSON value to copy.
            document_ids: Source document ids and their destination ids.

        Returns:
            Copied JSON data with document references updated.
        """
        if isinstance(value, list):
            return [ProjectService._remap_document_ids(item, document_ids) for item in value]
        if isinstance(value, dict):
            return {
                key: document_ids.get(item, item)
                if key in ("document_id", "doc_id", "source_document_id")
                and isinstance(item, str)
                else ProjectService._remap_document_ids(item, document_ids)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _note_payload_for_project(
        payload: Any,
        project_id: str,
        project_name: str,
        document_ids: Optional[dict[str, str]] = None,
    ) -> Any:
        """Copy a Studio payload while keeping its project reference current.

        Args:
            payload: Note payload to copy.
            project_id: Destination project id.
            project_name: Destination project name.
            document_ids: Optional source-to-target document id mapping.

        Returns:
            The copied payload with project metadata updated when present.
        """
        payload = ProjectService._remap_document_ids(payload, document_ids or {})
        if isinstance(payload, dict) and "project_id" in payload:
            payload["project_id"] = project_id
            if "project_name" in payload:
                payload["project_name"] = project_name
        return payload

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
                Document.deleted_at.is_(None),
            )
            .all()
        )
        notes = db.query(Note).filter(
            Note.project_id == project.id,
            Note.deleted_at.is_(None),
        ).all()
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
            output_language=project.output_language or "auto",
            chat_model=project.chat_model,
            cover_emoji=ProjectService.default_cover_emoji(duplicate_id),
        )
        links = [
            ProjectDocument(
                project_id=duplicate_id,
                document_id=row.document_id,
                shared_by_user_id=user_id,
            )
            for row in documents
        ]
        copied_notes = []
        for note in notes:
            copied_notes.append(Note(
                id=str(uuid.uuid4()),
                project_id=duplicate_id,
                title=note.title,
                content=note.content,
                origin=note.origin,
                source_message_id=note.source_message_id,
                studio_kind=note.studio_kind,
                payload_json=ProjectService._note_payload_for_project(
                    note.payload_json,
                    duplicate_id,
                    duplicate.name,
                ),
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
    def merge_project(
        db: Session,
        source: Project,
        target: Project,
        user_id: str,
        mode: str,
    ) -> dict:
        """Move or copy one authorized project's content into another.

        Args:
            db: Database session.
            source: Source project, already checked for ownership.
            target: Destination project, already checked for ownership.
            user_id: Owner of both projects.
            mode: Whether to move or copy the content.

        Returns:
            Counts of moved content and sources skipped as duplicates.

        Raises:
            ValueError: If the source and target are the same or their watched
                folders cannot be combined.
        """
        if source.id == target.id:
            raise ValueError("A project cannot be merged into itself")
        if mode == "move" and source.watched_folder and target.watched_folder not in (
            None, source.watched_folder
        ):
            raise ValueError("Projects use different watched folders")

        visible_source_document_ids = ProjectService.project_document_query(
            db, source.id
        ).with_entities(Document.id)
        source_links = db.query(ProjectDocument, Document).join(
            Document,
            Document.id == ProjectDocument.document_id,
        ).filter(
            ProjectDocument.project_id == source.id,
            Document.id.in_(visible_source_document_ids),
        ).order_by(func.lower(Document.title), Document.title, Document.id).all()
        target_documents = ProjectService.project_document_query(db, target.id).order_by(
            func.lower(Document.title), Document.title, Document.id
        ).all()
        target_documents_by_id = {document.id: document for document in target_documents}
        target_documents_by_hash = {
            document.content_hash: document
            for document in target_documents
            if document.content_hash
        }
        target_documents_by_url = {
            document.source_url: document
            for document in target_documents
            if document.source_url
        }

        target_groups = {
            group.name: group
            for group in db.query(ProjectSourceGroup).filter(
                ProjectSourceGroup.project_id == target.id
            ).all()
        }
        source_group_names = {
            group.id: group.name
            for group in db.query(ProjectSourceGroup).filter(
                ProjectSourceGroup.project_id == source.id
            ).all()
        }
        skipped_sources = []
        sources_merged = 0

        conversations = db.query(Conversation).filter(
            Conversation.project_id == source.id,
        ).order_by(Conversation.created_at, Conversation.id).all()
        notes = db.query(Note).filter(
            Note.project_id == source.id,
            Note.deleted_at.is_(None),
        ).all()
        document_ids = {}

        try:
            for link, document in source_links:
                duplicate_target = target_documents_by_id.get(document.id)
                if duplicate_target is None and document.content_hash:
                    duplicate_target = target_documents_by_hash.get(document.content_hash)
                if duplicate_target is None and document.source_url:
                    duplicate_target = target_documents_by_url.get(document.source_url)
                if duplicate_target is not None:
                    skipped_sources.append({"id": document.id, "title": document.title})
                    document_ids[document.id] = duplicate_target.id
                    continue
                document_ids[document.id] = document.id

                group_id = None
                group_name = source_group_names.get(link.source_group_id)
                if group_name:
                    group = target_groups.get(group_name)
                    if group is None:
                        group = ProjectSourceGroup(
                            id=str(uuid.uuid4()),
                            project_id=target.id,
                            name=group_name,
                        )
                        db.add(group)
                        target_groups[group_name] = group
                    group_id = group.id

                if mode == "move":
                    db.delete(link)
                db.add(ProjectDocument(
                    project_id=target.id,
                    document_id=document.id,
                    shared_by_user_id=document.user_id,
                    source_group_id=group_id,
                    added_at=link.added_at,
                ))
                target_documents_by_id[document.id] = document
                if document.content_hash:
                    target_documents_by_hash.setdefault(document.content_hash, document)
                if document.source_url:
                    target_documents_by_url.setdefault(document.source_url, document)
                sources_merged += 1

            if mode == "copy" or any(
                source_id != target_id for source_id, target_id in document_ids.items()
            ):
                messages = db.query(Message).join(
                    Conversation,
                    Conversation.id == Message.conversation_id,
                ).filter(
                    Conversation.project_id == source.id,
                ).order_by(Message.created_at, Message.id).all()
            else:
                messages = []

            if mode == "move":
                for conversation in conversations:
                    conversation.project_id = target.id
                    if conversation.user_id is None:
                        conversation.user_id = user_id
                for message in messages:
                    message.citations_json = ProjectService._remap_document_ids(
                        message.citations_json,
                        document_ids,
                    )
                    message.citation_checks_json = ProjectService._remap_document_ids(
                        message.citation_checks_json,
                        document_ids,
                    )
                for note in notes:
                    note.project_id = target.id
                    note.payload_json = ProjectService._note_payload_for_project(
                        note.payload_json,
                        target.id,
                        target.name,
                        document_ids,
                    )
            else:
                conversation_ids = {
                    conversation.id: str(uuid.uuid4())
                    for conversation in conversations
                }
                db.add_all([
                    Conversation(
                        id=conversation_ids[conversation.id],
                        project_id=target.id,
                        user_id=conversation.user_id or user_id,
                        title=conversation.title,
                        created_at=conversation.created_at,
                        updated_at=conversation.updated_at,
                    )
                    for conversation in conversations
                ])
                message_ids = {message.id: str(uuid.uuid4()) for message in messages}
                db.add_all([
                    Message(
                        id=message_ids[message.id],
                        conversation_id=conversation_ids[message.conversation_id],
                        role=message.role,
                        text=message.text,
                        citations_json=ProjectService._remap_document_ids(
                            message.citations_json,
                            document_ids,
                        ),
                        citation_checks_json=ProjectService._remap_document_ids(
                            message.citation_checks_json,
                            document_ids,
                        ),
                        used_mode=message.used_mode,
                        token_count=message.token_count,
                        cost=message.cost,
                        processing_time=message.processing_time,
                        is_bookmarked=message.is_bookmarked,
                        tags=copy.deepcopy(message.tags),
                        rating=message.rating,
                        created_at=message.created_at,
                    )
                    for message in messages
                ])
                db.add_all([
                    Note(
                        id=str(uuid.uuid4()),
                        project_id=target.id,
                        title=note.title,
                        content=note.content,
                        origin=note.origin,
                        source_message_id=message_ids.get(
                            note.source_message_id, note.source_message_id
                        ),
                        studio_kind=note.studio_kind,
                        payload_json=ProjectService._note_payload_for_project(
                            note.payload_json,
                            target.id,
                            target.name,
                            document_ids,
                        ),
                        created_at=note.created_at,
                        updated_at=note.updated_at,
                    )
                    for note in notes
                ])

            if mode == "move" and source.watched_folder:
                target.watched_folder = source.watched_folder
                source.watched_folder = None
            db.commit()
        except Exception:
            db.rollback()
            raise

        return {
            "target_project_id": target.id,
            "mode": mode,
            "sources_merged": sources_merged,
            "notes_merged": len(notes),
            "conversations_merged": len(conversations),
            "skipped_sources": skipped_sources,
        }
    
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
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        ).first()
        
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
    def get_project_tags(db: Session, user_id: str, project_id: str) -> list[str]:
        """Return one user's tags for a visible project.

        Args:
            db: Database session.
            user_id: Account whose tags are requested.
            project_id: Project id.

        Returns:
            The account's tags in stable case-insensitive order.
        """
        return [tag for (tag,) in db.query(UserProjectTag.tag).filter(
            UserProjectTag.user_id == user_id,
            UserProjectTag.project_id == project_id,
        ).order_by(func.lower(UserProjectTag.tag), UserProjectTag.tag).all()]

    @staticmethod
    def replace_project_tags(
        db: Session,
        project_id: str,
        user_id: str,
        tags: list[str],
    ) -> list[str]:
        """Replace one account's personal tags for a project.

        Args:
            db: Database session.
            project_id: Project whose tags are being replaced.
            user_id: Account that owns these tags.
            tags: Validated, normalized replacement tags.

        Returns:
            The account's saved tags.
        """
        db.query(UserProjectTag).filter(
            UserProjectTag.project_id == project_id,
            UserProjectTag.user_id == user_id,
        ).delete(synchronize_session=False)
        db.add_all(
            UserProjectTag(user_id=user_id, project_id=project_id, tag=tag)
            for tag in tags
        )
        db.commit()
        return tags

    @staticmethod
    def get_source_groups(db: Session, project_id: str) -> list[dict]:
        """Return a project's source groups with their linked document ids.

        Args:
            db: Database session.
            project_id: Project whose groups are requested.

        Returns:
            Groups ordered by name, each with document ids linked to it.
        """
        groups = db.query(ProjectSourceGroup).filter(
            ProjectSourceGroup.project_id == project_id,
        ).order_by(
            func.lower(ProjectSourceGroup.name),
            ProjectSourceGroup.id,
        ).all()
        document_ids = {group.id: [] for group in groups}
        if document_ids:
            for group_id, document_id in db.query(
                ProjectDocument.source_group_id,
                ProjectDocument.document_id,
            ).filter(
                ProjectDocument.project_id == project_id,
                ProjectDocument.source_group_id.in_(document_ids),
            ).all():
                document_ids[group_id].append(document_id)
        return [
            {
                "id": group.id,
                "name": group.name,
                "document_ids": document_ids[group.id],
            }
            for group in groups
        ]

    @staticmethod
    def create_source_group(
        db: Session,
        project_id: str,
        name: str,
    ) -> ProjectSourceGroup:
        """Create a named group shared by the project's members.

        Args:
            db: Database session.
            project_id: Project that owns the group.
            name: Validated group name.

        Returns:
            The created group.

        Raises:
            ValueError: If the project already has a group with this name.
        """
        group = ProjectSourceGroup(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=name,
        )
        db.add(group)
        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise ValueError("A group with this name already exists") from error
        db.refresh(group)
        return group

    @staticmethod
    def rename_source_group(
        db: Session,
        project_id: str,
        group_id: str,
        name: str,
    ) -> Optional[ProjectSourceGroup]:
        """Rename a group without changing its source assignments.

        Args:
            db: Database session.
            project_id: Project that owns the group.
            group_id: Group being renamed.
            name: Validated replacement name.

        Returns:
            The renamed group, or None if it is outside the project.

        Raises:
            ValueError: If another group in the project already has this name.
        """
        group = db.query(ProjectSourceGroup).filter(
            ProjectSourceGroup.id == group_id,
            ProjectSourceGroup.project_id == project_id,
        ).first()
        if group is None:
            return None
        group.name = name
        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise ValueError("A group with this name already exists") from error
        db.refresh(group)
        return group

    @staticmethod
    def delete_source_group(db: Session, project_id: str, group_id: str) -> bool:
        """Delete one group and leave its sources in the project ungrouped.

        Args:
            db: Database session.
            project_id: Project that owns the group.
            group_id: Group being deleted.

        Returns:
            Whether a matching group was deleted.
        """
        group = db.query(ProjectSourceGroup).filter(
            ProjectSourceGroup.id == group_id,
            ProjectSourceGroup.project_id == project_id,
        ).first()
        if group is None:
            return False
        db.query(ProjectDocument).filter(
            ProjectDocument.project_id == project_id,
            ProjectDocument.source_group_id == group_id,
        ).update(
            {ProjectDocument.source_group_id: None},
            synchronize_session=False,
        )
        db.delete(group)
        db.commit()
        return True

    @staticmethod
    def assign_source_group(
        db: Session,
        project_id: str,
        document_id: str,
        group_id: Optional[str],
    ) -> bool:
        """Move a project-linked document to a group or ungroup it.

        Args:
            db: Database session.
            project_id: Project containing the document.
            document_id: Document being moved.
            group_id: Group in this project, or None to ungroup.

        Returns:
            Whether the source link and optional group belong to the project.
        """
        link = db.query(ProjectDocument).filter(
            ProjectDocument.project_id == project_id,
            ProjectDocument.document_id == document_id,
        ).first()
        if link is None:
            return False
        if group_id is not None and db.query(ProjectSourceGroup.id).filter(
            ProjectSourceGroup.project_id == project_id,
            ProjectSourceGroup.id == group_id,
        ).first() is None:
            return False
        link.source_group_id = group_id
        db.commit()
        return True
    
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
            Project.deleted_at.is_(None),
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

        project_ids = [project.id for project in projects]
        project_tags = {}
        if project_ids:
            for project_id, tag in db.query(
                UserProjectTag.project_id,
                UserProjectTag.tag,
            ).filter(
                UserProjectTag.user_id == user_id,
                UserProjectTag.project_id.in_(project_ids),
            ).order_by(func.lower(UserProjectTag.tag), UserProjectTag.tag).all():
                project_tags.setdefault(project_id, []).append(tag)
        
        # Add counts for each project
        for project in projects:
            project.tags = project_tags.get(project.id, [])
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
        """Update an active project.

        Args:
            db: Database session.
            project_id: Project to update.
            project_update: Fields to replace.

        Returns:
            The updated project, or None when it is missing or in trash.
        """
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        ).first()
        
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
            output_language=project.output_language or "auto",
            model=project.chat_model,
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
        if "model" in chat_settings.model_fields_set:
            project.chat_model = chat_settings.model
        output_language = (
            chat_settings.output_language
            if "output_language" in chat_settings.model_fields_set
            else project.output_language or "auto"
        )
        if (project.output_language or "auto") != output_language:
            project.overview_json = None
        project.output_language = output_language
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
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        ).first()
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.deleted_at.is_(None),
        ).first()
        
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
            document_id=document_id,
            shared_by_user_id=document.user_id,
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
