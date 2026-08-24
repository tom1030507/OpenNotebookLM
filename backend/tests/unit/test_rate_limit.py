"""Deterministic tests for bounded request and concurrency controls."""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from starlette.requests import Request

from app.routers.rate_limit import get_client_ip
from app.services.rate_limit import (
    ConcurrencyLimitError,
    ConcurrencyLimiter,
    SlidingWindowRateLimiter,
)


class FakeClock:
    """Mutable monotonic clock for exact boundary assertions."""

    def __init__(self, now=0.0):
        """Initialize the clock.

        Args:
            now: Initial monotonic timestamp.
        """
        self.now = now

    def __call__(self):
        """Return the current synthetic timestamp.

        Returns:
            Current monotonic seconds.
        """
        return self.now


def test_sliding_window_refuses_the_next_request_until_exact_expiry():
    """The fourth registration in an hour waits only for the oldest event."""
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)

    assert all(
        limiter.check("register:203.0.113.8", limit=3, window_seconds=3600).allowed
        for _ in range(3)
    )
    refusal = limiter.check("register:203.0.113.8", limit=3, window_seconds=3600)

    assert refusal.allowed is False
    assert refusal.retry_after == 3600

    clock.now = 3599.2
    assert limiter.check(
        "register:203.0.113.8", limit=3, window_seconds=3600
    ).retry_after == 1

    clock.now = 3600
    assert limiter.check(
        "register:203.0.113.8", limit=3, window_seconds=3600
    ).allowed is True


def test_rate_limit_keys_do_not_share_budgets():
    """One account/IP/scope cannot consume another one's allowance."""
    limiter = SlidingWindowRateLimiter(clock=FakeClock())

    assert limiter.check("login:198.51.100.1", 1, 60).allowed is True
    assert limiter.check("login:198.51.100.1", 1, 60).allowed is False
    assert limiter.check("login:198.51.100.2", 1, 60).allowed is True
    assert limiter.check("register:198.51.100.1", 1, 60).allowed is True


def test_disabled_limiter_keeps_no_state():
    """Development can explicitly disable limits without filling buckets."""
    limiter = SlidingWindowRateLimiter(enabled=False, clock=FakeClock())

    assert all(limiter.check("query:user", 1, 60).allowed for _ in range(10))
    assert limiter.key_count == 0


def test_expired_buckets_are_removed_and_state_stays_bounded():
    """Rotating source keys cannot grow the in-process map forever."""
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_keys=2, clock=clock)

    assert limiter.check("login:first", 1, 60).allowed
    assert limiter.check("login:second", 1, 60).allowed
    assert limiter.check("login:third", 1, 60).allowed is False
    assert limiter.key_count == 2

    clock.now = 60
    assert limiter.check("login:third", 1, 60).allowed
    assert limiter.key_count == 1


def test_third_concurrent_operation_is_refused_per_account():
    """Two active operations are allowed and the third acquires no lease."""
    limiter = ConcurrencyLimiter(max_concurrent=2)

    first = limiter.acquire("ingest:user-a")
    second = limiter.acquire("ingest:user-a")
    with pytest.raises(ConcurrencyLimitError):
        limiter.acquire("ingest:user-a")

    other = limiter.acquire("ingest:user-b")
    first.release()
    replacement = limiter.acquire("ingest:user-a")

    replacement.release()
    second.release()
    other.release()
    assert limiter.key_count == 0


def test_concurrency_lease_releases_after_an_exception():
    """A failed operation cannot permanently consume an account slot."""
    limiter = ConcurrencyLimiter(max_concurrent=1)

    with pytest.raises(RuntimeError):
        with limiter.lease("query:user"):
            raise RuntimeError("model failed")

    with limiter.lease("query:user"):
        assert limiter.active("query:user") == 1

    assert limiter.active("query:user") == 0


def test_release_waits_for_deferred_underlying_future_and_happens_once():
    """Cancellation cannot free a slot while its executor future is running."""
    class CountingLimiter(ConcurrencyLimiter):
        def __init__(self):
            super().__init__(max_concurrent=1)
            self.release_calls = 0

        def _release(self, key):
            self.release_calls += 1
            super()._release(key)

    limiter = CountingLimiter()
    lease = limiter.acquire("ingest:user")
    underlying = Future()

    lease.defer_release_until(underlying)
    lease.release()

    assert limiter.active("ingest:user") == 1
    underlying.set_result(None)
    assert limiter.active("ingest:user") == 0
    lease.release()
    assert limiter.release_calls == 1


def test_concurrent_release_calls_decrement_the_limiter_exactly_once():
    """Lease release is idempotent even when callbacks race across threads."""
    class CountingLimiter(ConcurrencyLimiter):
        def __init__(self):
            super().__init__(max_concurrent=1)
            self.release_calls = 0
            self.count_lock = Lock()

        def _release(self, key):
            with self.count_lock:
                self.release_calls += 1
            super()._release(key)

    limiter = CountingLimiter()
    lease = limiter.acquire("ingest:user")
    barrier = Barrier(16)

    def release_together():
        barrier.wait(timeout=2)
        lease.release()

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(release_together) for _ in range(16)]
        for future in futures:
            future.result(timeout=2)

    assert limiter.active("ingest:user") == 0
    assert limiter.release_calls == 1


def test_forwarded_address_is_ignored_without_explicit_proxy_trust():
    """A caller cannot rotate limiter keys by forging X-Forwarded-For."""
    request = Request({
        "type": "http",
        "client": ("198.51.100.20", 4321),
        "headers": [(b"x-forwarded-for", b"203.0.113.9, 198.51.100.2")],
    })

    assert get_client_ip(request, trust_proxy_headers=False) == "198.51.100.20"
    assert get_client_ip(request, trust_proxy_headers=True) == "203.0.113.9"
