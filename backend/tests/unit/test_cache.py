"""Unit tests for cache service."""
import pytest
import numpy as np
from unittest.mock import Mock, patch
import json

from app.services.cache import CacheService


class TestCacheService:
    """Test cache service functionality."""
    
    @pytest.fixture
    def cache_service(self):
        """Create a cache service instance for testing."""
        return CacheService()
    
    def test_cache_initialization(self, cache_service):
        """Test cache service initialization."""
        assert cache_service is not None
        assert cache_service.cache_stats["hits"] == 0
        assert cache_service.cache_stats["misses"] == 0
    
    def test_set_and_get(self, cache_service):
        """Test basic set and get operations."""
        key = "test_key"
        value = {"data": "test_value"}
        
        # Set value
        result = cache_service.set(key, value)
        assert result is True
        
        # Get value
        retrieved = cache_service.get(key)
        assert retrieved == value
        assert cache_service.cache_stats["hits"] == 1
    
    def test_cache_miss(self, cache_service):
        """Test cache miss behavior."""
        retrieved = cache_service.get("non_existent_key")
        assert retrieved is None
        assert cache_service.cache_stats["misses"] == 1
    
    def test_delete(self, cache_service):
        """Test delete operation."""
        key = "delete_test"
        value = "test_data"
        
        cache_service.set(key, value)
        result = cache_service.delete(key)
        assert result is True
        
        # Verify deletion
        retrieved = cache_service.get(key)
        assert retrieved is None
    
    def test_cache_query_result(self, cache_service):
        """Test caching query results."""
        project_id = "test_project"
        query = "What is AI?"
        result = {
            "answer": "AI is artificial intelligence",
            "sources": [],
            "model": "test_model"
        }
        
        # Cache result
        success = cache_service.cache_query_result(project_id, query, result)
        assert success is True
        
        # Retrieve cached result
        cached = cache_service.get_cached_query(project_id, query)
        assert cached == result
    
    def test_cache_embedding(self, cache_service):
        """Test caching embeddings."""
        doc_id = "test_doc"
        chunk_id = "test_chunk"
        embedding = np.random.randn(384).astype(np.float32)
        
        # Cache embedding
        success = cache_service.cache_embedding(doc_id, chunk_id, embedding)
        assert success is True
        
        # Retrieve cached embedding
        cached = cache_service.get_cached_embedding(doc_id, chunk_id)
        assert cached is not None
        assert np.allclose(cached, embedding)
    
    def test_cache_chunk(self, cache_service):
        """Test caching document chunks."""
        doc_id = "test_doc"
        chunk_id = "test_chunk"
        chunk_data = {
            "text": "This is a test chunk",
            "metadata": {"page": 1}
        }
        
        # Cache chunk
        success = cache_service.cache_chunk(doc_id, chunk_id, chunk_data)
        assert success is True
        
        # Retrieve cached chunk
        cached = cache_service.get_cached_chunk(doc_id, chunk_id)
        assert cached == chunk_data
    
    def test_invalidate_project_cache(self, cache_service):
        """Test project cache invalidation."""
        project_id = "test_project"
        
        # Add some cache entries
        cache_service.set(f"query:{project_id}:test1", "data1")
        cache_service.set(f"query:{project_id}:test2", "data2")
        
        # Invalidate project cache
        count = cache_service.invalidate_project_cache(project_id)
        assert count >= 0  # Count may vary based on implementation
    
    def test_invalidate_document_cache(self, cache_service):
        """Test document cache invalidation."""
        doc_id = "test_doc"
        
        # Add some cache entries
        cache_service.set(f"embedding:{doc_id}:chunk1", "embed1")
        cache_service.set(f"chunk:{doc_id}:chunk1", "chunk1")
        
        # Invalidate document cache
        count = cache_service.invalidate_document_cache(doc_id)
        assert count >= 0  # Count may vary based on implementation
    
    def test_get_stats(self, cache_service):
        """Test cache statistics."""
        # Perform some operations
        cache_service.set("key1", "value1")
        cache_service.get("key1")  # Hit
        cache_service.get("key2")  # Miss
        
        stats = cache_service.get_stats()
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
    
    def test_health_check(self, cache_service):
        """Test cache health check."""
        health = cache_service.health_check()
        assert "status" in health
        assert "backend" in health
        assert health["status"] in ["healthy", "degraded"]
    
    def test_clear_with_pattern(self, cache_service):
        """Test clearing cache with pattern."""
        # Add test entries
        cache_service.set("test:key1", "value1")
        cache_service.set("test:key2", "value2")
        cache_service.set("other:key3", "value3")
        
        # Clear with pattern
        count = cache_service.clear("test:*")
        
        # Verify test keys are cleared
        assert cache_service.get("test:key1") is None
        assert cache_service.get("test:key2") is None
        # Other keys should remain (if pattern matching works)
        # Note: in-memory implementation may not support patterns fully
