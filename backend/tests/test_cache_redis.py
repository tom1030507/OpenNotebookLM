"""Real Redis contract for versioned, ownership-scoped cache invalidation."""
from __future__ import annotations

import os
import uuid

import numpy as np
import pytest

from app.services.cache import CACHE_INVALIDATION_SCOPE_COUNT, CacheService


def test_real_redis_document_version_invalidation_is_scoped() -> None:
    """A real server must make stale values unreachable without flushing peers."""
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is not configured")

    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(redis_url, decode_responses=False)
    namespace = f"cache-contract-{uuid.uuid4().hex}"
    service = CacheService(
        redis_url=redis_url,
        redis_client=client,
        namespace=namespace,
        max_entries=10,
    )
    peer_key = f"peer:{namespace}:sentinel"
    client.set(peer_key, b"keep")

    assert service.cache_embedding("document", "chunk", np.array([1.0]))
    assert service.cache_chunk("other-document", "chunk", {"text": "keep"})
    version_key = f"{namespace}:version:document:document"
    old_version = client.get(version_key).decode("utf-8")
    old_value_key = f"{namespace}:embedding:document:{old_version}:chunk"

    invalidated = service.invalidate_document_cache("document")

    assert invalidated == CACHE_INVALIDATION_SCOPE_COUNT
    assert service.get_cached_embedding("document", "chunk") is None
    assert service.get_cached_chunk("other-document", "chunk") == {"text": "keep"}
    assert client.get(peer_key) == b"keep"
    # Rotation is logical invalidation: the TTL value remains physical but is
    # no longer addressable through the current document version.
    assert client.exists(old_value_key) == 1

    new_version = client.get(version_key).decode("utf-8")
    other_version_key = f"{namespace}:version:document:other-document"
    other_version = client.get(other_version_key).decode("utf-8")
    client.delete(
        peer_key,
        version_key,
        other_version_key,
        old_value_key,
        f"{namespace}:embedding:document:{new_version}:chunk",
        f"{namespace}:chunk:other-document:{other_version}:chunk",
    )
