"""Bounded in-process request and concurrency controls."""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import math
import threading
import time
from typing import Callable, Deque, Dict, Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of one sliding-window check."""

    allowed: bool
    retry_after: int = 0


@dataclass
class _WindowBucket:
    """Timestamps and expiry policy retained for one caller key."""

    events: Deque[float]
    window_seconds: float


class SlidingWindowRateLimiter:
    """Lock-protected sliding windows with a hard bound on retained keys."""

    def __init__(
        self,
        enabled: bool = True,
        max_keys: int = 10000,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Initialize an in-process rate limiter.

        Args:
            enabled: Whether checks should retain and enforce state.
            max_keys: Maximum simultaneous non-expired caller buckets.
            clock: Monotonic seconds provider, injectable for tests.
        """
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self.enabled = enabled
        self.max_keys = max_keys
        self.clock = clock
        self._buckets: Dict[str, _WindowBucket] = {}
        self._lock = threading.Lock()

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: float,
    ) -> RateLimitDecision:
        """Consume one allowance when the key is still inside its limit.

        Args:
            key: Scope-qualified caller key.
            limit: Requests allowed in the sliding window.
            window_seconds: Window length in seconds.

        Returns:
            Whether the request is allowed and whole seconds until retry.

        Raises:
            ValueError: If the key is empty or either numeric bound is not
                positive.
        """
        if not key:
            raise ValueError("key must not be empty")
        if limit < 1 or window_seconds <= 0:
            raise ValueError("rate limit and window must be positive")
        if not self.enabled:
            return RateLimitDecision(allowed=True)

        now = self.clock()
        with self._lock:
            self._remove_expired(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_keys:
                    return RateLimitDecision(
                        allowed=False,
                        retry_after=self._capacity_retry_after(now),
                    )
                bucket = _WindowBucket(deque(), window_seconds)
                self._buckets[key] = bucket
            else:
                bucket.window_seconds = window_seconds
                self._trim(bucket, now)

            if len(bucket.events) >= limit:
                retry_after = max(
                    1,
                    math.ceil(bucket.events[0] + window_seconds - now),
                )
                return RateLimitDecision(False, retry_after)

            bucket.events.append(now)
            return RateLimitDecision(True)

    def _trim(self, bucket: _WindowBucket, now: float) -> None:
        """Drop events whose window ended at or before ``now``.

        Args:
            bucket: Bucket to mutate.
            now: Current monotonic timestamp.
        """
        cutoff = now - bucket.window_seconds
        while bucket.events and bucket.events[0] <= cutoff:
            bucket.events.popleft()

    def _remove_expired(self, now: float) -> None:
        """Remove empty buckets so key rotation cannot leak memory.

        Args:
            now: Current monotonic timestamp.
        """
        expired = []
        for key, bucket in self._buckets.items():
            self._trim(bucket, now)
            if not bucket.events:
                expired.append(key)
        for key in expired:
            del self._buckets[key]

    def _capacity_retry_after(self, now: float) -> int:
        """Return when the earliest retained bucket can be reclaimed.

        Args:
            now: Current monotonic timestamp.

        Returns:
            Positive whole seconds until one bucket expires.
        """
        expiries = [
            bucket.events[-1] + bucket.window_seconds
            for bucket in self._buckets.values()
            if bucket.events
        ]
        return max(1, math.ceil(min(expiries) - now)) if expiries else 1

    @property
    def key_count(self) -> int:
        """Return the number of retained keys.

        Returns:
            Retained key count.
        """
        with self._lock:
            return len(self._buckets)


class ConcurrencyLimitError(RuntimeError):
    """Raised when an account has no concurrency slot available."""


class OperationLease(Protocol):
    """Service ownership contract for active blocking operations."""

    def release(self) -> None:
        """Request release after all deferred futures finish.

        Returns:
            None.
        """
        ...

    def defer_release_until(self, future) -> None:
        """Keep ownership until submitted blocking work really finishes.

        Args:
            future: Concurrent future representing submitted blocking work.

        Returns:
            None.
        """
        ...


class UnlimitedConcurrencyLease:
    """No-op ownership handle used when abuse controls are disabled."""

    def release(self) -> None:
        """Complete an unlimited operation.

        Returns:
            None.
        """

    def defer_release_until(self, future) -> None:
        """Accept an underlying future without retaining quota state.

        Args:
            future: Submitted work that would retain a bounded lease.

        Returns:
            None.
        """


class ConcurrencyLease:
    """Thread-safe handle whose release can wait for underlying futures."""

    def __init__(self, limiter: "ConcurrencyLimiter", key: str):
        """Store the limiter and key that own this slot.

        Args:
            limiter: Limiter to notify on release.
            key: Scope-qualified account key.
        """
        self._limiter = limiter
        self._key = key
        self._lock = threading.Lock()
        self._release_requested = False
        self._released = False
        self._deferred_futures = 0

    def defer_release_until(self, future) -> None:
        """Prevent release until an already-submitted future really finishes.

        Args:
            future: Concurrent future representing blocking work that cannot be
                force-cancelled with its awaiting coroutine.

        Returns:
            None.

        Raises:
            RuntimeError: If ownership was already fully released before the
                future was attached.
        """
        with self._lock:
            if self._released:
                raise RuntimeError("cannot defer an already released lease")
            self._deferred_futures += 1
        future.add_done_callback(self._deferred_future_done)

    def release(self) -> None:
        """Release this lease once.

        Returns:
            None.
        """
        should_release = False
        with self._lock:
            self._release_requested = True
            if not self._released and self._deferred_futures == 0:
                self._released = True
                should_release = True
        if should_release:
            self._limiter._release(self._key)

    def _deferred_future_done(self, _future) -> None:
        """Release after the last attached blocking future exits."""
        should_release = False
        with self._lock:
            self._deferred_futures -= 1
            if (
                self._release_requested
                and not self._released
                and self._deferred_futures == 0
            ):
                self._released = True
                should_release = True
        if should_release:
            self._limiter._release(self._key)


class ConcurrencyLimiter:
    """Lock-protected active-operation count separated by account and scope."""

    def __init__(self, max_concurrent: int = 2):
        """Initialize a per-key concurrency quota.

        Args:
            max_concurrent: Simultaneous leases allowed for one key.
        """
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self.max_concurrent = max_concurrent
        self._active: Dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> ConcurrencyLease:
        """Acquire one slot or reject the operation immediately.

        Args:
            key: Scope-qualified account key.

        Returns:
            An idempotently releasable lease.

        Raises:
            ConcurrencyLimitError: If the key already holds every slot.
        """
        if not key:
            raise ValueError("key must not be empty")
        with self._lock:
            active = self._active.get(key, 0)
            if active >= self.max_concurrent:
                raise ConcurrencyLimitError("Too many concurrent operations")
            self._active[key] = active + 1
        return ConcurrencyLease(self, key)

    @contextmanager
    def lease(self, key: str):
        """Hold one slot for the duration of a context.

        Args:
            key: Scope-qualified account key.

        Yields:
            The acquired lease.
        """
        acquired = self.acquire(key)
        try:
            yield acquired
        finally:
            acquired.release()

    def _release(self, key: str) -> None:
        """Release one active slot and discard empty keys.

        Args:
            key: Scope-qualified account key.

        Returns:
            None.
        """
        with self._lock:
            active = self._active.get(key, 0)
            if active <= 1:
                self._active.pop(key, None)
            else:
                self._active[key] = active - 1

    def active(self, key: str) -> int:
        """Return the active count for a key.

        Args:
            key: Scope-qualified account key.

        Returns:
            Active lease count.
        """
        with self._lock:
            return self._active.get(key, 0)

    @property
    def key_count(self) -> int:
        """Return the number of keys with active operations.

        Returns:
            Retained key count.
        """
        with self._lock:
            return len(self._active)
