"""Pre-parser ASGI cap for multipart PDF upload request bodies."""
import json
from typing import Awaitable, Callable, Dict


MULTIPART_ENVELOPE_ALLOWANCE_BYTES = 1024 * 1024


class _UploadBodyTooLarge(Exception):
    """Signal that the wrapped receiver crossed its byte boundary."""


class UploadBodyLimitMiddleware:
    """Reject oversized PDF multipart bodies before FastAPI parses the form."""

    def __init__(
        self,
        app: Callable,
        max_file_size_bytes: int,
        configured_limit_mb: int,
        multipart_overhead_bytes: int = MULTIPART_ENVELOPE_ALLOWANCE_BYTES,
    ):
        """Configure the exact file cap plus bounded multipart framing room.

        Args:
            app: Downstream ASGI application.
            max_file_size_bytes: Exact file-content limit enforced by the
                document service after form parsing.
            configured_limit_mb: User-facing configured file limit.
            multipart_overhead_bytes: Small allowance for multipart headers and
                boundaries outside the file content.
        """
        if max_file_size_bytes < 0 or multipart_overhead_bytes < 0:
            raise ValueError("upload body limits cannot be negative")
        self.app = app
        self.max_body_bytes = max_file_size_bytes + multipart_overhead_bytes
        self.configured_limit_mb = configured_limit_mb

    async def __call__(self, scope: Dict, receive: Callable, send: Callable) -> None:
        """Apply the cap to the PDF upload route and delegate other requests.

        Args:
            scope: ASGI connection scope.
            receive: ASGI request-message receiver.
            send: ASGI response-message sender.

        Returns:
            None after either emitting 413 or completing the downstream app.
        """
        if not self._is_limited_upload(scope):
            await self.app(scope, receive, send)
            return

        declared_length = self._content_length(scope)
        if declared_length is not None and declared_length > self.max_body_bytes:
            await self._send_too_large(send)
            return

        consumed = 0

        async def capped_receive():
            nonlocal consumed
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_body_bytes:
                    raise _UploadBodyTooLarge()
            return message

        try:
            await self.app(scope, capped_receive, send)
        except _UploadBodyTooLarge:
            # Form parsing happens before dependencies and route code, so no
            # response has started when this receiver raises. Crucially, do not
            # drain more frames: continuing would defeat the ingress memory cap.
            await self._send_too_large(send)

    def _is_limited_upload(self, scope: Dict) -> bool:
        """Return whether this is the multipart PDF upload endpoint."""
        if scope.get("type") != "http" or scope.get("method") != "POST":
            return False
        if not scope.get("path", "").rstrip("/").endswith("/upload"):
            return False
        content_type = self._header(scope, b"content-type") or b""
        return content_type.lower().startswith(b"multipart/form-data")

    def _content_length(self, scope: Dict):
        """Return a valid non-negative declared length, if supplied."""
        value = self._header(scope, b"content-length")
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    def _header(scope: Dict, name: bytes):
        """Return the first case-insensitive ASGI header value."""
        for key, value in scope.get("headers", []):
            if key.lower() == name:
                return value
        return None

    async def _send_too_large(self, send: Callable[[Dict], Awaitable[None]]) -> None:
        """Emit the stable JSON 413 response used by the upload route."""
        body = json.dumps({
            "detail": "File size exceeds maximum of %sMB"
            % self.configured_limit_mb,
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
