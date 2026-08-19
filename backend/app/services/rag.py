"""RAG (Retrieval-Augmented Generation) query service."""
import json
import hashlib
from typing import List, Dict, Any, Optional, Tuple
import structlog
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Document, Chunk, Project, ProjectDocument
from app.services.embeddings import EmbeddingService
from app.services import retrieval
from app.services.llm import LLMService

# Try to import cache service
try:
    from app.services.cache import cache_service
except ImportError:
    cache_service = None

logger = structlog.get_logger()
settings = get_settings()

# A follow-up this short ("and the second one?") carries no searchable terms of
# its own, so the previous question is folded into the retrieval query for
# coreference. Anything longer stands on its own: mixing history in dilutes the
# query vector, and the embedding model truncates at its sequence limit from the
# end -- which is exactly where the current question sits.
FOLLOWUP_CHAR_FLOOR = 16


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
        top_k: Optional[int] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        include_sources: bool = True,
        use_cache: bool = True,
        retrieval_query: Optional[str] = None
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
            retrieval_query: What to search with, when it differs from what the
                model is asked. Conversation turns need this: the prompt carries
                the transcript, but retrieval must run on the current question.

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
                    include_sources=include_sources,
                    retrieval_query=retrieval_query
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
                query=retrieval_query or query,
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
                max_tokens=max_tokens,
                system_prompt=self._system_prompt(include_sources)
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
                    include_sources=include_sources,
                    retrieval_query=retrieval_query
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
        top_k: Optional[int] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        include_sources: bool = True,
        retrieval_query: Optional[str] = None
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
        # The full prompt input is part of the key on purpose. In a
        # conversation the answer depends on the transcript, so keying on the
        # current question alone would serve an answer computed under different
        # history -- a correctness bug dressed up as a higher hit rate.
        key_parts = [
            query,
            str(retrieval_query),
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
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant chunks for the query.

        Runs a dense search and a BM25 search over the same scope, then fuses
        them by reciprocal rank. The lexical half is what makes exact terms and
        Chinese text retrievable: dense similarities from a multilingual e5 model
        sit in a band about 0.01 wide across relevant and irrelevant chunks
        alike, so on its own the dense ranking is close to arbitrary.

        Args:
            db: Database session
            query: Search query
            project_id: Optional project ID
            top_k: Number of chunks to retrieve; defaults to RETRIEVAL_TOP_K

        Returns:
            List of relevant chunks with metadata
        """
        top_k = top_k or settings.retrieval_top_k

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

        candidate_k = max(settings.retrieval_candidate_k, top_k)

        dense = self.embedding_service.search_similar_chunks(
            db=db,
            query=query,
            document_ids=document_ids,
            top_k=candidate_k,
            threshold=settings.retrieval_min_score,
        )

        if not settings.hybrid_enabled:
            if settings.rerank_enabled:
                return self._rerank_chunks(query=query, chunks=dense, top_k=top_k)
            return dense[:top_k]

        lexical = self._lexical_candidates(db, query, document_ids, candidate_k)

        if not dense and not lexical:
            return []

        return self._fuse(dense, lexical, top_k)

    def _lexical_candidates(
        self,
        db: Session,
        query: str,
        document_ids: Optional[List[str]],
        candidate_k: int
    ) -> List[Dict[str, Any]]:
        """Rank chunks by BM25 over the same scope as the dense search.

        Scores every in-scope chunk, which is the same order of work the dense
        search already does with its full scan, so this adds no new asymptotic
        cost.

        Args:
            db: Database session
            query: Search query
            document_ids: Optional document scope
            candidate_k: How many candidates to keep

        Returns:
            Candidates in BM25 order, shaped like the dense results
        """
        query_tokens = retrieval.tokenize(query)
        if not query_tokens:
            return []

        rows = db.query(Chunk, Document.title).join(
            Document, Document.id == Chunk.document_id
        )
        if document_ids:
            rows = rows.filter(Chunk.document_id.in_(document_ids))
        rows = rows.all()
        if not rows:
            return []

        # The heading path is searchable too: a section name often carries the
        # question's vocabulary when the passage body does not.
        documents = [
            retrieval.tokenize(
                " ".join(part for part in (chunk.heading_path, chunk.text) if part)
            )
            for chunk, _ in rows
        ]
        scores = retrieval.bm25_scores(query_tokens, documents)

        scored = [
            (score, chunk, title)
            for score, (chunk, title) in zip(scores, rows)
            if score > 0
        ]
        scored.sort(key=lambda item: item[0], reverse=True)

        return [
            self._chunk_payload(chunk, title, score)
            for score, chunk, title in scored[:candidate_k]
        ]

    @staticmethod
    def _chunk_payload(chunk: Chunk, document_title: Optional[str], score: float) -> Dict[str, Any]:
        """Shape a chunk row the way the dense search shapes its results.

        Args:
            chunk: The chunk row
            document_title: Title of the document it belongs to
            score: Retriever score

        Returns:
            A result dict
        """
        return {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": document_title or "Unknown",
            "text": chunk.text,
            "score": float(score),
            "metadata": {
                "page_num": chunk.page_num,
                "timestamp": chunk.ts_start,
                "section": chunk.meta_json.get("section") if chunk.meta_json else None,
                "heading_path": chunk.heading_path,
            },
        }

    def _fuse(
        self,
        dense: List[Dict[str, Any]],
        lexical: List[Dict[str, Any]],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """Combine two ranked candidate lists and drop repeats.

        Args:
            dense: Candidates from the vector search, best first
            lexical: Candidates from BM25, best first
            top_k: How many chunks to return

        Returns:
            The fused, deduplicated top_k
        """
        payloads: Dict[str, Dict[str, Any]] = {}
        for item in list(dense) + list(lexical):
            payloads.setdefault(item["chunk_id"], item)

        fused = retrieval.fuse_rankings(
            [
                [item["chunk_id"] for item in dense],
                [item["chunk_id"] for item in lexical],
            ],
            k=settings.hybrid_rrf_k,
        )

        ordered = sorted(
            payloads.values(),
            key=lambda item: fused.get(item["chunk_id"], (0.0, 0.0)),
            reverse=True,
        )
        for item in ordered:
            best, total = fused.get(item["chunk_id"], (0.0, 0.0))
            item["rerank_score"] = best + total

        tokens = {item["chunk_id"]: retrieval.tokenize(item["text"]) for item in ordered}
        deduped = retrieval.dedupe_near_duplicates(
            ordered,
            tokens_of=lambda item: tokens[item["chunk_id"]],
            threshold=settings.dedupe_jaccard,
        )

        return deduped[:top_k]

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
        used = 0

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
            
            # Add the section the passage came from. Without it a citation
            # says only which document answered, and the model loses the one cue
            # that tells it which part of a long document it is reading.
            heading_path = chunk["metadata"].get("heading_path")
            if heading_path and heading_path != chunk["document_title"]:
                source_info += ", " + heading_path

            source_info += "]"

            entry = f"{source_info}\n{chunk['text']}"

            # Keep the prompt bounded. top_k is caller-supplied and unvalidated,
            # so without this a large value grows the prompt until the provider
            # rejects it.
            if context_parts and used + len(entry) > settings.context_char_budget:
                logger.info(
                    "Context budget reached, dropping remaining chunks",
                    kept=len(context_parts),
                    total=len(chunks),
                )
                break

            context_parts.append(entry)
            used += len(entry) + 2

        return "\n\n".join(context_parts)
    
    def _system_prompt(self, include_sources: bool) -> str:
        """Instructions for the model, as a system message.

        These used to ride inside the user turn. Providers weight a system
        message more strongly for instruction following, and keeping the
        instructions separate from the question is also what lets a provider
        cache the stable half of the prompt.

        Args:
            include_sources: Whether to ask for source citations

        Returns:
            The system prompt
        """
        base = (
            "You answer questions using only the context provided in the user "
            "message. If the context does not contain the answer, say so plainly "
            "instead of guessing. Answer in the language the question is asked in."
        )
        if include_sources:
            base += (
                " Cite the passages you used by their bracketed label, for example "
                "[Source 2]. Do not cite a passage you did not use."
            )
        return base

    def _build_prompt(
        self,
        query: str,
        context: str,
        include_sources: bool
    ) -> str:
        """Build the user turn: the retrieved context and the question.

        Args:
            query: User query
            context: Retrieved context
            include_sources: Whether to request source citations

        Returns:
            Formatted prompt
        """
        answer_cue = "Answer (with source citations):" if include_sources else "Answer:"

        return f"""Context:
{context}

Question: {query}

{answer_cue}"""

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
    
    def _retrieval_query(
        self,
        db: Session,
        query: str,
        conversation_id: str
    ) -> str:
        """Decide what to search with for one conversation turn.

        Args:
            db: Database session
            query: The question just asked
            conversation_id: Conversation the turn belongs to

        Returns:
            The question, with the previous one prepended if it is too short to
            search with on its own.
        """
        if len(query.strip()) >= FOLLOWUP_CHAR_FLOOR:
            return query

        from app.db.models import Message

        previous = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.role == "user",
        ).order_by(Message.created_at.desc()).first()

        if previous and previous.text:
            return previous.text + " " + query
        return query

    def query_with_conversation(
        self,
        db: Session,
        query: str,
        conversation_id: str,
        project_id: Optional[str] = None,
        top_k: Optional[int] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        include_sources: bool = True,
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
            include_sources: Whether to include source citations

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
        
        # The transcript goes to the model; retrieval runs on the question.
        # Searching with the transcript was the single most damaging defect here:
        # the query vector was dominated by old turns, and because the sequence
        # limit truncates from the end, after a few turns the current question was
        # cut off entirely and retrieval ran on stale history alone.
        response = self.query(
            db=db,
            query=enhanced_query,
            project_id=project_id,
            top_k=top_k,
            temperature=temperature,
            max_tokens=max_tokens,
            include_sources=include_sources,
            use_cache=use_cache,
            retrieval_query=self._retrieval_query(db, query, conversation_id)
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
