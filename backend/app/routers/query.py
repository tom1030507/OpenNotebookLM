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
from typing import Any, Literal, Optional, List
from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
import structlog
import json
import uuid

from app.config import Settings, get_settings
from app.db.database import get_db
from app.services.projects import ProjectService
from app.db.models import Conversation, Message, User
from app.schemas import (
    ConversationResponse,
    MAX_DOCUMENT_SELECTION,
    ProjectSearchRequest,
    ProjectSearchResponse,
)
from app.routers.auth import get_current_user
from app.routers.ownership import (
    owned_document_ids,
    require_conversation,
    require_documents,
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
from app.services.global_search import search_visible_projects

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()


class ClosingStreamingResponse(StreamingResponse):
    """Close the sync event iterator and release its operation lease on exit."""

    def __init__(self, content, lease, **kwargs):
        self._content = content
        self._lease = lease
        super().__init__(content, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await run_in_threadpool(self._content.close)
            finally:
                self._lease.release()


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
    # Omitted means every owned source. An empty list is refused rather than
    # read as "no restriction", which would quietly search everything.
    document_ids: Optional[List[str]] = Field(
        default=None,
        min_length=1,
        max_length=MAX_DOCUMENT_SELECTION,
    )

    @field_validator("document_ids", mode="before")
    @classmethod
    def deduplicate_document_ids(
        cls,
        document_ids: Any,
    ) -> Any:
        """Keep the first occurrence of each source before ownership lookup.

        Args:
            document_ids: Validated source ids, or None when no selection was
                supplied.

        Returns:
            The selection in request order with duplicates removed.
        """
        if not isinstance(document_ids, (list, tuple)):
            return document_ids
        unique_ids = []
        seen_ids = set()
        for document_id in document_ids:
            if not isinstance(document_id, str):
                unique_ids.append(document_id)
            elif document_id not in seen_ids:
                seen_ids.add(document_id)
                unique_ids.append(document_id)
        return unique_ids


class CitationCheckResponse(BaseModel):
    sentence_index: int
    cited_labels: List[int]
    score: float
    supported: bool


class QueryResponse(BaseModel):
    """Query response model."""
    answer: str
    sources: List[dict]
    chunks_used: int
    model_used: Optional[str]
    usage: dict
    conversation_id: Optional[str] = None
    citation_checks: Optional[List[CitationCheckResponse]] = None


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


class MessageRatingRequest(BaseModel):
    """Request model for rating an answer; null clears the rating."""

    rating: Optional[Literal["up", "down"]] = None


def _resolve_query_scope(db, request, current_user):
    """Resolve conversation, project, and source access before rate limits."""
    project_id = request.project_id
    conversation = None
    if request.conversation_id:
        conversation = require_conversation(db, request.conversation_id, current_user)
        if project_id and conversation.project_id != project_id:
            raise HTTPException(
                status_code=400,
                detail="Conversation does not belong to the selected project",
            )
        project_id = project_id or conversation.project_id

    if project_id:
        require_project(db, project_id, current_user, min_role="viewer")
        allowed_document_ids = owned_document_ids(
            db, current_user, project_id=project_id
        )
        if request.document_ids is not None:
            allowed_document_ids = require_documents(
                db,
                request.document_ids,
                current_user,
                project_id=project_id,
            )
    else:
        allowed_document_ids = owned_document_ids(db, current_user)
        if request.document_ids is not None:
            allowed_document_ids = require_documents(
                db, request.document_ids, current_user
            )
    return project_id, conversation, allowed_document_ids


def _acquire_query_lease(settings, request_limiter, concurrency_limiter, user_id):
    lease = UnlimitedConcurrencyLease()
    if settings.rate_limit_enabled:
        enforce_account_rate_limit(
            request_limiter, "query", user_id, limit=30, window_seconds=60
        )
        lease = acquire_account_lease(concurrency_limiter, "query", user_id)
    return lease


@router.post("/search", response_model=ProjectSearchResponse)
def search_projects(
    request: ProjectSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    rag_service: Any = Depends(get_rag_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    settings: Settings = Depends(get_settings),
):
    """Return hybrid-ranked source passages across visible projects.

    Args:
        request: Search text.
        db: Database session.
        current_user: Signed-in account whose project access defines scope.
        rag_service: Existing dense and lexical retrieval service.
        request_limiter: Per-account query request limiter.
        concurrency_limiter: Per-account active-operation limiter.
        settings: Current rate and concurrency settings.

    Returns:
        Ranked passages grouped by project and source document.
    """
    lease = _acquire_query_lease(
        settings,
        request_limiter,
        concurrency_limiter,
        current_user.id,
    )
    try:
        return search_visible_projects(db, current_user, rag_service, request.query)
    except Exception as error:
        logger.error("Cross-project search failed", error=str(error))
        raise HTTPException(status_code=500, detail="Search failed") from error
    finally:
        lease.release()


@router.post(
    "/query",
    response_model=QueryResponse,
    response_model_exclude_unset=True,
)
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
        # Resolve every ownership-bearing id before abuse controls. Otherwise a
        # depleted limiter would turn another account's normally indistinguishable
        # 404 into a 429 and reveal that the probed id follows a different path.
        project_id, conversation, allowed_document_ids = _resolve_query_scope(
            db, request, current_user
        )
        conversation_id = request.conversation_id
        lease = _acquire_query_lease(
            settings, request_limiter, concurrency_limiter, current_user.id
        )
        try:
            if conversation is not None:
                # Process query with conversation context
                result = rag_service.query_with_conversation(
                    db=db,
                    query=request.query,
                    conversation_id=conversation_id,
                    project_id=project_id,
                    top_k=request.top_k,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    include_sources=request.include_sources,
                    allowed_document_ids=allowed_document_ids
                )
            else:
                # Create new conversation if project is specified
                if project_id:
                    conversation = Conversation(
                        id=str(uuid.uuid4()),
                        project_id=project_id,
                        user_id=current_user.id,
                        title=request.query[:100]
                    )
                    db.add(conversation)
                    db.commit()
                    conversation_id = conversation.id

                    result = rag_service.query_with_conversation(
                        db=db,
                        query=request.query,
                        conversation_id=conversation_id,
                        project_id=project_id,
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
                        project_id=project_id,
                        top_k=request.top_k,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        include_sources=request.include_sources,
                        allowed_document_ids=allowed_document_ids
                    )
        finally:
            lease.release()
        
        response_fields = {}
        if "citation_checks" in result:
            response_fields["citation_checks"] = result["citation_checks"]
        return QueryResponse(
            answer=result["answer"],
            sources=result.get("sources", []),
            chunks_used=result["chunks_used"],
            model_used=result["model_used"],
            usage=result.get("usage", {}),
            conversation_id=conversation_id,
            **response_fields,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/stream", response_class=StreamingResponse)
def stream_query(
    request: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    rag_service: Any = Depends(get_rag_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    settings: Settings = Depends(get_settings),
):
    """Stream a grounded answer and save its completed conversation turn."""
    lease = None
    try:
        project_id, conversation, allowed_document_ids = _resolve_query_scope(
            db, request, current_user
        )
        conversation_id = request.conversation_id
        new_conversation = conversation_id is None and project_id is not None
        if new_conversation:
            conversation_id = str(uuid.uuid4())
        rag_conversation_id = conversation_id or str(uuid.uuid4())
        persist = conversation is not None or new_conversation
        lease = _acquire_query_lease(
            settings, request_limiter, concurrency_limiter, current_user.id
        )

        def events():
            rag_events = None
            persist_started = False
            completed = False
            try:
                rag_events = rag_service.stream_query_with_conversation(
                    db=db,
                    query=request.query,
                    conversation_id=rag_conversation_id,
                    project_id=project_id,
                    top_k=request.top_k,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    include_sources=request.include_sources,
                    allowed_document_ids=allowed_document_ids,
                )
                for event, payload in rag_events:
                    if event == "delta":
                        yield _sse("token", {"text": payload})
                        continue
                    if event != "complete":
                        raise RuntimeError("Unexpected RAG streaming event")

                    message_id = None
                    if persist:
                        persist_started = True
                        if new_conversation:
                            db.add(Conversation(
                                id=conversation_id,
                                project_id=project_id,
                                user_id=current_user.id,
                                title=request.query[:100],
                            ))
                        db.add(Message(
                            id=str(uuid.uuid4()),
                            conversation_id=conversation_id,
                            role="user",
                            text=request.query,
                            citations_json=[],
                        ))
                        assistant = Message(
                            id=str(uuid.uuid4()),
                            conversation_id=conversation_id,
                            role="assistant",
                            text=payload["answer"],
                            citations_json=payload.get("sources", []),
                            citation_checks_json=payload.get("citation_checks"),
                            used_mode=payload.get("model_used"),
                            token_count=payload.get("usage", {}).get("total_tokens"),
                        )
                        db.add(assistant)
                        db.commit()
                        message_id = assistant.id

                    completed = True
                    yield _sse("complete", {
                        **payload,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                    })
                    return

                if not completed:
                    raise RuntimeError("RAG stream ended before completion")
            except Exception as error:
                if persist_started:
                    db.rollback()
                logger.error("Streaming query failed", error=str(error))
                yield _sse("error", {"detail": str(error)})
            finally:
                close = getattr(rag_events, "close", None)
                if close:
                    close()

        return ClosingStreamingResponse(
            events(),
            lease,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        if lease is not None:
            lease.release()
        raise
    except Exception as error:
        if lease is not None:
            lease.release()
        logger.error("Unable to start streaming query", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error


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
    require_project(db, project_id, current_user, min_role="viewer")

    conversation = Conversation(
        id=str(uuid.uuid4()),
        project_id=project_id,
        user_id=current_user.id,
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
            "citations": msg.citations_json,
            "rating": msg.rating,
        })
        if get_settings().citation_check_enabled and msg.citation_checks_json is not None:
            messages[-1]["citation_checks"] = msg.citation_checks_json
    
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


@router.put("/conversations/{conversation_id}/messages/{message_id}/rating")
def rate_message(
    conversation_id: str,
    message_id: str,
    request: MessageRatingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set, change or clear the rating on one of the caller's answers.

    Args:
        conversation_id: Conversation holding the message.
        message_id: Assistant message to rate.
        request: "up", "down", or null to clear.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        The message id and its rating.
    """
    require_conversation(db, conversation_id, current_user)
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.conversation_id == conversation_id,
        Message.role == "assistant",
    ).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    message.rating = request.rating
    db.commit()
    return {"id": message.id, "rating": message.rating}


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
    project = require_project(db, project_id, current_user, min_role="viewer")

    query = db.query(Conversation).filter(
        Conversation.project_id == project_id
    )
    query = query.filter(
        or_(Conversation.user_id == current_user.id, Conversation.user_id.is_(None))
        if project.user_id == current_user.id
        else Conversation.user_id == current_user.id
    )
    conversations = query.order_by(Conversation.updated_at.desc()).all()
    
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
