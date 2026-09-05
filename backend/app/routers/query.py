"""Query and RAG router.

Every route here is a plain `def`. Answering a question embeds it, searches, and
then blocks on the LLM for as long as the model takes; the container runs a
single uvicorn worker, so on the event loop one question stalls every other
request for that whole time — `/healthz` included, which the compose healthcheck
gives ten seconds. FastAPI runs a sync handler in its threadpool, which is where
blocking work belongs, and it is what the ingest path already does with its own
heavy work.

The conversation routes below are cheap by comparison, but they await nothing
either and are sync for the same reason, so that a route added here does not have
to relitigate the question. Anything that does start awaiting has to become
`async def` again — a sync handler that blocks the thread it was given is fine,
an async one that blocks the loop is not.
"""
from functools import lru_cache
from typing import Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
import structlog
import uuid

from app.config import Settings, get_settings
from app.db.database import get_db
from app.services.projects import ProjectService
from app.db.models import Conversation, User
from app.schemas import ConversationResponse
from app.routers.auth import get_current_user
from app.routers.ownership import (
    owned_document_ids,
    require_conversation,
    require_project,
)
from app.routers.rate_limit import (
    acquire_account_lease,
    enforce_account_rate_limit,
    get_concurrency_limiter,
    get_rate_limiter,
)
from app.services.rate_limit import (
    ConcurrencyLimiter,
    SlidingWindowRateLimiter,
    UnlimitedConcurrencyLease,
)

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()

@lru_cache
def get_rag_service() -> Any:
    """Return the process-wide RAG service on first use.

    Args:
        None.

    Returns:
        The production RAG service.
    """
    from app.services.rag import RAGService

    return RAGService()


class QueryRequest(BaseModel):
    """Query request model."""
    query: str
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    # RETRIEVAL_TOP_K was advertised in the README and .env.example while nothing
    # read it; this is where it now takes effect.
    top_k: int = Field(default_factory=lambda: get_settings().retrieval_top_k, ge=1, le=50)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8192, ge=1, le=8192)
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
def query(
    request: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    rag_service: Any = Depends(get_rag_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    settings: Settings = Depends(get_settings),
):
    """Process a rate- and concurrency-bounded RAG query.

    Args:
        request: Query and optional project/conversation scope.
        db: Database session.
        current_user: Authenticated caller.
        request_limiter: Per-account sliding-window limiter.
        concurrency_limiter: Per-account active-operation limiter.
        settings: Current application abuse-control settings.

    Returns:
        Answer, source, model, usage, and conversation metadata.
    """
    try:
        # Retrieval is confined to the caller's own documents, always, and
        # independently of the project scope below. Without this a question with
        # no project selected searched every chunk in the database.
        allowed_document_ids = owned_document_ids(db, current_user)

        # Validate project if specified
        if request.project_id:
            require_project(db, request.project_id, current_user)
        
        # Resolve every ownership-bearing id before abuse controls. Otherwise a
        # depleted limiter would turn another account's normally indistinguishable
        # 404 into a 429 and reveal that the probed id follows a different path.
        conversation_id = request.conversation_id
        conversation = None
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

        lease = UnlimitedConcurrencyLease()
        if settings.rate_limit_enabled:
            enforce_account_rate_limit(
                request_limiter,
                "query",
                current_user.id,
                limit=30,
                window_seconds=60,
            )
            lease = acquire_account_lease(
                concurrency_limiter,
                "query",
                current_user.id,
            )
        try:
            if conversation is not None:
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
                        title=request.query[:100]
                    )
                    db.add(conversation)
                    db.commit()
                    conversation_id = conversation.id

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
        finally:
            lease.release()
        
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
def create_conversation(
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
def get_conversation(
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
def update_conversation(
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
def list_project_conversations(
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
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete one of the caller's conversations."""
    conversation = require_conversation(db, conversation_id, current_user)
    
    db.delete(conversation)
    db.commit()
    
    return {"status": "success", "message": "Conversation deleted"}
