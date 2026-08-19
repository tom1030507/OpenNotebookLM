"""Query and RAG router."""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
import structlog
import uuid

from app.config import get_settings
from app.db.database import get_db
from app.services.rag import RAGService
from app.services.projects import ProjectService
from app.db.models import Conversation, User
from app.schemas import ConversationResponse
from app.routers.auth import get_current_user
from app.routers.ownership import (
    owned_document_ids,
    require_conversation,
    require_project,
)

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()

# Initialize services
rag_service = RAGService()


class QueryRequest(BaseModel):
    """Query request model."""
    query: str
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    # RETRIEVAL_TOP_K was advertised in the README and .env.example while nothing
    # read it; this is where it now takes effect.
    top_k: int = Field(default_factory=lambda: get_settings().retrieval_top_k, ge=1, le=50)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=8192)
    include_sources: bool = True


class QueryResponse(BaseModel):
    """Query response model."""
    answer: str
    sources: List[dict]
    chunks_used: int
    model_used: Optional[str]
    usage: dict
    conversation_id: Optional[str] = None


class ConversationCreateRequest(BaseModel):
    """Request model for creating an empty conversation."""

    title: Optional[str] = None


class ConversationUpdateRequest(BaseModel):
    """Request model for renaming a conversation."""

    title: str = Field(..., min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, title: str) -> str:
        """Normalize the title before enforcing the non-empty contract."""
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Title must not be blank")
        return normalized_title


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Process a RAG query.
    
    This endpoint:
    1. Retrieves relevant document chunks
    2. Uses them as context for the LLM
    3. Returns an answer with source citations
    """
    try:
        # Retrieval is confined to the caller's own documents, always, and
        # independently of the project scope below. Without this a question with
        # no project selected searched every chunk in the database.
        allowed_document_ids = owned_document_ids(db, current_user)

        # Validate project if specified
        if request.project_id:
            require_project(db, request.project_id, current_user)
        
        # Handle conversation
        conversation_id = request.conversation_id
        if request.conversation_id:
            conversation = require_conversation(db, request.conversation_id, current_user)

            if (
                request.project_id
                and conversation.project_id != request.project_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Conversation does not belong to the selected project",
                )
            
            # Use conversation's project if not specified
            if not request.project_id and conversation.project_id:
                request.project_id = conversation.project_id
                
            # Process query with conversation context
            result = rag_service.query_with_conversation(
                db=db,
                query=request.query,
                conversation_id=conversation_id,
                project_id=request.project_id,
                top_k=request.top_k,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                include_sources=request.include_sources,
                allowed_document_ids=allowed_document_ids
            )
        else:
            # Create new conversation if project is specified
            if request.project_id:
                conversation = Conversation(
                    id=str(uuid.uuid4()),
                    project_id=request.project_id,
                    title=request.query[:100]  # Use first 100 chars as title
                )
                db.add(conversation)
                db.commit()
                conversation_id = conversation.id
                
                # Process query with new conversation
                result = rag_service.query_with_conversation(
                    db=db,
                    query=request.query,
                    conversation_id=conversation_id,
                    project_id=request.project_id,
                    top_k=request.top_k,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    include_sources=request.include_sources,
                    allowed_document_ids=allowed_document_ids
                )
            else:
                # One-off query without conversation
                result = rag_service.query(
                    db=db,
                    query=request.query,
                    project_id=request.project_id,
                    top_k=request.top_k,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    include_sources=request.include_sources,
                    allowed_document_ids=allowed_document_ids
                )
        
        return QueryResponse(
            answer=result["answer"],
            sources=result.get("sources", []),
            chunks_used=result["chunks_used"],
            model_used=result["model_used"],
            usage=result.get("usage", {}),
            conversation_id=conversation_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ConversationResponse,
)
async def create_conversation(
    project_id: str,
    request: ConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an empty conversation in one of the caller's projects."""
    require_project(db, project_id, current_user)

    conversation = Conversation(
        id=str(uuid.uuid4()),
        project_id=project_id,
        title=request.title,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return ConversationResponse(
        id=conversation.id,
        project_id=conversation.project_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=0,
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get one of the caller's conversations, with its messages."""
    conversation = require_conversation(db, conversation_id, current_user)
    
    # Get messages
    messages = []
    for msg in conversation.messages:
        messages.append({
            "id": msg.id,
            "role": msg.role,
            "text": msg.text,
            "created_at": msg.created_at,
            "citations": msg.citations_json
        })
    
    return {
        "id": conversation.id,
        "project_id": conversation.project_id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": messages
    }


@router.put(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename one of the caller's conversations."""
    conversation = require_conversation(db, conversation_id, current_user)

    conversation.title = request.title
    db.commit()
    db.refresh(conversation)

    return ConversationResponse(
        id=conversation.id,
        project_id=conversation.project_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(conversation.messages),
    )


@router.get(
    "/projects/{project_id}/conversations",
    response_model=list[ConversationResponse],
)
async def list_project_conversations(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List the conversations in one of the caller's projects."""
    require_project(db, project_id, current_user)
    
    conversations = db.query(Conversation).filter(
        Conversation.project_id == project_id
    ).order_by(Conversation.updated_at.desc()).all()
    
    return [
        {
            "id": conv.id,
            "project_id": conv.project_id,
            "title": conv.title,
            "message_count": len(conv.messages),
            "created_at": conv.created_at,
            "updated_at": conv.updated_at
        }
        for conv in conversations
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete one of the caller's conversations."""
    conversation = require_conversation(db, conversation_id, current_user)
    
    db.delete(conversation)
    db.commit()
    
    return {"status": "success", "message": "Conversation deleted"}
