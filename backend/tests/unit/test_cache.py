"""Focused tests for bounded memory and Redis cache behavior."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import fnmatch
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from app.config import get_settings
import app.services.cache as cache_module
from app.services.cache import CacheService


class FakeClock:
    """A manually advanced monotonic clock."""

    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeRedis:
    """Small Redis-compatible store that preserves delete-count semantics."""

    def __init__(self, clock: FakeClock | None = None):
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.expires_at: dict[str, float] = {}
        self.setex_calls: list[tuple[str, int, bytes]] = []
        self.clock = clock

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> bytes | None:
        if (
            self.clock is not None
            and key in self.expires_at
            and self.clock() >= self.expires_at[key]
        ):
            self.delete(key)
        return self.values.get(key)

    def set(self, key: str, value: bytes) -> bool:
        self.values[key] = value
        self.ttls.pop(key, None)
        self.expires_at.pop(key, None)
        return True

    def setex(self, key: str, ttl: int, value: bytes) -> bool:
        self.values[key] = value
        self.ttls[key] = ttl
        if self.clock is not None:
            self.expires_at[key] = self.clock() + ttl
        self.setex_calls.append((key, ttl, value))
        return True

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                del self.values[key]
                self.ttls.pop(key, None)
                self.expires_at.pop(key, None)
        return deleted

    def scan_iter(self, match: str, count: int):
        del count
        return iter([
            key for key in list(self.values)
            if fnmatch.fnmatch(key, match)
        ])

    def info(self) -> dict[str, object]:
        return {"used_memory_human": "1K", "connected_clients": 1}

    def dbsize(self) -> int:
        return len(self.values)

    def flushdb(self) -> None:
        raise AssertionError("resource-scoped invalidation must never flush Redis")


class CountingOrderedDict(OrderedDict):
    """Ordered mapping that records cleanup's iteration work."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visited = 0

    def __iter__(self):
        for key in super().__iter__():
            self.visited += 1
            yield key


@pytest.fixture
def memory_cache() -> CacheService:
    """Return an explicitly configured memory cache."""
    return CacheService(redis_url=None, namespace="test-app", max_entries=100)


def test_memory_ttl_expires_at_the_exact_boundary() -> None:
    """Using ``>`` instead of ``>=`` would retain an already-expired entry."""
    clock = FakeClock()
    service = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=10,
        clock=clock,
    )

    assert service.set("answer", {"value": 1}, ttl=5)
    clock.advance(5)

    assert service.get("answer") is None
    assert service.get_stats()["total_keys"] == 0


def test_refreshing_a_key_replaces_its_old_expiry() -> None:
    """An old TTL must not delete a newer value written under the same key."""
    clock = FakeClock()
    service = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=10,
        clock=clock,
    )

    assert service.set("answer", "old", ttl=5)
    clock.advance(4)
    assert service.set("answer", "new", ttl=5)
    clock.advance(2)

    assert service.get("answer") == "new"


def test_five_thousand_ttl_sets_never_start_a_per_entry_thread(monkeypatch) -> None:
    """The former timer-per-key design attempted one OS thread per set."""
    started = 0

    def reject_thread_start(_thread: threading.Thread) -> None:
        nonlocal started
        started += 1
        raise AssertionError("cache entries must not own threads")

    monkeypatch.setattr(threading.Thread, "start", reject_thread_start)
    service = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=5_000,
    )

    assert all(service.set(f"key-{index}", index, ttl=60) for index in range(5_000))
    assert started == 0


def test_memory_cache_evicts_the_least_recently_used_entry() -> None:
    """A fourth attacker-controlled key cannot grow a three-entry cache."""
    service = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=3,
    )
    for key in ("oldest", "middle", "newest"):
        assert service.set(key, key)
    assert service.get("oldest") == "oldest"

    assert service.set("attacker-key", "value")

    assert service.get("middle") is None
    assert service.get("oldest") == "oldest"
    assert service.get_stats()["total_keys"] == 3


def test_lazy_expiry_cleanup_inspects_only_a_bounded_batch() -> None:
    """A set must not scan every attacker-controlled key for expired entries."""
    service = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=1_001,
    )
    for index in range(1_000):
        assert service.set(f"key-{index}", index, ttl=60)
    counted = CountingOrderedDict(service.in_memory_cache)
    service.in_memory_cache = counted
    counted.visited = 0

    assert service.set("one-more", "value", ttl=60)

    assert counted.visited <= cache_module.MEMORY_CLEANUP_BATCH_SIZE


def test_concurrent_gets_and_sets_keep_size_and_stats_consistent() -> None:
    """Unsynchronised eviction or counters would lose work under contention."""
    service = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=64,
    )

    def exercise(worker: int) -> None:
        for index in range(100):
            key = f"{worker}:{index}"
            assert service.set(key, index, ttl=60)
            service.get(key)

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(exercise, range(16)))

    stats = service.get_stats()
    assert stats["sets"] == 1_600
    assert stats["hits"] + stats["misses"] == 1_600
    assert stats["total_keys"] <= 64


def test_basic_memory_values_and_high_level_helpers(memory_cache: CacheService) -> None:
    """Bounding the cache must preserve JSON, numpy, and deletion behavior."""
    query_result = {"answer": "AI", "sources": []}
    embedding = np.array([0.1, 0.2], dtype=np.float32)

    assert memory_cache.cache_query_result("project", "question", query_result)
    assert memory_cache.get_cached_query("project", "question") == query_result
    assert memory_cache.cache_embedding("document", "chunk", embedding)
    assert np.allclose(
        memory_cache.get_cached_embedding("document", "chunk"),
        embedding,
    )
    assert memory_cache.delete("query:project:question")
    assert memory_cache.get_cached_query("project", "question") is None


def test_configured_redis_url_is_read_when_each_service_is_created(monkeypatch) -> None:
    """A module-import settings snapshot made REDIS_URL permanently unreachable."""
    fake_redis = FakeRedis()
    from_url = Mock(return_value=fake_redis)
    monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6379/0")
    get_settings.cache_clear()
    monkeypatch.setattr(cache_module, "REDIS_AVAILABLE", True)
    monkeypatch.setattr(
        cache_module,
        "redis",
        SimpleNamespace(Redis=SimpleNamespace(from_url=from_url)),
        raising=False,
    )

    try:
        service = CacheService(namespace="test-app", max_entries=10)
    finally:
        get_settings.cache_clear()

    from_url.assert_called_once_with(
        "redis://cache.internal:6379/0",
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    assert service.health_check() == {"status": "healthy", "backend": "redis"}


def test_redis_and_memory_apply_the_same_namespace_and_ttl() -> None:
    """Backend selection must not change the logical key or requested TTL."""
    clock = FakeClock()
    redis_backend = FakeRedis(clock)
    redis_cache = CacheService(
        redis_url="redis://unused",
        redis_client=redis_backend,
        namespace="test-app",
        max_entries=10,
        clock=clock,
    )
    memory = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=10,
        clock=clock,
    )

    assert redis_cache.set("query:project:question", {"answer": "redis"}, ttl=37)
    assert memory.set("query:project:question", {"answer": "memory"}, ttl=37)

    assert redis_backend.setex_calls[0][:2] == (
        "test-app:query:project:question",
        37,
    )
    assert list(memory.in_memory_cache) == ["test-app:query:project:question"]
    assert redis_cache.get("query:project:question") == {"answer": "redis"}
    assert memory.get("query:project:question") == {"answer": "memory"}

    clock.advance(37)

    assert redis_cache.get("query:project:question") is None
    assert memory.get("query:project:question") is None


def test_redis_namespaces_isolate_identical_logical_keys() -> None:
    """Two applications sharing Redis cannot overwrite one another's key."""
    redis_backend = FakeRedis()
    first = CacheService(
        redis_url="redis://unused",
        redis_client=redis_backend,
        namespace="first-app",
        max_entries=10,
    )
    second = CacheService(
        redis_url="redis://unused",
        redis_client=redis_backend,
        namespace="second-app",
        max_entries=10,
    )

    assert first.set("shared", "first", ttl=10)
    assert second.set("shared", "second", ttl=10)

    assert first.get("shared") == "first"
    assert second.get("shared") == "second"


def test_redis_document_invalidation_counts_actual_deletes_and_keeps_sentinels() -> None:
    """Counting SCAN results or flushing the DB would over-report or erase peers."""
    redis_backend = FakeRedis()
    service = CacheService(
        redis_url="redis://unused",
        redis_client=redis_backend,
        namespace="test-app",
        max_entries=10,
    )
    assert service.cache_embedding("document", "one", np.array([1.0]))
    assert service.cache_chunk("document", "two", {"text": "two"})
    assert service.cache_chunk("other-document", "three", {"text": "three"})
    redis_backend.values["other-app:chunk:document:sentinel"] = b"sentinel"

    deleted = service.invalidate_document_cache("document")

    assert deleted == 2
    assert "test-app:chunk:other-document:three" in redis_backend.values
    assert "other-app:chunk:document:sentinel" in redis_backend.values
    assert service.get_stats()["deletes"] == 2


def test_memory_project_invalidation_is_scoped_to_the_named_project() -> None:
    """Project invalidation must preserve other projects in the same process."""
    service = CacheService(
        redis_url=None,
        namespace="test-app",
        max_entries=10,
    )
    assert service.cache_query_result("project-one", "q", {"answer": 1})
    assert service.cache_query_result("project-two", "q", {"answer": 2})

    assert service.invalidate_project_cache("project-one") == 1
    assert service.get_cached_query("project-one", "q") is None
    assert service.get_cached_query("project-two", "q") == {"answer": 2}
