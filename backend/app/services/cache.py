"""Bounded cache service for query results, embeddings, and document chunks."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import fnmatch
from itertools import islice
import json
import pickle
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional

import numpy as np
import structlog

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False

from app.config import get_settings

logger = structlog.get_logger()

_CONFIGURED_VALUE = object()
CACHE_SCAN_BATCH_SIZE = 100
MEMORY_CLEANUP_BATCH_SIZE = 64


@dataclass(frozen=True)
class _MemoryEntry:
    """One in-process value and the monotonic instant when it expires."""

    value: Any
    expires_at: Optional[float]


class CacheService:
    """Cache values in namespaced Redis or a bounded in-process LRU store."""

    def __init__(
        self,
        redis_url: object = _CONFIGURED_VALUE,
        namespace: Optional[str] = None,
        max_entries: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
        redis_client: Any = None,
    ) -> None:
        """Initialize one cache backend.

        Args:
            redis_url: Redis URL override. Omit it to read current application
                settings; pass ``None`` to force the memory backend.
            namespace: Prefix isolating this application's logical keys.
            max_entries: Maximum number of in-process entries.
            clock: Monotonic clock used for in-process expiry metadata.
            redis_client: Prebuilt Redis-compatible client, primarily for
                controlled integrations and tests.

        Returns:
            None.
        """
        configured = get_settings()
        selected_redis_url = (
            configured.redis_url
            if redis_url is _CONFIGURED_VALUE
            else redis_url
        )
        self.namespace = (
            namespace
            if namespace is not None
            else configured.cache_namespace
        )
        self.max_entries = (
            max_entries
            if max_entries is not None
            else configured.cache_max_entries
        )
        if not self.namespace.strip():
            raise ValueError("cache namespace must not be blank")
        if self.max_entries < 1:
            raise ValueError("cache max entries must be at least 1")

        self._clock = clock
        self._lock = threading.RLock()
        self.cache_backend = redis_client
        self.in_memory_cache: OrderedDict[str, _MemoryEntry] = OrderedDict()
        self.cache_stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
        }

        if self.cache_backend is not None:
            self._verify_redis_or_fallback()
        elif selected_redis_url:
            self._connect_redis(str(selected_redis_url))
        else:
            logger.info("Using bounded in-memory cache")

    def _connect_redis(self, redis_url: str) -> None:
        """Connect to configured Redis, falling back if it is unavailable."""
        if not REDIS_AVAILABLE:
            logger.warning("Redis configured but client package is unavailable")
            return

        try:
            self.cache_backend = redis.Redis.from_url(
                redis_url,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            self._verify_redis_or_fallback()
        except Exception as error:
            logger.warning(
                "Failed to connect to Redis, using bounded in-memory cache",
                error=str(error),
            )
            self.cache_backend = None

    def _verify_redis_or_fallback(self) -> None:
        """Verify an injected or configured Redis client before using it."""
        try:
            self.cache_backend.ping()
            logger.info("Connected to Redis cache", namespace=self.namespace)
        except Exception as error:
            logger.warning(
                "Failed to connect to Redis, using bounded in-memory cache",
                error=str(error),
            )
            self.cache_backend = None

    def _namespaced_key(self, key: str) -> str:
        """Prefix one logical cache key with the application namespace."""
        return f"{self.namespace}:{key}"

    def _namespaced_pattern(self, pattern: str) -> str:
        """Prefix one internal invalidation pattern with the namespace."""
        return f"{self.namespace}:{pattern}"

    def _get_key(self, prefix: str, key: str) -> str:
        """Build a logical key from a resource prefix and value."""
        return f"{prefix}:{key}"

    def _serialize(self, value: Any) -> bytes:
        """Serialize one value for Redis storage."""
        if isinstance(value, np.ndarray):
            return pickle.dumps(value)
        if isinstance(value, (dict, list)):
            return json.dumps(value).encode("utf-8")
        return pickle.dumps(value)

    def _deserialize(self, data: bytes, data_type: str = "auto") -> Any:
        """Deserialize one value read from Redis."""
        if data_type == "numpy":
            return pickle.loads(data)
        if data_type == "json":
            return json.loads(data.decode("utf-8"))
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return pickle.loads(data)

    def _increment_stat(self, name: str, amount: int = 1) -> None:
        """Update a counter without losing increments under concurrency."""
        with self._lock:
            self.cache_stats[name] += amount

    @staticmethod
    def _expiry(clock: Callable[[], float], ttl: Optional[int]) -> Optional[float]:
        """Turn a positive TTL into a monotonic deadline."""
        if ttl is None:
            return None
        if ttl <= 0:
            raise ValueError("cache TTL must be positive")
        return clock() + ttl

    def _cleanup_expired_locked(self, now: float) -> int:
        """Remove only a bounded sample of expired in-process entries."""
        deleted = 0
        for key in list(islice(
            self.in_memory_cache,
            MEMORY_CLEANUP_BATCH_SIZE,
        )):
            entry = self.in_memory_cache.get(key)
            if entry is not None and (
                entry.expires_at is not None and now >= entry.expires_at
            ):
                del self.in_memory_cache[key]
                deleted += 1
        if deleted:
            self.cache_stats["deletes"] += deleted
        return deleted

    def get(self, key: str, data_type: str = "auto") -> Optional[Any]:
        """Return a cached value when it exists and has not expired.

        Args:
            key: Logical cache key without the application namespace.
            data_type: Redis deserialization hint: ``auto``, ``json``, or
                ``numpy``.

        Returns:
            The cached value, or ``None`` for a miss or backend error.
        """
        namespaced_key = self._namespaced_key(key)
        try:
            if self.cache_backend is not None:
                data = self.cache_backend.get(namespaced_key)
                if data is not None:
                    self._increment_stat("hits")
                    return self._deserialize(data, data_type)
            else:
                now = self._clock()
                with self._lock:
                    self._cleanup_expired_locked(now)
                    entry = self.in_memory_cache.get(namespaced_key)
                    if entry is not None and (
                        entry.expires_at is None or now < entry.expires_at
                    ):
                        self.in_memory_cache.move_to_end(namespaced_key)
                        self.cache_stats["hits"] += 1
                        return entry.value
                    if entry is not None:
                        del self.in_memory_cache[namespaced_key]
                        self.cache_stats["deletes"] += 1

            self._increment_stat("misses")
            return None
        except Exception as error:
            logger.error("Cache get error", error=str(error))
            self._increment_stat("misses")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Store a value with an optional positive TTL.

        Args:
            key: Logical cache key without the application namespace.
            value: Value to cache.
            ttl: Positive lifetime in seconds, or ``None`` for no expiry.

        Returns:
            True when the value was stored, otherwise False.
        """
        namespaced_key = self._namespaced_key(key)
        try:
            if self.cache_backend is not None:
                data = self._serialize(value)
                if ttl is not None:
                    self._expiry(self._clock, ttl)
                    self.cache_backend.setex(namespaced_key, ttl, data)
                else:
                    self.cache_backend.set(namespaced_key, data)
                self._increment_stat("sets")
                return True

            now = self._clock()
            expires_at = self._expiry(lambda: now, ttl)
            with self._lock:
                self._cleanup_expired_locked(now)
                self.in_memory_cache[namespaced_key] = _MemoryEntry(
                    value=value,
                    expires_at=expires_at,
                )
                self.in_memory_cache.move_to_end(namespaced_key)
                while len(self.in_memory_cache) > self.max_entries:
                    self.in_memory_cache.popitem(last=False)
                    self.cache_stats["deletes"] += 1
                self.cache_stats["sets"] += 1
            return True
        except Exception as error:
            logger.error("Cache set error", error=str(error))
            return False

    def delete(self, key: str) -> bool:
        """Delete one logical key.

        Args:
            key: Logical cache key without the application namespace.

        Returns:
            True when the backend operation completed, even if the key was
            already absent; False on a backend error.
        """
        namespaced_key = self._namespaced_key(key)
        try:
            if self.cache_backend is not None:
                deleted = int(self.cache_backend.delete(namespaced_key))
                self._increment_stat("deletes", deleted)
            else:
                with self._lock:
                    deleted = int(self.in_memory_cache.pop(namespaced_key, None) is not None)
                    self.cache_stats["deletes"] += deleted
            return True
        except Exception as error:
            logger.error("Cache delete error", error=str(error))
            return False

    def _redis_keys(self, pattern: str) -> Iterator[Any]:
        """Yield Redis keys matching one already-namespaced pattern."""
        yield from self.cache_backend.scan_iter(
            match=pattern,
            count=CACHE_SCAN_BATCH_SIZE,
        )

    def _delete_pattern(self, pattern: str) -> int:
        """Delete one internal, namespaced resource pattern in bounded batches."""
        namespaced_pattern = self._namespaced_pattern(pattern)
        if self.cache_backend is not None:
            deleted = 0
            batch: List[str] = []
            for key in self._redis_keys(namespaced_pattern):
                batch.append(key)
                if len(batch) == CACHE_SCAN_BATCH_SIZE:
                    deleted += int(self.cache_backend.delete(*batch))
                    batch.clear()
            if batch:
                deleted += int(self.cache_backend.delete(*batch))
            self._increment_stat("deletes", deleted)
            return deleted

        with self._lock:
            keys = [
                key for key in self.in_memory_cache
                if fnmatch.fnmatchcase(key, namespaced_pattern)
            ]
            for key in keys:
                del self.in_memory_cache[key]
            self.cache_stats["deletes"] += len(keys)
            return len(keys)

    def cache_query_result(
        self,
        project_id: str,
        query: str,
        result: Dict[str, Any],
        ttl: int = 3600,
    ) -> bool:
        """Cache a project-scoped query result.

        Args:
            project_id: Owning project id.
            query: Query text.
            result: Query response data.
            ttl: Lifetime in seconds.

        Returns:
            True when stored.
        """
        key = self._get_key(f"query:{project_id}", query)
        return self.set(key, result, ttl)

    def get_cached_query(
        self,
        project_id: str,
        query: str,
    ) -> Optional[Dict[str, Any]]:
        """Return a project-scoped cached query result.

        Args:
            project_id: Owning project id.
            query: Query text.

        Returns:
            Cached response data, or None.
        """
        key = self._get_key(f"query:{project_id}", query)
        return self.get(key, data_type="json")

    def cache_embedding(
        self,
        document_id: str,
        chunk_id: str,
        embedding: np.ndarray,
        ttl: int = 7200,
    ) -> bool:
        """Cache a document-scoped embedding vector.

        Args:
            document_id: Owning document id.
            chunk_id: Chunk id or stable content key.
            embedding: Vector to cache.
            ttl: Lifetime in seconds.

        Returns:
            True when stored.
        """
        key = self._get_key(f"embedding:{document_id}", chunk_id)
        return self.set(key, embedding, ttl)

    def get_cached_embedding(
        self,
        document_id: str,
        chunk_id: str,
    ) -> Optional[np.ndarray]:
        """Return a document-scoped cached embedding.

        Args:
            document_id: Owning document id.
            chunk_id: Chunk id or stable content key.

        Returns:
            Cached numpy vector, or None.
        """
        key = self._get_key(f"embedding:{document_id}", chunk_id)
        return self.get(key, data_type="numpy")

    def cache_chunk(
        self,
        document_id: str,
        chunk_id: str,
        chunk_data: Dict[str, Any],
        ttl: int = 7200,
    ) -> bool:
        """Cache document-scoped chunk data.

        Args:
            document_id: Owning document id.
            chunk_id: Chunk id.
            chunk_data: Chunk payload.
            ttl: Lifetime in seconds.

        Returns:
            True when stored.
        """
        key = self._get_key(f"chunk:{document_id}", chunk_id)
        return self.set(key, chunk_data, ttl)

    def get_cached_chunk(
        self,
        document_id: str,
        chunk_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return document-scoped chunk data.

        Args:
            document_id: Owning document id.
            chunk_id: Chunk id.

        Returns:
            Cached chunk payload, or None.
        """
        key = self._get_key(f"chunk:{document_id}", chunk_id)
        return self.get(key, data_type="json")

    def invalidate_project_cache(self, project_id: str) -> int:
        """Invalidate query results for one project.

        Args:
            project_id: Owned project id.

        Returns:
            Number of entries actually deleted.
        """
        return self._delete_pattern(f"query:{project_id}:*")

    def invalidate_document_cache(self, document_id: str) -> int:
        """Invalidate cached chunks and embeddings for one document.

        Args:
            document_id: Owned document id.

        Returns:
            Number of entries actually deleted.
        """
        return sum(
            self._delete_pattern(pattern)
            for pattern in (
                f"embedding:{document_id}:*",
                f"chunk:{document_id}:*",
            )
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return internal cache counters and backend data.

        Args:
            None.

        Returns:
            Cache statistics for operational diagnostics.
        """
        if self.cache_backend is not None:
            with self._lock:
                stats = self.cache_stats.copy()
            try:
                info = self.cache_backend.info()
                stats.update({
                    "backend": "redis",
                    "used_memory": info.get("used_memory_human", "N/A"),
                    "total_keys": sum(
                        1 for _key in self._redis_keys(
                            self._namespaced_pattern("*")
                        )
                    ),
                    "connected_clients": info.get("connected_clients", 0),
                })
            except Exception:
                stats.update({"backend": "redis (error)", "total_keys": 0})
        else:
            with self._lock:
                self._cleanup_expired_locked(self._clock())
                stats = self.cache_stats.copy()
                stats.update({
                    "backend": "in-memory",
                    "total_keys": len(self.in_memory_cache),
                })

        total_requests = stats["hits"] + stats["misses"]
        stats["hit_rate"] = (
            f"{(stats['hits'] / total_requests * 100):.1f}%"
            if total_requests
            else "N/A"
        )
        return stats

    def health_check(self) -> Dict[str, Any]:
        """Return internal cache connectivity state.

        Args:
            None.

        Returns:
            Backend name and healthy or degraded status.
        """
        if self.cache_backend is not None:
            try:
                self.cache_backend.ping()
                return {"status": "healthy", "backend": "redis"}
            except Exception as error:
                return {
                    "status": "degraded",
                    "backend": "redis",
                    "error": str(error),
                }
        return {"status": "healthy", "backend": "in-memory"}


cache_service = CacheService()
