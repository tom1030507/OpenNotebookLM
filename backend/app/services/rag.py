"""RAG (Retrieval-Augmented Generation) query service."""
import json
import hashlib
from typing import List, Dict, Any, Optional, Tuple
import structlog
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Document, Chunk, Project, ProjectDocument
from app.services.embeddings import EmbeddingService
from app.services.llm import LLMService

# Try to import cache service
try:
    from app.services.cache import cache_service
except ImportError:
    cache_service = None

logger = structlog.get_logger()
settings = get_settings()


class RAGService:
    """Service for RAG-based query processing."""
    
    def __init__(self):
        """Initialize RAG service."""
        self.embedding_service = EmbeddingService()
        self.llm_service = LLMService()
    
    def query(
        self,
        db: Session,
        query: str,
        project_id: Optional[str] = None,
        top_k: int = 5,
        temperature: float = 0.7,
        max_tokens: int = 512,
        include_sources: bool = True,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Process a query using RAG.
        
        Args:
            db: Database session
            query: User query
            project_id: Optional project ID to limit search scope
            top_k: Number of chunks to retrieve
            temperature: LLM temperature
            max_tokens: Maximum tokens in response
            include_sources: Whether to include source citations
            use_cache: Whether to use cache for query results
            
        Returns:
            Query response with answer and sources
        """
        try:
            # Check cache first if enabled
            if use_cache and cache_service:
                # Create a cache key from query parameters
                cache_key = self._generate_cache_key(
                    query=query,
                    project_id=project_id,
                    top_k=top_k,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    include_sources=include_sources
                )
                
                cached_result = cache_service.get_cached_query(
                    project_id=project_id or "global",
                    query=cache_key
                )
                
                if cached_result:
                    logger.info(f"Cache hit for query: {query[:50]}...")
                    return cached_result
            
            # 1. Retrieve relevant chunks
            logger.info(f"Processing RAG query: {query[:100]}...")
            
            relevant_chunks = self._retrieve_chunks(
                db=db,
                query=query,
                project_id=project_id,
                top_k=top_k
            )
            
            if not relevant_chunks:
                return {
                    "answer": "I couldn't find any relevant information in the documents to answer your question.",
                    "sources": [],
                    "chunks_used": 0,
                    "model_used": None
                }
            
            # 2. Prepare context
            context = self._prepare_context(relevant_chunks)
            
            # 3. Generate answer using LLM
            prompt = self._build_prompt(query, context, include_sources)
            
            answer = self.llm_service.generate(
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # 4. Format response
            response = {
                "answer": answer["text"],
                "sources": self._format_sources(relevant_chunks) if include_sources else [],
                "chunks_used": len(relevant_chunks),
                "model_used": answer["model"],
                "usage": answer.get("usage", {})
            }
            
            logger.info(
                "RAG query completed",
                chunks_used=len(relevant_chunks),
                model=answer["model"]
            )
            
            # Cache the result if enabled
            if use_cache and cache_service:
                cache_key = self._generate_cache_key(
                    query=query,
                    project_id=project_id,
                    top_k=top_k,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    include_sources=include_sources
                )
                
                cache_service.cache_query_result(
                    project_id=project_id or "global",
                    query=cache_key,
                    result=response,
                    ttl=3600  # Cache for 1 hour
                )
                logger.info(f"Cached query result for: {query[:50]}...")
            
            return response
            
        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            raise
    
    def _generate_cache_key(
        self,
        query: str,
        project_id: Optional[str] = None,
        top_k: int = 5,
        temperature: float = 0.7,
        max_tokens: int = 512,
        include_sources: bool = True
    ) -> str:
        """Generate a unique cache key for the query.
        
        Args:
            query: User query
            project_id: Optional project ID
            top_k: Number of chunks to retrieve
            temperature: LLM temperature
            max_tokens: Maximum tokens in response
            include_sources: Whether to include source citations
            
        Returns:
            Unique cache key
        """
        # Create a string representation of all parameters
        key_parts = [
            query,
            str(project_id),
            str(top_k),
            str(temperature),
            str(max_tokens),
            str(include_sources)
        ]
        key_string = "|".join(key_parts)
        
        # Generate a hash for the key
        return hashlib.sha256(key_string.encode()).hexdigest()
    
    def _retrieve_chunks(
        self,
        db: Session,
        query: str,
        project_id: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant chunks for the query.
        
        Args:
            db: Database session
            query: Search query
            project_id: Optional project ID
            top_k: Number of chunks to retrieve
            
        Returns:
            List of relevant chunks with metadata
        """
        # Get document IDs if project is specified
        document_ids = None
        if project_id:
            project_docs = db.query(ProjectDocument).filter(
                ProjectDocument.project_id == project_id
            ).all()
            document_ids = [pd.document_id for pd in project_docs]
            
            if not document_ids:
                logger.warning(f"No documents found in project {project_id}")
                return []
        
        # Use embedding service for semantic search
        similar_chunks = self.embedding_service.search_similar_chunks(
            db=db,
            query=query,
            document_ids=document_ids,
            top_k=top_k * 2,  # Get more candidates for reranking
            threshold=0.5  # Lower threshold to get more candidates
        )
        
        if not similar_chunks:
            return []
        
        # Rerank if enabled
        if settings.rerank_enabled:
            similar_chunks = self._rerank_chunks(
                query=query,
                chunks=similar_chunks,
                top_k=top_k
            )
        else:
            similar_chunks = similar_chunks[:top_k]
        
        return similar_chunks
    
    def _rerank_chunks(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """Rerank chunks using a combination of factors.
        
        Args:
            query: Search query
            chunks: Initial chunks from vector search
            top_k: Number of chunks to return
            
        Returns:
            Reranked chunks
        """
        # Simple reranking based on multiple factors
        for chunk in chunks:
            # Vector similarity score (already present)
            vector_score = chunk["score"]
            
            # Keyword match score
            query_terms = set(query.lower().split())
            chunk_terms = set(chunk["text"].lower().split())
            keyword_score = len(query_terms & chunk_terms) / len(query_terms) if query_terms else 0
            
            # Length penalty (prefer chunks with reasonable length)
            text_length = len(chunk["text"])
            if text_length < 100:
                length_score = 0.5
            elif text_length > 1000:
                length_score = 0.8
            else:
                length_score = 1.0
            
            # Combined score with configurable weights
            chunk["rerank_score"] = (
                settings.rerank_alpha * vector_score +
                settings.rerank_beta * keyword_score +
                settings.rerank_gamma * length_score
            )
        
        # Sort by reranked score
        chunks.sort(key=lambda x: x["rerank_score"], reverse=True)
        
        return chunks[:top_k]
    
    def _prepare_context(self, chunks: List[Dict[str, Any]]) -> str:
        """Prepare context from retrieved chunks.
        
        Args:
            chunks: Retrieved chunks
            
        Returns:
            Formatted context string
        """
        context_parts = []
        
        for i, chunk in enumerate(chunks, 1):
            # Include source information
            source_info = f"[Source {i}: {chunk['document_title']}"
            
            # Add page number if available
            if chunk["metadata"].get("page_num"):
                source_info += f", Page {chunk['metadata']['page_num']}"
            
            # Add timestamp if available
            if chunk["metadata"].get("timestamp"):
                timestamp = chunk["metadata"]["timestamp"]
                source_info += f", {timestamp:.1f}s"
            
            source_info += "]"
            
            # Add chunk text
            context_parts.append(f"{source_info}\n{chunk['text']}")
        
        return "\n\n".join(context_parts)
    
    def _build_prompt(
        self,
        query: str,
        context: str,
        include_sources: bool
    ) -> str:
        """Build the prompt for the LLM.
        
        Args:
            query: User query
            context: Retrieved context
            include_sources: Whether to request source citations
            
        Returns:
            Formatted prompt
        """
        if include_sources:
            prompt = f"""You are a helpful assistant that answers questions based on the provided context.
Use the following context to answer the question. If you use information from the context, cite the source by referencing [Source X].
If the context doesn't contain relevant information, say so.

Context:
{context}

Question: {query}

Answer (with source citations):"""
        else:
            prompt = f"""You are a helpful assistant that answers questions based on the provided context.
Use the following context to answer the question.
If the context doesn't contain relevant information, say so.

Context:
{context}

Question: {query}

Answer:"""
        
        return prompt
    
    def _format_sources(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format source citations.
        
        Args:
            chunks: Retrieved chunks
            
        Returns:
            Formatted source citations
        """
        sources = []
        
        for i, chunk in enumerate(chunks, 1):
            source = {
                "id": i,
                "document_id": chunk["document_id"],
                "document_title": chunk["document_title"],
                "chunk_id": chunk["chunk_id"],
                "text_preview": chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"],
                "score": chunk.get("rerank_score", chunk["score"])
            }
            
            # Add optional metadata
            if chunk["metadata"].get("page_num"):
                source["page_num"] = chunk["metadata"]["page_num"]
            
            if chunk["metadata"].get("timestamp"):
                source["timestamp"] = chunk["metadata"]["timestamp"]
            
            if chunk["metadata"].get("section"):
                source["section"] = chunk["metadata"]["section"]
            
            sources.append(source)
        
        return sources
    
    def get_conversation_context(
        self,
        db: Session,
        conversation_id: str,
        max_messages: int = 10
    ) -> str:
        """Get conversation history for context.
        
        Args:
            db: Database session
            conversation_id: Conversation ID
            max_messages: Maximum number of messages to include
            
        Returns:
            Formatted conversation context
        """
        from app.db.models import Message
        
        messages = db.query(Message).filter(
            Message.conversation_id == conversation_id
        ).order_by(Message.created_at.desc()).limit(max_messages).all()
        
        # Reverse to get chronological order
        messages.reverse()
        
        context = []
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            context.append(f"{role}: {msg.text}")
        
        return "\n\n".join(context)
    
    def query_with_conversation(
        self,
        db: Session,
        query: str,
        conversation_id: str,
        project_id: Optional[str] = None,
        top_k: int = 5,
        temperature: float = 0.7,
        max_tokens: int = 512,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Process a query with conversation context.
        
        Args:
            db: Database session
            query: User query
            conversation_id: Conversation ID
            project_id: Optional project ID
            top_k: Number of chunks to retrieve
            temperature: LLM temperature
            max_tokens: Maximum tokens in response
            
        Returns:
            Query response with conversation awareness
        """
        # Get conversation context
        conv_context = self.get_conversation_context(db, conversation_id)
        
        # Modify query to include conversation context
        if conv_context:
            enhanced_query = f"""Previous conversation:
{conv_context}

Current question: {query}"""
        else:
            enhanced_query = query
        
        # Process with regular query method
        response = self.query(
            db=db,
            query=enhanced_query,
            project_id=project_id,
            top_k=top_k,
            temperature=temperature,
            max_tokens=max_tokens,
            use_cache=use_cache
        )
        
        # Save to conversation
        from app.db.models import Message
        import uuid
        
        # Save user message
        user_msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="user",
            text=query,
            citations_json=[]
        )
        db.add(user_msg)
        
        # Save assistant message
        assistant_msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            text=response["answer"],
            citations_json=response.get("sources", []),
            used_mode=response.get("model_used"),
            token_count=response.get("usage", {}).get("total_tokens")
        )
        db.add(assistant_msg)
        
        db.commit()
        
        return response
