"""Pydantic schemas for API models."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# Project schemas
class ProjectBase(BaseModel):
    """Base project schema."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    meta_json: Optional[Dict[str, Any]] = {}


class ProjectCreate(ProjectBase):
    """Schema for creating a project."""
    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    meta_json: Optional[Dict[str, Any]] = None


class ProjectResponse(ProjectBase):
    """Schema for project response."""
    id: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    conversation_count: int = 0
    
    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """Schema for project list response."""
    projects: List[ProjectResponse]
    total: int
    page: int
    per_page: int


# Document schemas
class DocumentBase(BaseModel):
    """Base document schema."""
    title: str
    source_type: str  # pdf, url, youtube
    source_url: Optional[str] = None
    meta_json: Optional[Dict[str, Any]] = {}


class DocumentCreate(DocumentBase):
    """Schema for creating a document."""
    project_id: str


class DocumentResponse(DocumentBase):
    """Schema for document response."""
    id: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0
    
    class Config:
        from_attributes = True


class DocumentStatusResponse(BaseModel):
    """Schema for document status response."""
    id: str
    status: str  # queued, processing, ready, error
    meta: Optional[Dict[str, Any]] = {}
    error_message: Optional[str] = None
    progress: Optional[float] = None


# Upload schemas
class FileUploadResponse(BaseModel):
    """Schema for file upload response."""
    doc_id: str
    status: str
    message: str


class URLUploadRequest(BaseModel):
    """Schema for URL upload request."""
    url: str = Field(..., min_length=1)
    title: Optional[str] = None


class YouTubeUploadRequest(BaseModel):
    """Schema for YouTube upload request."""
    youtube_url: str = Field(..., min_length=1)
    title: Optional[str] = None


# Conversation schemas
class ConversationCreate(BaseModel):
    """Schema for creating a conversation."""
    project_id: str
    title: Optional[str] = None


class ConversationResponse(BaseModel):
    """Schema for conversation response."""
    id: str
    project_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    
    class Config:
        from_attributes = True


# Message schemas
class MessageCreate(BaseModel):
    """Schema for creating a message."""
    conversation_id: str
    text: str
    role: str = "user"


class CitationSchema(BaseModel):
    """Schema for citation."""
    doc_id: str
    chunk_id: str
    page_num: Optional[int] = None
    url: Optional[str] = None
    ts_start: Optional[float] = None
    ts_end: Optional[float] = None
    char_span: Optional[List[int]] = None
    text_snippet: Optional[str] = None


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: str
    conversation_id: str
    role: str
    text: str
    citations: List[CitationSchema] = []
    used_mode: Optional[str] = None
    token_count: Optional[int] = None
    cost: Optional[float] = None
    processing_time: Optional[float] = None
    is_bookmarked: bool = False
    tags: List[str] = []
    created_at: datetime
    
    class Config:
        from_attributes = True


# Query schemas
class QueryRequest(BaseModel):
    """Schema for query request."""
    project_id: str
    query: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    rerank: bool = True
    mode: str = Field(default="auto", pattern="^(local|cloud|auto)$")


class QueryResponse(BaseModel):
    """Schema for query response."""
    answer: str
    citations: List[CitationSchema]
    used_mode: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    timings: Dict[str, float] = {}
    token_cost: Optional[Dict[str, Any]] = None


# Export schemas
class ExportRequest(BaseModel):
    """Schema for export request."""
    format: str = Field(default="markdown", pattern="^(markdown|json|html)$")
    include_citations: bool = True
    include_metadata: bool = False


# Health schemas
class HealthResponse(BaseModel):
    """Schema for health check response."""
    ok: bool
    timestamp: datetime
    version: str
    environment: str
    database: str
    system: Dict[str, Any]
    config: Dict[str, Any]


class ReadyResponse(BaseModel):
    """Schema for readiness check response."""
    ready: bool
    reason: Optional[str] = None
