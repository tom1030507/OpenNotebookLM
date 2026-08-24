"""RAG (Retrieval-Augmented Generation) query service."""
import json
import hashlib
from time import perf_counter
from typing import List, Dict, Any, Optional, Tuple
import structlog
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Document, Chunk, Project, ProjectDocument
from app.services import retrieval
from app.services.llm import LLMService
from app.services.retrieval_index import get_retrieval_index

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
    
    def __init__(
        self,
        embedding_service: Any | None = None,
        llm_service: Any | None = None,
    ):
        """Initialize RAG dependencies.

        Args:
            embedding_service: Optional embedding and dense-search implementation.
            llm_service: Optional answer-generation implementation.

        Returns:
            None.
        """
        if embedding_service is None:
            from app.services.embeddings import EmbeddingService

            embedding_service = EmbeddingService()

        self.embedding_service = embedding_service
        self.llm_service = llm_service if llm_service is not None else LLMService()
    
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
        retrieval_query: Optional[str] = None,
        allowed_document_ids: Optional[List[str]] = None
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
            allowed_document_ids: Hard limit on which documents may be searched,
                regardless of project. The API passes the caller's own documents,
                so a question can never reach another account's chunks. An empty
                list means nothing is searchable; None means no limit, which only
                callers outside the request path (the eval harness) should use.

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
                    retrieval_query=retrieval_query,
                    allowed_document_ids=allowed_document_ids
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
                top_k=top_k,
                allowed_document_ids=allowed_document_ids
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
                    retrieval_query=retrieval_query,
                    allowed_document_ids=allowed_document_ids
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
        retrieval_query: Optional[str] = None,
        allowed_document_ids: Optional[List[str]] = None
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
        # The scope is part of the key. Without it two accounts asking the same
        # question with no project selected would share a cache entry, and the
        # second would be served the first one's answer -- built from documents it
        # is not allowed to see.
        scope = "any" if allowed_document_ids is None else ",".join(sorted(allowed_document_ids))

        key_parts = [
            query,
            str(retrieval_query),
            scope,
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
        top_k: Optional[int] = None,
        allowed_document_ids: Optional[List[str]] = None
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
            allowed_document_ids: Hard limit on searchable documents, applied on
                top of the project scope rather than instead of it

        Returns:
            List of relevant chunks with metadata
        """
        chunks, _ = self.retrieve_with_diagnostics(
            db=db,
            query=query,
            project_id=project_id,
            top_k=top_k,
            allowed_document_ids=allowed_document_ids,
        )
        return chunks

    def retrieve_with_diagnostics(
        self,
        db: Session,
        query: str,
        project_id: Optional[str] = None,
        top_k: Optional[int] = None,
        allowed_document_ids: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Retrieve indexed candidates and return request-local diagnostics.

        Args:
            db: Database session.
            query: Search query.
            project_id: Optional project scope.
            top_k: Maximum fused results.
            allowed_document_ids: Hard document-ownership scope.

        Returns:
            A pair of hydrated results and retrieval diagnostics.
        """
        started = perf_counter()
        top_k = top_k or settings.retrieval_top_k
        index = get_retrieval_index()

        def diagnostics(
            dense_count: int = 0,
            lexical_count: int = 0,
            fused_count: int = 0,
        ) -> Dict[str, Any]:
            # Passing the request Session would count canonical/index rows on
            # every query. Searches already initialize the active backends, so
            # the cached capability view is sufficient and constant-work.
            index_status = index.status()
            status_payload = (
                index_status.as_dict()
                if hasattr(index_status, "as_dict")
                else dict(index_status)
            )
            active_backend = status_payload.get("active_backend")
            if not active_backend:
                dense_backend = (
                    status_payload.get("dense_backend")
                    or status_payload.get("active_dense_backend")
                )
                lexical_backend = (
                    status_payload.get("lexical_backend")
                    or status_payload.get("active_lexical_backend")
                )
                active_backend = "+".join(
                    backend
                    for backend in (dense_backend, lexical_backend)
                    if backend
                ) or "unavailable"
            return {
                "dense_candidates": dense_count,
                "lexical_candidates": lexical_count,
                "fused_candidates": fused_count,
                "latency_ms": (perf_counter() - started) * 1000,
                "active_backend": active_backend,
            }

        # Get document IDs if project is specified
        document_ids = None
        if project_id:
            project_docs = db.query(ProjectDocument).filter(
                ProjectDocument.project_id == project_id
            ).all()
            document_ids = [pd.document_id for pd in project_docs]

            if not document_ids:
                logger.warning(f"No documents found in project {project_id}")
                return [], diagnostics()

        # Narrow to what the caller may see. This is applied last and always, so
        # a project scope cannot widen it: attaching someone else's document to a
        # project would still not make it searchable.
        if allowed_document_ids is not None:
            allowed = set(allowed_document_ids)
            document_ids = (
                [doc_id for doc_id in document_ids if doc_id in allowed]
                if document_ids is not None
                else sorted(allowed)
            )
            if not document_ids:
                return [], diagnostics()

        candidate_k = max(settings.retrieval_candidate_k, top_k)

        # The query vector is generated exactly once per request. Indexed
        # search consumes the raw float32 values and never loads the canonical
        # pickled Embedding table on the normal path.
        query_vector = self.embedding_service.generate_embedding(
            query,
            normalize=True,
            role="query",
        )
        dense_candidates = index.dense_search(
            db,
            query_vector,
            document_ids=document_ids,
            top_k=candidate_k,
            threshold=settings.retrieval_min_score,
        )

        lexical_candidates = (
            index.lexical_search(
                db,
                query,
                document_ids=document_ids,
                top_k=candidate_k,
            )
            if settings.hybrid_enabled
            else []
        )

        candidate_ids = list(dict.fromkeys(
            [candidate.chunk_id for candidate in dense_candidates]
            + [candidate.chunk_id for candidate in lexical_candidates]
        ))
        if not candidate_ids:
            return [], diagnostics(
                dense_count=len(dense_candidates),
                lexical_count=len(lexical_candidates),
            )

        hydrated = index.hydrate(db, candidate_ids)
        allowed_scope = set(document_ids) if document_ids is not None else None
        hydrated_by_id = {
            payload["chunk_id"]: payload
            for payload in hydrated
            if (
                allowed_scope is None
                or payload["document_id"] in allowed_scope
            )
        }

        def ranked_payloads(candidates):
            ranked = []
            for candidate in candidates:
                payload = hydrated_by_id.get(candidate.chunk_id)
                if payload is None:
                    continue
                item = dict(payload)
                item["metadata"] = dict(payload.get("metadata") or {})
                item["score"] = float(candidate.score)
                ranked.append(item)
            return ranked

        dense = ranked_payloads(dense_candidates)
        lexical = ranked_payloads(lexical_candidates)

        if not settings.hybrid_enabled:
            results = (
                self._rerank_chunks(query=query, chunks=dense, top_k=top_k)
                if settings.rerank_enabled
                else dense[:top_k]
            )
        elif dense or lexical:
            results = self._fuse(dense, lexical, top_k)
        else:
            results = []

        return results, diagnostics(
            dense_count=len(dense),
            lexical_count=len(lexical),
            fused_count=len(results),
        )

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
        use_cache: bool = True,
        allowed_document_ids: Optional[List[str]] = None
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
            allowed_document_ids: Hard limit on searchable documents; see `query`

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
            retrieval_query=self._retrieval_query(db, query, conversation_id),
            allowed_document_ids=allowed_document_ids
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
