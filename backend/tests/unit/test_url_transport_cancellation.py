"""Real-socket tests for URL transport cancellation boundaries."""
import os
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.adapters import url as url_module
from app.adapters.url import URLAdapter
from app.utils.network import UnsafeURLError
from app.utils.time import utc_now


def _resolver_for_public_example(host, port, *args, **kwargs):
    """Resolve the test hostname to a policy-safe address."""
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port),
        )
    ]


def _make_tls_context(tmp_path):
    """Create a short-lived test CA/server certificate for example.com."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "example.com")])
    now = utc_now()
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("example.com")]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    certificate_path = tmp_path / "server-cert.pem"
    private_key_path = tmp_path / "server-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_path, private_key_path)
    return context, str(certificate_path)


def _patch_connections_to_localhost(monkeypatch, certificate_path):
    """Route pinned sockets locally while retaining the real Requests/TLS stack."""
    original_create_connection = url_module.urllib3_connection.create_connection
    original_session = requests.Session

    def create_local_connection(address, *args, **kwargs):
        return original_create_connection(
            ("127.0.0.1", address[1]),
            *args,
            **kwargs,
        )

    def trusted_session():
        session = original_session()
        session.verify = certificate_path
        return session

    monkeypatch.setattr(
        url_module.urllib3_connection,
        "create_connection",
        create_local_connection,
    )
    monkeypatch.setattr(url_module.requests, "Session", trusted_session)


def _wait_until(predicate, timeout):
    """Poll a thread-owned condition without adding a fixed sleep."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class _HeaderStallTLSServer:
    """TLS server that stalls four headers, then serves one recovery request."""

    def __init__(self, context, stalled_connections=4):
        self._context = context
        self._stalled_connections = stalled_connections
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(stalled_connections + 1)
        self._listener.settimeout(0.1)
        self.port = self._listener.getsockname()[1]
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._handlers = []
        self._accepted = 0
        self._stalled_ready = 0
        self._peer_closed = 0
        self._accept_thread = threading.Thread(target=self._accept, daemon=True)
        self._accept_thread.start()

    @property
    def stalled_ready(self):
        """Return the number of clients waiting on incomplete headers."""
        with self._lock:
            return self._stalled_ready

    @property
    def peer_closed(self):
        """Return the number of connections whose client side closed."""
        with self._lock:
            return self._peer_closed

    def close(self):
        """Stop accepting and release all server-side worker threads."""
        self._stop.set()
        self._listener.close()
        self._accept_thread.join(timeout=2)
        for handler in list(self._handlers):
            handler.join(timeout=2)

    def _accept(self):
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except (OSError, socket.timeout):
                continue
            connection.settimeout(2)
            with self._lock:
                index = self._accepted
                self._accepted += 1
            handler = threading.Thread(
                target=self._serve,
                args=(connection, index),
                daemon=True,
            )
            self._handlers.append(handler)
            handler.start()

    def _serve(self, connection, index):
        try:
            with self._context.wrap_socket(connection, server_side=True) as tls_socket:
                request = bytearray()
                while b"\r\n\r\n" not in request:
                    request.extend(tls_socket.recv(4096))
                if index < self._stalled_connections:
                    tls_socket.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/html\r\n"
                        b"Content-Length: 2\r\n"
                        b"X-Incomplete: "
                    )
                    with self._lock:
                        self._stalled_ready += 1
                    tls_socket.settimeout(0.1)
                    while not self._stop.is_set():
                        try:
                            if not tls_socket.recv(1):
                                break
                        except socket.timeout:
                            continue
                    return

                tls_socket.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/html\r\n"
                    b"Content-Length: 35\r\n"
                    b"Connection: keep-alive\r\n\r\n"
                    b"<html><main>Recovered</main></html>"
                )
                tls_socket.settimeout(0.1)
                while not self._stop.is_set():
                    try:
                        if not tls_socket.recv(1):
                            break
                    except socket.timeout:
                        continue
        except (OSError, ssl.SSLError):
            pass
        finally:
            try:
                connection.close()
            finally:
                with self._lock:
                    self._peer_closed += 1


class _HandshakeStallServer:
    """TCP server that reads ClientHello but never completes TLS."""

    def __init__(self):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self.client_hello = threading.Event()
        self.peer_closed = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self):
        """Release the listener and its accepted connection."""
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)

    def _serve(self):
        connection = None
        try:
            connection, _ = self._listener.accept()
            connection.settimeout(0.1)
            while not self._stop.is_set():
                try:
                    data = connection.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    self.peer_closed.set()
                    return
                self.client_hello.set()
        except OSError:
            pass
        finally:
            if connection is not None:
                connection.close()


class _CountingSocket:
    """Record cancellation-handle calls at the OS socket boundary."""

    def __init__(self):
        self.shutdown_calls = []
        self.close_calls = 0

    def shutdown(self, how):
        """Record the requested shutdown direction."""
        self.shutdown_calls.append(how)

    def close(self):
        """Record a descriptor close."""
        self.close_calls += 1


def test_socket_cancellation_handle_cleans_up_exactly_once():
    """Timeout and later connection cleanup cannot close one handle twice."""
    tracked_socket = _CountingSocket()
    handle = url_module._SocketCancellationHandle(tracked_socket)

    handle.cancel()
    handle.cancel()
    handle.close()

    assert tracked_socket.shutdown_calls == [socket.SHUT_RDWR]
    assert tracked_socket.close_calls == 1


def test_socket_cancellation_handle_normal_close_does_not_shutdown():
    """Normal completion closes its handle once without aborting transport."""
    tracked_socket = _CountingSocket()
    handle = url_module._SocketCancellationHandle(tracked_socket)

    handle.close()
    handle.cancel()
    handle.close()

    assert tracked_socket.shutdown_calls == []
    assert tracked_socket.close_calls == 1


def test_real_tls_header_stalls_are_interrupted_and_four_worker_pool_recovers(
    tmp_path,
    monkeypatch,
):
    """Caller cancellation must stop real TLS header reads, not fake sessions."""
    tls_context, certificate_path = _make_tls_context(tmp_path)
    _patch_connections_to_localhost(monkeypatch, certificate_path)
    server = _HeaderStallTLSServer(tls_context)
    adapter = URLAdapter(
        timeout=2,
        connect_timeout=2,
        resolver=_resolver_for_public_example,
        max_download_seconds=0.25,
    )
    operations = [
        adapter.start_extract_content(
            "https://example.com:%s/stall/%s" % (server.port, index)
        )
        for index in range(4)
    ]

    try:
        assert _wait_until(lambda: server.stalled_ready == 4, timeout=2)
        for operation in operations:
            with pytest.raises(UnsafeURLError, match="time limit"):
                operation.result()

        assert _wait_until(
            lambda: all(operation.future.done() for operation in operations),
            timeout=0.5,
        )
        assert _wait_until(lambda: server.peer_closed >= 4, timeout=0.5)

        recovery_adapter = URLAdapter(
            timeout=2,
            connect_timeout=2,
            resolver=_resolver_for_public_example,
            max_download_seconds=1,
        )
        result = recovery_adapter.extract_content(
            "https://example.com:%s/recovered" % server.port
        )
        assert result["text"] == "Recovered"
        assert _wait_until(lambda: server.peer_closed == 5, timeout=0.5)
    finally:
        server.close()


def test_real_tls_handshake_is_interrupted_at_the_caller_deadline(
    tmp_path,
    monkeypatch,
):
    """Socket ownership transfer cannot leave TLS handshake work behind."""
    _, certificate_path = _make_tls_context(tmp_path)
    _patch_connections_to_localhost(monkeypatch, certificate_path)
    server = _HandshakeStallServer()
    executor = ThreadPoolExecutor(max_workers=1)
    adapter = URLAdapter(
        timeout=2,
        connect_timeout=2,
        resolver=_resolver_for_public_example,
        max_download_seconds=0.25,
        executor=executor,
    )
    operation = adapter.start_extract_content(
        "https://example.com:%s/handshake" % server.port
    )

    try:
        assert server.client_hello.wait(timeout=1)
        with pytest.raises(UnsafeURLError, match="time limit"):
            operation.result()
        assert _wait_until(operation.future.done, timeout=0.5)
        assert server.peer_closed.wait(timeout=0.5)
    finally:
        server.close()
        executor.shutdown(wait=True)


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="Linux fd audit")
def test_real_tls_normal_completion_releases_client_connection_and_file_descriptors(
    tmp_path,
    monkeypatch,
):
    """A keep-alive response cannot strand the adapter's temporary pool."""
    tls_context, certificate_path = _make_tls_context(tmp_path)
    _patch_connections_to_localhost(monkeypatch, certificate_path)
    server = _HeaderStallTLSServer(tls_context, stalled_connections=0)
    executor = ThreadPoolExecutor(max_workers=4)
    adapter = URLAdapter(
        resolver=_resolver_for_public_example,
        max_download_seconds=1,
        executor=executor,
    )
    baseline_descriptors = len(os.listdir("/proc/self/fd"))

    try:
        operation = adapter.start_extract_content(
            "https://example.com:%s/normal" % server.port
        )
        result = operation.result()
        assert result["text"] == "Recovered"
        assert _wait_until(lambda: server.peer_closed == 1, timeout=0.5)
        assert len(os.listdir("/proc/self/fd")) <= baseline_descriptors
        assert operation.future.done()
    finally:
        server.close()
        executor.shutdown(wait=True)
