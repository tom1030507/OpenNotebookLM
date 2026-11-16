"""HTTP adapters for request and concurrency limits."""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from starlette.requests import Request

from app.config import Settings, get_settings
from app.services.rate_limit import (
    ConcurrencyLimitError,
    ConcurrencyLimiter,
    SlidingWindowRateLimiter,
)


_request_limiter = SlidingWindowRateLimiter(
    enabled=get_settings().rate_limit_enabled,
    max_keys=get_settings().rate_limit_max_keys,
)
_concurrency_limiter = ConcurrencyLimiter(max_concurrent=2)


def get_rate_limiter() -> SlidingWindowRateLimiter:
    """Return the process-wide request limiter.

    Returns:
        Shared sliding-window limiter.
    """
    return _request_limiter


def get_concurrency_limiter() -> ConcurrencyLimiter:
    """Return the process-wide concurrency limiter.

    Returns:
        Shared per-account concurrency limiter.
    """
    return _concurrency_limiter


def get_client_ip(request: Request, trust_proxy_headers: bool = False) -> str:
    """Return the direct peer address used as the default limiter key.

    Args:
        request: Incoming HTTP request.
        trust_proxy_headers: Whether an operator-authorized proxy may identify
            the original client.

    Returns:
        Client address string.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For", "")
        original = forwarded.split(",", 1)[0].strip()
        if original:
            return original
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(
    limiter: SlidingWindowRateLimiter,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Consume an allowance or raise a standard HTTP 429 refusal.

    Args:
        limiter: Sliding-window service to consult.
        key: Scope-qualified IP or account key.
        limit: Requests allowed in the window.
        window_seconds: Sliding-window length.

    Returns:
        None when the request is allowed.

    Raises:
        HTTPException: With status 429 and Retry-After when refused.
    """
    decision = limiter.check(key, limit, window_seconds)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(decision.retry_after)},
        )


def enforce_account_rate_limit(
    limiter: SlidingWindowRateLimiter,
    scope: str,
    user_id: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Apply a sliding-window allowance to one authenticated account.

    Args:
        limiter: Sliding-window service to consult.
        scope: Operation namespace such as ``query`` or ``ingest``.
        user_id: Authenticated account identifier.
        limit: Requests allowed in the window.
        window_seconds: Sliding-window length.

    Returns:
        None when the request is allowed.
    """
    enforce_rate_limit(
        limiter,
        "%s:%s" % (scope, user_id),
        limit,
        window_seconds,
    )


def acquire_account_lease(
    limiter: ConcurrencyLimiter,
    scope: str,
    user_id: str,
):
    """Acquire an account operation slot or raise HTTP 429.

    Args:
        limiter: Shared concurrency limiter.
        scope: Operation namespace such as ``query`` or ``ingest``.
        user_id: Authenticated account identifier.

    Returns:
        An idempotently releasable concurrency lease.

    Raises:
        HTTPException: With status 429 when both account slots are active.
    """
    try:
        return limiter.acquire("%s:%s" % (scope, user_id))
    except ConcurrencyLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc


def limit_registration(
    request: Request,
    limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    settings: Settings = Depends(get_settings),
) -> None:
    """Limit account registration to three attempts per source IP per hour.

    Args:
        request: Incoming registration request.
        limiter: Shared request limiter.
        settings: Application settings controlling limiter/proxy behavior.

    Returns:
        None when the request may continue.
    """
    if settings.rate_limit_enabled:
        client_ip = get_client_ip(request, settings.trust_proxy_headers)
        enforce_rate_limit(limiter, "register:%s" % client_ip, 3, 3600)


def limit_login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    settings: Settings = Depends(get_settings),
) -> None:
    """Limit password guesses per account name, and more loosely per address.

    Behind the bundled frontend every browser reaches this API from the
    frontend's own address: Next's rewrite proxy adds no X-Forwarded-For. An
    address-only limit of ten a minute was therefore one allowance for the
    whole deployment, about five sign-ins a minute once the login page's
    demo-account read shared it (#232). Ten a minute per username still stops
    guessing one account's password; the per-address ceiling still bounds a
    single direct client trying many usernames.

    Args:
        request: Incoming sign-in request.
        form_data: The sign-in form; FastAPI parses it once for this and the
            route.
        limiter: Shared request limiter.
        settings: Application settings controlling limiter/proxy behavior.

    Returns:
        None when the request may continue.
    """
    if settings.rate_limit_enabled:
        client_ip = get_client_ip(request, settings.trust_proxy_headers)
        username = form_data.username.strip().lower()
        enforce_rate_limit(limiter, "login:%s:%s" % (client_ip, username), 10, 60)
        enforce_rate_limit(limiter, "login:%s" % client_ip, 100, 60)


def limit_demo_account_lookup(
    request: Request,
    limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    settings: Settings = Depends(get_settings),
) -> None:
    """Bound the demo-account hint, which verifies a password hash per call.

    Its own allowance: the login page reads it on every load, and sharing the
    sign-in allowance made each sign-in cost two attempts.

    Args:
        request: Incoming request for the hint.
        limiter: Shared request limiter.
        settings: Application settings controlling limiter/proxy behavior.

    Returns:
        None when the request may continue.
    """
    if settings.rate_limit_enabled:
        client_ip = get_client_ip(request, settings.trust_proxy_headers)
        enforce_rate_limit(limiter, "demo-account:%s" % client_ip, 120, 60)
