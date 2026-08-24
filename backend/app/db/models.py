"""Database models."""
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    Column, String, Integer, Text,
    ForeignKey, JSON, Float, Boolean, LargeBinary, Index, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.types import UTCDateTime
from app.utils.time import utc_now

Base = declarative_base()


class Project(Base):
    """Project model."""
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True)
    # Nullable because rows written before ownership existed have no owner to
    # name. A null owner means the API treats the row as belonging to nobody
    # rather than to everybody -- see scripts/assign_owner.py to claim them.
    # The column itself is added to older databases by
    # `db.database.ensure_added_columns`, since create_all only creates tables.
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    meta_json = Column(JSON, default={})
    created_at = Column(UTCDateTime, default=func.now())
    updated_at = Column(UTCDateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    owner = relationship("User", back_populates="projects")
    documents = relationship("ProjectDocument", back_populates="project", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_projects_user_id", "user_id"),
    )


class User(Base):
    """Account used to sign in to the workspace."""
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)  # bcrypt hash, never plain text
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(UTCDateTime, default=func.now())
    last_login_at = Column(UTCDateTime)

    # Relationships
    projects = relationship("Project", back_populates="owner")
    documents = relationship("Document", back_populates="owner")

    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
    )


class Document(Base):
    """Document model."""
    __tablename__ = "documents"
    
    id = Column(String, primary_key=True)
    # Documents carry their own owner rather than inheriting one through
    # ProjectDocument. A document does not need a project to exist -- in the
    # database this was written against, 25 of 27 documents belonged to no project
    # at all -- so deriving ownership from membership would leave those rows with
    # no answer to "whose is this?".
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    title = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # pdf, url, youtube
    source_url = Column(Text)
    content = Column(Text)  # Full content for reference
    meta_json = Column(JSON, default={})
    status = Column(String, default="queued")  # queued, processing, ready, error
    error_message = Column(Text)
    created_at = Column(UTCDateTime, default=func.now())
    updated_at = Column(UTCDateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    owner = relationship("User", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    projects = relationship("ProjectDocument", back_populates="document", cascade="all, delete-orphan")
    ingestion_jobs = relationship(
        "IngestionJob",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("idx_documents_status", "status"),
        Index("idx_documents_source_type", "source_type"),
        Index("idx_documents_user_id", "user_id"),
    )


class IngestionJob(Base):
    """Durable extraction and indexing work for one document."""
    __tablename__ = "ingestion_jobs"

    id = Column(String, primary_key=True)
    # Terminal rows are durable attempt history. The partial unique index below
    # prevents competing active attempts without discarding that history.
    document_id = Column(
        String,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_type = Column(String, nullable=False)
    payload_json = Column(JSON, default=dict, nullable=False)
    status = Column(String, default="queued", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(JSON)
    created_at = Column(UTCDateTime, default=utc_now, nullable=False)
    started_at = Column(UTCDateTime)
    completed_at = Column(UTCDateTime)

    document = relationship("Document", back_populates="ingestion_jobs")

    __table_args__ = (
        Index("idx_ingestion_jobs_status_created", "status", "created_at"),
        Index(
            "uq_ingestion_jobs_active_document",
            "document_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )


class ProjectDocument(Base):
    """Many-to-many relationship between projects and documents."""
    __tablename__ = "project_documents"
    
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(UTCDateTime, default=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="documents")
    document = relationship("Document", back_populates="projects")


class Chunk(Base):
    """Document chunk model."""
    __tablename__ = "chunks"
    
    id = Column(String, primary_key=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    text = Column(Text, nullable=False)
    start_offset = Column(Integer)
    end_offset = Column(Integer)
    page_num = Column(Integer)  # For PDFs
    heading_path = Column(Text)  # For URLs (e.g., "h1/h2/h3")
    ts_start = Column(Float)  # For YouTube (timestamp in seconds)
    ts_end = Column(Float)  # For YouTube
    meta_json = Column(JSON, default={})
    created_at = Column(UTCDateTime, default=func.now())
    
    # Relationships
    document = relationship("Document", back_populates="chunks")
    embedding = relationship("Embedding", back_populates="chunk", uselist=False, cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_chunks_document_id", "document_id"),
        Index("idx_chunks_page_num", "page_num"),
    )


class Embedding(Base):
    """Embedding model."""
    __tablename__ = "embeddings"
    
    id = Column(String, primary_key=True)
    chunk_id = Column(String, ForeignKey("chunks.id"), unique=True, nullable=False)
    vector = Column(LargeBinary)  # For SQLite storage
    vector_json = Column(JSON)  # Alternative JSON storage
    model_name = Column(String)
    created_at = Column(UTCDateTime, default=func.now())
    
    # Relationships
    chunk = relationship("Chunk", back_populates="embedding")
    
    __table_args__ = (
        Index("idx_embeddings_chunk_id", "chunk_id"),
    )


class RetrievalIndexEntry(Base):
    """Stable mapping and fallback data for persistent retrieval indexes."""
    __tablename__ = "retrieval_index_entries"

    # sqlite-vec requires an integer primary key. Keeping it in this ordinary
    # table gives a chunk a stable id across updates while the virtual-table row
    # is explicitly deleted and reinserted (vec0 does not support UPSERT).
    id = Column(Integer, primary_key=True, autoincrement=True)
    chunk_id = Column(
        String,
        ForeignKey("chunks.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    document_id = Column(String, nullable=False)
    vector = Column(LargeBinary, nullable=False)
    model_name = Column(String)
    dimension = Column(Integer, nullable=False)
    source_hash = Column(String, nullable=False)
    dense_hash = Column(String)
    lexical_hash = Column(String)
    lexical_text = Column(Text, nullable=False)
    # Canonical text can change while FTS5 is unavailable. Retaining the tokens
    # that produced the actual postings lets recovery issue the required FTS5
    # external-content delete before inserting the new representation.
    indexed_lexical_text = Column(Text)
    searchable = Column(Boolean, default=False, nullable=False)
    created_at = Column(UTCDateTime, default=utc_now, nullable=False)
    updated_at = Column(UTCDateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_retrieval_index_entries_document", "document_id"),
        Index("idx_retrieval_index_entries_source_hash", "source_hash"),
        # A vec row can temporarily outlive its mapping when the extension is
        # unavailable during deletion. SQLite otherwise reuses the deleted
        # maximum INTEGER PRIMARY KEY, which could attach that orphan vector to
        # an unrelated new chunk and bypass its document partition.
        {"sqlite_autoincrement": True},
    )


class RetrievalIndexFTSTombstone(Base):
    """Deferred FTS posting deletion recorded while FTS5 is unavailable."""
    __tablename__ = "retrieval_index_fts_tombstones"

    entry_id = Column(Integer, primary_key=True)
    document_id = Column(String, nullable=False)
    indexed_lexical_text = Column(Text, nullable=False)
    created_at = Column(UTCDateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_retrieval_fts_tombstones_document", "document_id"),
    )


class Conversation(Base):
    """Conversation model."""
    __tablename__ = "conversations"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    title = Column(String)
    created_at = Column(UTCDateTime, default=func.now())
    updated_at = Column(UTCDateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_conversations_project_id", "project_id"),
    )


class Message(Base):
    """Message model."""
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)  # user, assistant, system
    text = Column(Text, nullable=False)
    citations_json = Column(JSON, default=[])
    used_mode = Column(String)  # local, cloud
    token_count = Column(Integer)
    cost = Column(Float)
    processing_time = Column(Float)
    is_bookmarked = Column(Boolean, default=False)
    tags = Column(JSON, default=[])
    # Python-side, not func.now(): SQLite's CURRENT_TIMESTAMP has second
    # resolution, and the two messages of one turn are written in a single
    # commit. Tied timestamps make `order_by(created_at)` arbitrary, which
    # scrambles the history in the prompt and made picking the previous
    # question for a follow-up return whichever row the engine felt like.
    created_at = Column(UTCDateTime, default=utc_now)
    
    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    
    __table_args__ = (
        Index("idx_messages_conversation_id", "conversation_id"),
        Index("idx_messages_role", "role"),
        Index("idx_messages_is_bookmarked", "is_bookmarked"),
    )


class Citation(Base):
    """Citation model (optional, can also use JSON in Message)."""
    __tablename__ = "citations"
    
    id = Column(String, primary_key=True)
    message_id = Column(String, ForeignKey("messages.id"), nullable=False)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    chunk_id = Column(String, ForeignKey("chunks.id"), nullable=False)
    page_num = Column(Integer)
    url = Column(Text)
    ts_start = Column(Float)
    ts_end = Column(Float)
    char_span_start = Column(Integer)
    char_span_end = Column(Integer)
    created_at = Column(UTCDateTime, default=func.now())
    
    __table_args__ = (
        Index("idx_citations_message_id", "message_id"),
        Index("idx_citations_document_id", "document_id"),
        Index("idx_citations_chunk_id", "chunk_id"),
    )
