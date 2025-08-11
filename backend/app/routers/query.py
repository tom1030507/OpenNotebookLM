"""Query and RAG router."""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import structlog
import uuid

from app.db.database import get_db
from app.services.rag import RAGService
from app.services.projects import ProjectService
from app.db.models import Conversation, Project

router = APIRouter()
logger = structlog.get_logger()

# Initialize services
rag_service = RAGService()


class QueryRequest(BaseModel):
    """Query request model."""
    query: str
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    top_k: int = 5
    temperature: float = 0.7
    max_tokens: int = 512
    include_sources: bool = True


class QueryResponse(BaseModel):
    """Query response model."""
    answer: str
    sources: List[dict]
    chunks_used: int
    model_used: Optional[str]
    usage: dict
    conversation_id: Optional[str] = None


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: Session = Depends(get_db)
):
    """Process a RAG query.
    
    This endpoint:
    1. Retrieves relevant document chunks
    2. Uses them as context for the LLM
    3. Returns an answer with source citations
    """
    try:
        # Validate project if specified
        if request.project_id:
            project = db.query(Project).filter(
                Project.id == request.project_id
            ).first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
        
        # Handle conversation
        conversation_id = request.conversation_id
        if request.conversation_id:
            # Use existing conversation
            conversation = db.query(Conversation).filter(
                Conversation.id == request.conversation_id
            ).first()
            if not conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")
            
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
                max_tokens=request.max_tokens
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
                    max_tokens=request.max_tokens
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
                    include_sources=request.include_sources
                )
        
        return QueryResponse(
            answer=result["answer"],
            sources=result.get("sources", []),
            chunks_used=result["chunks_used"],
            model_used=result["model_used"],
            usage=result.get("usage", {}),
            conversation_id=conversation_id
        )
        
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """Get conversation details with messages."""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
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


@router.get("/projects/{project_id}/conversations")
async def list_project_conversations(
    project_id: str,
    db: Session = Depends(get_db)
):
    """List all conversations in a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    conversations = db.query(Conversation).filter(
        Conversation.project_id == project_id
    ).order_by(Conversation.updated_at.desc()).all()
    
    return [
        {
            "id": conv.id,
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
    db: Session = Depends(get_db)
):
    """Delete a conversation."""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    db.delete(conversation)
    db.commit()
    
    return {"status": "success", "message": "Conversation deleted"}
