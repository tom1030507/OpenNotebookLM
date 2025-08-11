"""Cache service for query results, embeddings, and document chunks."""
import json
import pickle
import hashlib
import time
from typing import Dict, Any, Optional, List
import numpy as np
import structlog

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class CacheService:
    """Service for caching query results, embeddings, and chunks."""
    
    def __init__(self):
        """Initialize cache service."""
        self.cache_backend = None
        self.in_memory_cache = {}
        self.cache_stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0
        }
        
        # Try to connect to Redis if available
        if REDIS_AVAILABLE and hasattr(settings, 'redis_url'):
            try:
                self.cache_backend = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=False,  # We'll handle encoding/decoding
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                # Test connection
                self.cache_backend.ping()
                logger.info("Connected to Redis cache")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis, using in-memory cache: {e}")
                self.cache_backend = None
        else:
            logger.info("Using in-memory cache (Redis not available)")
    
    def _get_key(self, prefix: str, key: str) -> str:
        """Generate a cache key with prefix."""
        return f"{prefix}:{key}"
    
    def _serialize(self, value: Any) -> bytes:
        """Serialize value for storage."""
        if isinstance(value, np.ndarray):
            return pickle.dumps(value)
        elif isinstance(value, (dict, list)):
            return json.dumps(value).encode('utf-8')
        else:
            return pickle.dumps(value)
    
    def _deserialize(self, data: bytes, data_type: str = "auto") -> Any:
        """Deserialize value from storage."""
        if data_type == "numpy":
            return pickle.loads(data)
        elif data_type == "json":
            return json.loads(data.decode('utf-8'))
        else:
            # Try json first, then pickle
            try:
                return json.loads(data.decode('utf-8'))
            except:
                return pickle.loads(data)
    
    def get(self, key: str, data_type: str = "auto") -> Optional[Any]:
        """Get value from cache."""
        try:
            if self.cache_backend:
                data = self.cache_backend.get(key)
                if data:
                    self.cache_stats["hits"] += 1
                    return self._deserialize(data, data_type)
            else:
                if key in self.in_memory_cache:
                    self.cache_stats["hits"] += 1
                    return self.in_memory_cache[key]
            
            self.cache_stats["misses"] += 1
            return None
            
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            self.cache_stats["misses"] += 1
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL."""
        try:
            if self.cache_backend:
                data = self._serialize(value)
                if ttl:
                    self.cache_backend.setex(key, ttl, data)
                else:
                    self.cache_backend.set(key, data)
            else:
                self.in_memory_cache[key] = value
                # Simple TTL for in-memory cache
                if ttl:
                    self._schedule_deletion(key, ttl)
            
            self.cache_stats["sets"] += 1
            return True
            
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete value from cache."""
        try:
            if self.cache_backend:
                self.cache_backend.delete(key)
            else:
                self.in_memory_cache.pop(key, None)
            
            self.cache_stats["deletes"] += 1
            return True
            
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries matching pattern."""
        count = 0
        try:
            if self.cache_backend:
                if pattern:
                    # Use SCAN to find matching keys
                    cursor = 0
                    while True:
                        cursor, keys = self.cache_backend.scan(
                            cursor, match=pattern, count=100
                        )
                        if keys:
                            self.cache_backend.delete(*keys)
                            count += len(keys)
                        if cursor == 0:
                            break
                else:
                    # Clear all
                    self.cache_backend.flushdb()
                    count = -1  # Unknown count
            else:
                if pattern:
                    # Simple pattern matching for in-memory
                    import fnmatch
                    keys_to_delete = [
                        k for k in self.in_memory_cache.keys()
                        if fnmatch.fnmatch(k, pattern)
                    ]
                    for key in keys_to_delete:
                        del self.in_memory_cache[key]
                        count += 1
                else:
                    count = len(self.in_memory_cache)
                    self.in_memory_cache.clear()
            
            return count
            
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return 0
    
    def _schedule_deletion(self, key: str, ttl: int):
        """Schedule deletion for in-memory cache (simplified)."""
        # This is a simplified version - in production, use a proper scheduler
        import threading
        def delete_after_timeout():
            time.sleep(ttl)
            self.in_memory_cache.pop(key, None)
        
        thread = threading.Thread(target=delete_after_timeout, daemon=True)
        thread.start()
    
    # High-level caching methods
    
    def cache_query_result(
        self,
        project_id: str,
        query: str,
        result: Dict[str, Any],
        ttl: int = 3600
    ) -> bool:
        """Cache a query result."""
        key = self._get_key(f"query:{project_id}", query)
        return self.set(key, result, ttl)
    
    def get_cached_query(
        self,
        project_id: str,
        query: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached query result."""
        key = self._get_key(f"query:{project_id}", query)
        return self.get(key, data_type="json")
    
    def cache_embedding(
        self,
        document_id: str,
        chunk_id: str,
        embedding: np.ndarray,
        ttl: int = 7200
    ) -> bool:
        """Cache an embedding vector."""
        key = self._get_key(f"embedding:{document_id}", chunk_id)
        return self.set(key, embedding, ttl)
    
    def get_cached_embedding(
        self,
        document_id: str,
        chunk_id: str
    ) -> Optional[np.ndarray]:
        """Get cached embedding vector."""
        key = self._get_key(f"embedding:{document_id}", chunk_id)
        return self.get(key, data_type="numpy")
    
    def cache_chunk(
        self,
        document_id: str,
        chunk_id: str,
        chunk_data: Dict[str, Any],
        ttl: int = 7200
    ) -> bool:
        """Cache document chunk data."""
        key = self._get_key(f"chunk:{document_id}", chunk_id)
        return self.set(key, chunk_data, ttl)
    
    def get_cached_chunk(
        self,
        document_id: str,
        chunk_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached chunk data."""
        key = self._get_key(f"chunk:{document_id}", chunk_id)
        return self.get(key, data_type="json")
    
    def invalidate_project_cache(self, project_id: str) -> int:
        """Invalidate all cache entries for a project."""
        patterns = [
            f"query:{project_id}:*",
            f"*:project:{project_id}:*"
        ]
        total = 0
        for pattern in patterns:
            total += self.clear(pattern)
        return total
    
    def invalidate_document_cache(self, document_id: str) -> int:
        """Invalidate all cache entries for a document."""
        patterns = [
            f"embedding:{document_id}:*",
            f"chunk:{document_id}:*"
        ]
        total = 0
        for pattern in patterns:
            total += self.clear(pattern)
        return total
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        stats = self.cache_stats.copy()
        
        if self.cache_backend:
            try:
                info = self.cache_backend.info()
                stats.update({
                    "backend": "redis",
                    "used_memory": info.get("used_memory_human", "N/A"),
                    "total_keys": self.cache_backend.dbsize(),
                    "connected_clients": info.get("connected_clients", 0)
                })
            except:
                stats["backend"] = "redis (error)"
        else:
            stats.update({
                "backend": "in-memory",
                "total_keys": len(self.in_memory_cache)
            })
        
        # Calculate hit rate
        total_requests = stats["hits"] + stats["misses"]
        if total_requests > 0:
            stats["hit_rate"] = f"{(stats['hits'] / total_requests * 100):.1f}%"
        else:
            stats["hit_rate"] = "N/A"
        
        return stats
    
    def health_check(self) -> Dict[str, Any]:
        """Check cache health."""
        if self.cache_backend:
            try:
                self.cache_backend.ping()
                return {"status": "healthy", "backend": "redis"}
            except Exception as e:
                return {"status": "degraded", "backend": "redis", "error": str(e)}
        else:
            return {"status": "healthy", "backend": "in-memory"}


# Global cache service instance
cache_service = CacheService()
