"""Pydantic schemas for API models."""
from datetime import datetime
from typing import Annotated, Optional, List, Dict, Any
from pydantic import AfterValidator, BaseModel, Field

from app.utils.time import as_utc

# Every datetime this API emits has to carry a UTC designator: a designator-less
# value such as "2026-08-13T09:00:00" is read as *local* time by ECMAScript, so a
# browser in UTC+8 renders a record created seconds ago as hours old and files it
# under the wrong date-group header.
#
# Stored datetimes already arrive labelled, via app.db.types.UTCDateTime. This
# alias closes the boundary for anything else a route might hand a response
# model, labelling a naive value as the UTC it is meant to be rather than letting
# it serialise bare.
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]


# Authentication schemas
# email-validator is not installed, so the address is checked with a pattern
# rather than pydantic's EmailStr.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserRegister(BaseModel):
    """Schema for registering an account."""
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., max_length=255, pattern=EMAIL_PATTERN)
    # bcrypt reads at most 72 bytes, so longer passwords are refused here
    # rather than being silently truncated.
    password: str = Field(..., min_length=8, max_length=72)


class UserResponse(BaseModel):
    """Schema for account response. Never carries password material."""
    id: str
    username: str
    email: str
    created_at: UtcDatetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Schema for a successful sign-in."""
    access_token: str
    token_type: str = "bearer"


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
    created_at: UtcDatetime
    updated_at: UtcDatetime
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
    created_at: UtcDatetime
    updated_at: UtcDatetime
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
    created_at: UtcDatetime
    updated_at: UtcDatetime
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
    created_at: UtcDatetime
    
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
    timestamp: UtcDatetime
    version: str
    environment: str
    database: str
    system: Dict[str, Any]
    config: Dict[str, Any]


class ReadyResponse(BaseModel):
    """Schema for readiness check response."""
    ready: bool
    reason: Optional[str] = None


# Mind map schemas
class MindMapNode(BaseModel):
    """One node of a project's mind map.

    The same shape at every level — project, document, topic — so the browser can
    draw the tree with one recursive renderer instead of three.
    """
    id: str
    label: str
    kind: str = Field(..., pattern="^(project|document|topic)$")
    # Source type for a document node; nothing for the others so far.
    detail: Optional[str] = None
    # Set on a document node and on its topics, so selecting a topic can open
    # the source it came from.
    document_id: Optional[str] = None
    children: List["MindMapNode"] = []


class MindMapResponse(BaseModel):
    """Schema for a generated mind map."""

    # `model_used` collides with pydantic's reserved `model_` prefix, and the
    # pinned pydantic 2.5.0 warns about every such field at import time. The name
    # is kept because a query answer already reports `model_used` and the browser
    # reads that key; the guard is waived rather than the field renamed.
    model_config = {"protected_namespaces": ()}

    project_id: str
    project_name: str
    generated_at: UtcDatetime
    # Which model named the topics, or "fallback" when the document structure
    # did. Mirrors `model_used` on a query answer: the caller has to be able to
    # tell a generated map from an extracted one.
    model_used: str
    node_count: int
    root: MindMapNode
