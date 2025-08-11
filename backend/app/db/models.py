"""Database models."""
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, 
    ForeignKey, JSON, Float, Boolean, LargeBinary, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Project(Base):
    """Project model."""
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    meta_json = Column(JSON, default={})
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    documents = relationship("ProjectDocument", back_populates="project", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="project", cascade="all, delete-orphan")


class Document(Base):
    """Document model."""
    __tablename__ = "documents"
    
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # pdf, url, youtube
    source_url = Column(Text)
    content = Column(Text)  # Full content for reference
    meta_json = Column(JSON, default={})
    status = Column(String, default="queued")  # queued, processing, ready, error
    error_message = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    projects = relationship("ProjectDocument", back_populates="document", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_documents_status", "status"),
        Index("idx_documents_source_type", "source_type"),
    )


class ProjectDocument(Base):
    """Many-to-many relationship between projects and documents."""
    __tablename__ = "project_documents"
    
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime, default=func.now())
    
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
    created_at = Column(DateTime, default=func.now())
    
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
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    chunk = relationship("Chunk", back_populates="embedding")
    
    __table_args__ = (
        Index("idx_embeddings_chunk_id", "chunk_id"),
    )


class Conversation(Base):
    """Conversation model."""
    __tablename__ = "conversations"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    title = Column(String)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
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
    created_at = Column(DateTime, default=func.now())
    
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
    created_at = Column(DateTime, default=func.now())
    
    __table_args__ = (
        Index("idx_citations_message_id", "message_id"),
        Index("idx_citations_document_id", "document_id"),
        Index("idx_citations_chunk_id", "chunk_id"),
    )
