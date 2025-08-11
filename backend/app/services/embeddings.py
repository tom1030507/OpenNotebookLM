"""Embedding generation service."""
import json
import uuid
import pickle
import hashlib
from typing import List, Dict, Any, Optional, Union
import numpy as np
import structlog
from sqlalchemy.orm import Session
from sentence_transformers import SentenceTransformer
import torch

from app.config import get_settings
from app.db.models import Document, Chunk, Embedding

# Try to import cache service
try:
    from app.services.cache import cache_service
except ImportError:
    cache_service = None

logger = structlog.get_logger()
settings = get_settings()


class EmbeddingService:
    """Service for generating and managing embeddings."""
    
    _instance = None
    _model = None
    
    def __new__(cls):
        """Singleton pattern to avoid loading model multiple times."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize embedding service."""
        if EmbeddingService._model is None:
            self._initialize_model()
    
    def _initialize_model(self):
        """Load the embedding model."""
        try:
            logger.info(f"Loading embedding model: {settings.emb_model_name}")
            
            # Set device
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            logger.info(f"Using device: {device}")
            
            # Load model
            EmbeddingService._model = SentenceTransformer(
                settings.emb_model_name,
                device=device
            )
            
            # Verify model dimension
            test_embedding = EmbeddingService._model.encode("test")
            actual_dim = len(test_embedding)
            
            if actual_dim != settings.emb_dimension:
                logger.warning(
                    f"Model dimension mismatch. Expected: {settings.emb_dimension}, "
                    f"Actual: {actual_dim}. Updating configuration."
                )
                settings.emb_dimension = actual_dim
            
            logger.info(f"Model loaded successfully. Dimension: {actual_dim}")
            
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    
    def generate_embedding(
        self,
        text: Union[str, List[str]],
        normalize: bool = True,
        use_cache: bool = True
    ) -> Union[np.ndarray, List[np.ndarray]]:
        """Generate embedding for text.
        
        Args:
            text: Text or list of texts to embed
            normalize: Whether to normalize the embeddings
            use_cache: Whether to use cache for embeddings
            
        Returns:
            Embedding vector(s)
        """
        try:
            if isinstance(text, str):
                # Check cache for single text
                if use_cache and cache_service:
                    # Generate cache key for the text
                    cache_key = hashlib.sha256(f"{text}_{normalize}".encode()).hexdigest()
                    cached_embedding = cache_service.get_cached_embedding(
                        document_id="text_embed",
                        chunk_id=cache_key
                    )
                    if cached_embedding is not None:
                        logger.debug(f"Cache hit for text embedding")
                        return cached_embedding
                
                # Single text
                embedding = EmbeddingService._model.encode(
                    text,
                    normalize_embeddings=normalize,
                    show_progress_bar=False
                )
                
                # Cache the result
                if use_cache and cache_service:
                    cache_service.cache_embedding(
                        document_id="text_embed",
                        chunk_id=cache_key,
                        embedding=embedding,
                        ttl=7200  # Cache for 2 hours
                    )
                
                return embedding
            else:
                # Batch processing with cache check
                embeddings = []
                texts_to_process = []
                indices_to_process = []
                
                if use_cache and cache_service:
                    # Check cache for each text
                    for i, t in enumerate(text):
                        cache_key = hashlib.sha256(f"{t}_{normalize}".encode()).hexdigest()
                        cached_embedding = cache_service.get_cached_embedding(
                            document_id="text_embed",
                            chunk_id=cache_key
                        )
                        if cached_embedding is not None:
                            embeddings.append((i, cached_embedding))
                        else:
                            texts_to_process.append(t)
                            indices_to_process.append(i)
                else:
                    texts_to_process = text
                    indices_to_process = list(range(len(text)))
                
                # Process uncached texts
                if texts_to_process:
                    new_embeddings = EmbeddingService._model.encode(
                        texts_to_process,
                        normalize_embeddings=normalize,
                        show_progress_bar=len(texts_to_process) > 100,
                        batch_size=32
                    )
                    
                    # Cache new embeddings
                    if use_cache and cache_service:
                        for t, emb in zip(texts_to_process, new_embeddings):
                            cache_key = hashlib.sha256(f"{t}_{normalize}".encode()).hexdigest()
                            cache_service.cache_embedding(
                                document_id="text_embed",
                                chunk_id=cache_key,
                                embedding=emb,
                                ttl=7200  # Cache for 2 hours
                            )
                    
                    # Combine with cached embeddings
                    for idx, emb in zip(indices_to_process, new_embeddings):
                        embeddings.append((idx, emb))
                
                # Sort by original index and extract embeddings
                embeddings.sort(key=lambda x: x[0])
                return np.array([emb for _, emb in embeddings])
                
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise
    
    def embed_chunks(
        self,
        db: Session,
        document_id: str,
        force_regenerate: bool = False
    ) -> List[Embedding]:
        """Generate embeddings for all chunks of a document.
        
        Args:
            db: Database session
            document_id: Document ID
            force_regenerate: Whether to regenerate existing embeddings
            
        Returns:
            List of embedding records
        """
        try:
            # Get document and chunks
            document = db.query(Document).filter(Document.id == document_id).first()
            if not document:
                raise ValueError(f"Document {document_id} not found")
            
            chunks = db.query(Chunk).filter(
                Chunk.document_id == document_id
            ).order_by(Chunk.id).all()
            
            if not chunks:
                logger.warning(f"No chunks found for document {document_id}")
                return []
            
            logger.info(f"Generating embeddings for {len(chunks)} chunks")
            
            # Check existing embeddings
            if not force_regenerate:
                existing_embeddings = db.query(Embedding).filter(
                    Embedding.chunk_id.in_([c.id for c in chunks])
                ).all()
                
                if len(existing_embeddings) == len(chunks):
                    logger.info("Embeddings already exist, skipping generation")
                    return existing_embeddings
                elif existing_embeddings:
                    logger.info(f"Found {len(existing_embeddings)} existing embeddings, "
                               f"generating {len(chunks) - len(existing_embeddings)} new ones")
            else:
                # Delete existing embeddings
                db.query(Embedding).filter(
                    Embedding.chunk_id.in_([c.id for c in chunks])
                ).delete()
                db.commit()
            
            # Prepare texts for batch processing
            texts_to_embed = []
            chunks_to_embed = []
            
            for chunk in chunks:
                # Skip if embedding already exists (unless force_regenerate)
                if not force_regenerate:
                    existing = db.query(Embedding).filter(
                        Embedding.chunk_id == chunk.id
                    ).first()
                    if existing:
                        continue
                
                # Prepare text with context
                chunk_text = chunk.text
                
                # Add document title as context
                if document.title:
                    chunk_text = f"{document.title}\n\n{chunk_text}"
                
                texts_to_embed.append(chunk_text)
                chunks_to_embed.append(chunk)
            
            if not texts_to_embed:
                logger.info("No new embeddings to generate")
                return db.query(Embedding).filter(
                    Embedding.chunk_id.in_([c.id for c in chunks])
                ).all()
            
            # Generate embeddings in batch (with caching)
            embeddings = self.generate_embedding(texts_to_embed, normalize=True, use_cache=True)
            
            # Save to database
            embedding_records = []
            for i, (chunk, embedding) in enumerate(zip(chunks_to_embed, embeddings)):
                # Convert to bytes for storage
                embedding_bytes = pickle.dumps(embedding.astype(np.float32))
                
                # Also store as JSON for compatibility
                embedding_json = embedding.tolist()
                
                embedding_record = Embedding(
                    id=str(uuid.uuid4()),
                    chunk_id=chunk.id,
                    vector=embedding_bytes,
                    vector_json=embedding_json,
                    model_name=settings.emb_model_name
                )
                
                db.add(embedding_record)
                embedding_records.append(embedding_record)
                
                # Commit in batches
                if (i + 1) % 100 == 0:
                    db.commit()
                    logger.info(f"Saved {i + 1} embeddings")
            
            db.commit()
            
            logger.info(
                f"Successfully generated {len(embedding_records)} embeddings "
                f"for document {document_id}"
            )
            
            return embedding_records
            
        except Exception as e:
            logger.error(f"Failed to embed chunks: {e}")
            db.rollback()
            raise
    
    def embed_all_documents(
        self,
        db: Session,
        project_id: Optional[str] = None,
        force_regenerate: bool = False
    ):
        """Generate embeddings for all documents in a project or all documents.
        
        Args:
            db: Database session
            project_id: Optional project ID to limit scope
            force_regenerate: Whether to regenerate existing embeddings
        """
        try:
            # Get documents
            if project_id:
                # Get documents for specific project
                from app.db.models import ProjectDocument
                doc_ids = db.query(ProjectDocument.document_id).filter(
                    ProjectDocument.project_id == project_id
                ).all()
                doc_ids = [d[0] for d in doc_ids]
                
                documents = db.query(Document).filter(
                    Document.id.in_(doc_ids),
                    Document.status == "ready"
                ).all()
            else:
                # Get all ready documents
                documents = db.query(Document).filter(
                    Document.status == "ready"
                ).all()
            
            logger.info(f"Found {len(documents)} documents to process")
            
            for i, document in enumerate(documents):
                logger.info(
                    f"Processing document {i+1}/{len(documents)}: "
                    f"{document.title} ({document.id})"
                )
                
                try:
                    self.embed_chunks(db, document.id, force_regenerate)
                except Exception as e:
                    logger.error(
                        f"Failed to embed document {document.id}: {e}"
                    )
                    continue
            
            logger.info("Completed embedding generation for all documents")
            
        except Exception as e:
            logger.error(f"Failed to embed all documents: {e}")
            raise
    
    def search_similar_chunks(
        self,
        db: Session,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: int = 5,
        threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks using vector similarity.
        
        Args:
            db: Database session
            query: Search query
            document_ids: Optional list of document IDs to search within
            top_k: Number of results to return
            threshold: Minimum similarity threshold
            
        Returns:
            List of similar chunks with scores
        """
        try:
            # Generate query embedding
            query_embedding = self.generate_embedding(query, normalize=True)
            
            # Get all embeddings (with optional document filter)
            embedding_query = db.query(Embedding).join(Chunk)
            
            if document_ids:
                embedding_query = embedding_query.filter(
                    Chunk.document_id.in_(document_ids)
                )
            
            embeddings = embedding_query.all()
            
            if not embeddings:
                logger.warning("No embeddings found")
                return []
            
            # Calculate similarities
            similarities = []
            for embedding in embeddings:
                # Load stored embedding
                stored_vector = pickle.loads(embedding.vector)
                
                # Calculate cosine similarity
                similarity = np.dot(query_embedding, stored_vector)
                
                if similarity >= threshold:
                    similarities.append({
                        "embedding_id": embedding.id,
                        "chunk_id": embedding.chunk_id,
                        "score": float(similarity)
                    })
            
            # Sort by similarity and get top k
            similarities.sort(key=lambda x: x["score"], reverse=True)
            top_results = similarities[:top_k]
            
            # Fetch chunk details
            results = []
            for result in top_results:
                chunk = db.query(Chunk).filter(
                    Chunk.id == result["chunk_id"]
                ).first()
                
                if chunk:
                    document = db.query(Document).filter(
                        Document.id == chunk.document_id
                    ).first()
                    
                    results.append({
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "document_title": document.title if document else "Unknown",
                        "text": chunk.text,
                        "score": result["score"],
                        "metadata": {
                            "page_num": chunk.page_num,
                            "timestamp": chunk.ts_start,
                            "section": chunk.meta_json.get("section") if chunk.meta_json else None
                        }
                    })
            
            logger.info(f"Found {len(results)} similar chunks for query")
            return results
            
        except Exception as e:
            logger.error(f"Failed to search similar chunks: {e}")
            raise
    
    def get_embedding_stats(self, db: Session) -> Dict[str, Any]:
        """Get statistics about embeddings in the database.
        
        Args:
            db: Database session
            
        Returns:
            Dictionary with embedding statistics
        """
        try:
            total_embeddings = db.query(Embedding).count()
            total_chunks = db.query(Chunk).count()
            total_documents = db.query(Document).filter(
                Document.status == "ready"
            ).count()
            
            # Count embeddings per document
            from sqlalchemy import func
            embeddings_per_doc = db.query(
                Document.id,
                Document.title,
                func.count(Embedding.id).label("embedding_count")
            ).join(
                Chunk, Document.id == Chunk.document_id
            ).outerjoin(
                Embedding, Chunk.id == Embedding.chunk_id
            ).group_by(Document.id).all()
            
            return {
                "total_embeddings": total_embeddings,
                "total_chunks": total_chunks,
                "total_documents": total_documents,
                "coverage": f"{(total_embeddings / total_chunks * 100):.1f}%" if total_chunks > 0 else "0%",
                "model": settings.emb_model_name,
                "dimension": settings.emb_dimension,
                "documents": [
                    {
                        "id": doc_id,
                        "title": title,
                        "embeddings": count
                    }
                    for doc_id, title, count in embeddings_per_doc
                ]
            }
            
        except Exception as e:
            logger.error(f"Failed to get embedding stats: {e}")
            raise
