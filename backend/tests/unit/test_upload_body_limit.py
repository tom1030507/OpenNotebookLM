"""ASGI-level multipart upload body-limit tests."""
import asyncio

from app.middleware.upload_body_limit import UploadBodyLimitMiddleware


def _upload_scope(content_length=None, origin=None):
    """Build an HTTP upload scope with optional declared length.

    Args:
        content_length: Optional declared request-body byte count.
        origin: Optional browser Origin header.

    Returns:
        Minimal ASGI HTTP scope for the PDF upload route.
    """
    headers = [(b"content-type", b"multipart/form-data; boundary=boundary")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/projects/project/upload",
        "raw_path": b"/api/projects/project/upload",
        "query_string": b"",
        "headers": headers,
        "client": ("203.0.113.10", 1234),
        "server": ("testserver", 80),
    }


def test_declared_oversize_is_rejected_without_reading_or_calling_app():
    """A declared oversized multipart body never reaches parsing or auth."""
    receive_calls = 0
    app_calls = 0
    sent = []

    async def receive():
        nonlocal receive_calls
        receive_calls += 1
        raise AssertionError("declared oversized body was read")

    async def downstream(scope, receive, send):
        nonlocal app_calls
        app_calls += 1
        raise AssertionError("declared oversized body reached downstream app")

    async def send(message):
        sent.append(message)

    middleware = UploadBodyLimitMiddleware(
        downstream,
        max_file_size_bytes=8,
        multipart_overhead_bytes=4,
        configured_limit_mb=50,
    )
    asyncio.run(middleware(_upload_scope(content_length=13), receive, send))

    assert receive_calls == 0
    assert app_calls == 0
    assert sent[0]["status"] == 413
    assert b"50MB" in sent[1]["body"]


def test_actual_multimessage_body_stops_at_first_frame_crossing_cap():
    """A lying/chunked body cannot feed parser frames after crossing the cap."""
    messages = [
        {"type": "http.request", "body": b"aaaa", "more_body": True},
        {"type": "http.request", "body": b"bbbb", "more_body": True},
        {"type": "http.request", "body": b"ccccc", "more_body": True},
        {"type": "http.request", "body": b"must-not-be-read", "more_body": False},
    ]
    receive_calls = 0
    downstream_bytes = 0
    handler_reached = False
    sent = []

    async def receive():
        nonlocal receive_calls
        message = messages[receive_calls]
        receive_calls += 1
        return message

    async def downstream(scope, receive, send):
        nonlocal downstream_bytes, handler_reached
        while True:
            message = await receive()
            downstream_bytes += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        handler_reached = True

    async def send(message):
        sent.append(message)

    middleware = UploadBodyLimitMiddleware(
        downstream,
        max_file_size_bytes=8,
        multipart_overhead_bytes=4,
        configured_limit_mb=50,
    )
    asyncio.run(middleware(_upload_scope(), receive, send))

    assert receive_calls == 3
    assert downstream_bytes == 8
    assert handler_reached is False
    assert sent[0]["status"] == 413


def test_non_upload_request_is_not_capped():
    """The multipart allowance does not alter unrelated request bodies."""
    downstream_called = False
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"large", "more_body": False}

    async def downstream(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True
        message = await receive()
        assert message["body"] == b"large"
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        sent.append(message)

    middleware = UploadBodyLimitMiddleware(
        downstream,
        max_file_size_bytes=1,
        multipart_overhead_bytes=1,
        configured_limit_mb=50,
    )
    scope = _upload_scope(content_length=100)
    scope["path"] = "/api/query"
    asyncio.run(middleware(scope, receive, send))

    assert downstream_called is True
    assert sent[0]["status"] == 204


def test_app_cors_wraps_preparser_upload_rejection():
    """Browser clients receive CORS headers even when the body guard rejects."""
    from app.main import app

    sent = []

    async def receive():
        raise AssertionError("declared oversized body was read")

    async def send(message):
        sent.append(message)

    scope = _upload_scope(
        content_length=60 * 1024 * 1024,
        origin="http://localhost:3000",
    )
    asyncio.run(app(scope, receive, send))

    response_start = sent[0]
    headers = dict(response_start["headers"])
    assert response_start["status"] == 413
    assert headers[b"access-control-allow-origin"] == b"http://localhost:3000"
