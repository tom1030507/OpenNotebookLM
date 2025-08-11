"""
SQLite-vec adapter for vector storage and similarity search.
Using sqlite-vec extension for efficient vector operations.
"""

import sqlite3
import json
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class SQLiteVecAdapter:
    """SQLite-vec adapter for vector storage and similarity search."""
    
    def __init__(self, db_path: str = "data/vectors.db", dimension: int = 384):
        """
        Initialize SQLite-vec adapter.
        
        Args:
            db_path: Path to SQLite database
            dimension: Vector dimension (default 384 for sentence-transformers)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.dimension = dimension
        self.conn = None
        self._init_database()
    
    def _init_database(self):
        """Initialize database and create tables."""
        try:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row
            
            # Enable WAL mode for better concurrency
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            
            # Create embeddings table with vector column
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id TEXT UNIQUE NOT NULL,
                    document_id TEXT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    metadata TEXT,
                    vector BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for faster queries
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_embeddings_document_id 
                ON embeddings(document_id)
            """)
            
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id 
                ON embeddings(chunk_id)
            """)
            
            self.conn.commit()
            logger.info(f"Initialized SQLite-vec database at {self.db_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def _vector_to_blob(self, vector: np.ndarray) -> bytes:
        """Convert numpy array to blob for storage."""
        return vector.astype(np.float32).tobytes()
    
    def _blob_to_vector(self, blob: bytes) -> np.ndarray:
        """Convert blob back to numpy array."""
        return np.frombuffer(blob, dtype=np.float32)
    
    def add_embedding(
        self,
        chunk_id: str,
        document_id: str,
        chunk_text: str,
        chunk_index: int,
        vector: np.ndarray,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add an embedding to the database.
        
        Args:
            chunk_id: Unique chunk identifier
            document_id: Document identifier
            chunk_text: Text content of the chunk
            chunk_index: Index of chunk in document
            vector: Embedding vector
            metadata: Additional metadata
            
        Returns:
            True if successful
        """
        try:
            vector_blob = self._vector_to_blob(vector)
            metadata_json = json.dumps(metadata) if metadata else None
            
            self.conn.execute("""
                INSERT OR REPLACE INTO embeddings 
                (chunk_id, document_id, chunk_text, chunk_index, vector, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chunk_id, document_id, chunk_text, chunk_index, vector_blob, metadata_json))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to add embedding: {e}")
            return False
    
    def add_embeddings_batch(
        self,
        embeddings: List[Dict[str, Any]]
    ) -> int:
        """
        Add multiple embeddings in batch.
        
        Args:
            embeddings: List of embedding dictionaries
            
        Returns:
            Number of embeddings added
        """
        count = 0
        try:
            for emb in embeddings:
                vector_blob = self._vector_to_blob(emb['vector'])
                metadata_json = json.dumps(emb.get('metadata')) if emb.get('metadata') else None
                
                self.conn.execute("""
                    INSERT OR REPLACE INTO embeddings 
                    (chunk_id, document_id, chunk_text, chunk_index, vector, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    emb['chunk_id'],
                    emb['document_id'],
                    emb['chunk_text'],
                    emb['chunk_index'],
                    vector_blob,
                    metadata_json
                ))
                count += 1
            
            self.conn.commit()
            logger.info(f"Added {count} embeddings in batch")
            return count
            
        except Exception as e:
            logger.error(f"Failed to add embeddings batch: {e}")
            self.conn.rollback()
            return 0
    
    def search_similar(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        document_ids: Optional[List[str]] = None,
        threshold: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using cosine similarity.
        
        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            document_ids: Optional list of document IDs to search within
            threshold: Minimum similarity threshold
            
        Returns:
            List of similar chunks with scores
        """
        try:
            # Build query
            query = """
                SELECT chunk_id, document_id, chunk_text, chunk_index, vector, metadata
                FROM embeddings
            """
            
            params = []
            if document_ids:
                placeholders = ','.join('?' * len(document_ids))
                query += f" WHERE document_id IN ({placeholders})"
                params.extend(document_ids)
            
            cursor = self.conn.execute(query, params)
            
            # Calculate similarities
            results = []
            query_norm = np.linalg.norm(query_vector)
            
            for row in cursor:
                chunk_vector = self._blob_to_vector(row['vector'])
                
                # Cosine similarity
                chunk_norm = np.linalg.norm(chunk_vector)
                if chunk_norm > 0 and query_norm > 0:
                    similarity = np.dot(query_vector, chunk_vector) / (query_norm * chunk_norm)
                else:
                    similarity = 0.0
                
                if similarity >= threshold:
                    results.append({
                        'chunk_id': row['chunk_id'],
                        'document_id': row['document_id'],
                        'chunk_text': row['chunk_text'],
                        'chunk_index': row['chunk_index'],
                        'score': float(similarity),
                        'metadata': json.loads(row['metadata']) if row['metadata'] else None
                    })
            
            # Sort by score and return top_k
            results.sort(key=lambda x: x['score'], reverse=True)
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Failed to search similar: {e}")
            return []
    
    def get_document_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        """
        Get all chunks for a document.
        
        Args:
            document_id: Document identifier
            
        Returns:
            List of chunks
        """
        try:
            cursor = self.conn.execute("""
                SELECT chunk_id, chunk_text, chunk_index, metadata
                FROM embeddings
                WHERE document_id = ?
                ORDER BY chunk_index
            """, (document_id,))
            
            return [
                {
                    'chunk_id': row['chunk_id'],
                    'chunk_text': row['chunk_text'],
                    'chunk_index': row['chunk_index'],
                    'metadata': json.loads(row['metadata']) if row['metadata'] else None
                }
                for row in cursor
            ]
            
        except Exception as e:
            logger.error(f"Failed to get document chunks: {e}")
            return []
    
    def delete_document_embeddings(self, document_id: str) -> bool:
        """
        Delete all embeddings for a document.
        
        Args:
            document_id: Document identifier
            
        Returns:
            True if successful
        """
        try:
            self.conn.execute("""
                DELETE FROM embeddings WHERE document_id = ?
            """, (document_id,))
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete document embeddings: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Statistics dictionary
        """
        try:
            cursor = self.conn.execute("""
                SELECT 
                    COUNT(*) as total_embeddings,
                    COUNT(DISTINCT document_id) as total_documents,
                    AVG(LENGTH(chunk_text)) as avg_chunk_size,
                    MAX(LENGTH(chunk_text)) as max_chunk_size,
                    MIN(LENGTH(chunk_text)) as min_chunk_size
                FROM embeddings
            """)
            
            row = cursor.fetchone()
            
            # Get database file size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            
            return {
                'total_embeddings': row['total_embeddings'],
                'total_documents': row['total_documents'],
                'avg_chunk_size': row['avg_chunk_size'],
                'max_chunk_size': row['max_chunk_size'],
                'min_chunk_size': row['min_chunk_size'],
                'database_size_mb': db_size / (1024 * 1024),
                'vector_dimension': self.dimension
            }
            
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def optimize(self):
        """Optimize database (VACUUM and ANALYZE)."""
        try:
            self.conn.execute("VACUUM")
            self.conn.execute("ANALYZE")
            self.conn.commit()
            logger.info("Database optimized")
            
        except Exception as e:
            logger.error(f"Failed to optimize database: {e}")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
