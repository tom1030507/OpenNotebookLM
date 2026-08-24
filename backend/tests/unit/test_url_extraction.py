"""Unit tests for URLAdapter validation, streaming, and text extraction.

Extraction had no tests, which is how a `from readability import Readability`
that raises ImportError went unnoticed: the flag it set was simply False, so
every page fell back to `soup.body` and the index filled up with navigation,
language lists and reference entries.
"""
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import requests
from bs4 import BeautifulSoup

from app.adapters import url as url_module
from app.adapters.url import URLAdapter
from app.utils.network import (
    UnsafeURLError,
    resolve_public_http_url,
    validate_public_http_url,
)


def resolver_for(*addresses):
    """Return a getaddrinfo-compatible resolver for literal addresses.

    Args:
        *addresses: IP address strings returned for every lookup.

    Returns:
        A resolver callable with the same result shape as socket.getaddrinfo.
    """
    def resolve(host, port, *args, **kwargs):
        family = socket.AF_INET6 if ":" in addresses[0] else socket.AF_INET
        return [
            (family, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]

    return resolve


class FakeResponse:
    """Small streamed response double for an external HTTP server."""

    def __init__(self, status=200, headers=None, chunks=()):
        """Store response metadata and lazily yielded body blocks.

        Args:
            status: HTTP status code.
            headers: Response headers.
            chunks: Body blocks yielded by ``iter_content``.
        """
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self._chunks = list(chunks)
        self.closed = False
        self.chunks_read = 0

    def iter_content(self, chunk_size):
        """Yield configured blocks while recording how far the reader got.

        Args:
            chunk_size: Requested block size, checked by the caller's contract.

        Yields:
            Configured body blocks.
        """
        assert chunk_size == 64 * 1024
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk

    def raise_for_status(self):
        """Raise the requests-style error used by the adapter for bad status."""
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)

    def close(self):
        """Record that the adapter released the response."""
        self.closed = True


class FakeSession:
    """Response queue standing in for external network I/O."""

    def __init__(self, responses):
        """Store the responses returned by consecutive GET requests.

        Args:
            responses: Response objects returned in order.
        """
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        """Return the next response and record request safety options.

        Args:
            url: Destination URL.
            **kwargs: Requests options.

        Returns:
            The next configured response.
        """
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class SequenceClock:
    """Monotonic clock returning a controlled sequence of timestamps."""

    def __init__(self, *timestamps):
        """Store timestamps returned by consecutive calls.

        Args:
            *timestamps: Monotonic seconds returned in order.
        """
        self.timestamps = iter(timestamps)

    def __call__(self):
        """Return the next timestamp.

        Returns:
            Next configured monotonic second.
        """
        return next(self.timestamps)


class TestPublicURLPolicy:
    """Only globally routable credential-free HTTP(S) targets are fetchable."""

    @pytest.mark.parametrize(
        "url,addresses",
        [
            ("file:///etc/passwd", ("93.184.216.34",)),
            ("ftp://example.com/file", ("93.184.216.34",)),
            ("https://user:secret@example.com", ("93.184.216.34",)),
            ("http://127.0.0.1", ("127.0.0.1",)),
            ("http://10.0.0.8", ("10.0.0.8",)),
            ("http://169.254.169.254/latest/meta-data", ("169.254.169.254",)),
            ("http://[::1]", ("::1",)),
            ("http://[fc00::1]", ("fc00::1",)),
            ("http://[fe80::1]", ("fe80::1",)),
            ("http://192.0.2.1", ("192.0.2.1",)),
        ],
    )
    def test_non_global_or_credentialed_destination_is_rejected(self, url, addresses):
        with pytest.raises(UnsafeURLError):
            validate_public_http_url(url, resolver=resolver_for(*addresses))

    def test_every_dns_answer_must_be_global(self):
        resolver = resolver_for("93.184.216.34", "127.0.0.1")

        with pytest.raises(UnsafeURLError):
            validate_public_http_url("https://example.com", resolver=resolver)

    @pytest.mark.parametrize(
        "address",
        [
            "224.0.0.1",             # IPv4 multicast
            "240.0.0.1",             # IPv4 reserved
            "0.0.0.0",               # IPv4 unspecified
            "127.0.0.1",             # IPv4 loopback
            "169.254.1.1",           # IPv4 link-local
            "10.0.0.1",              # IPv4 private
            "ff02::1",               # IPv6 multicast (is_global on Python 3.10)
            "100::1",                # IPv6 reserved/discard prefix
            "::",                    # IPv6 unspecified
            "::1",                   # IPv6 loopback
            "fe80::1",               # IPv6 link-local
            "fc00::1",               # IPv6 private
            "fec0::1",               # deprecated IPv6 site-local
            "::ffff:127.0.0.1",      # IPv4-mapped loopback
            "2002:7f00:1::",         # 6to4 embedding loopback
            "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo transition
        ],
    )
    def test_explicit_non_public_address_classes_are_rejected(self, address):
        """Every dangerous address flag and transition form is denied."""
        with pytest.raises(UnsafeURLError):
            validate_public_http_url(
                "https://example.com",
                resolver=resolver_for(address),
            )

    @pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
    def test_plain_public_ipv4_and_ipv6_addresses_are_allowed(self, address):
        """Explicit denials do not turn the policy into an IPv4-only allowlist."""
        assert validate_public_http_url(
            "https://example.com",
            resolver=resolver_for(address),
        ) == "https://example.com"

    def test_a_public_https_url_is_normalized_without_its_fragment(self):
        normalized = validate_public_http_url(
            "HTTPS://example.com/article?q=1#private-fragment",
            resolver=resolver_for("93.184.216.34"),
        )

        assert normalized == "https://example.com/article?q=1"

    def test_production_https_connection_pins_validated_ip_without_losing_hostname(
        self,
        monkeypatch,
    ):
        """Real Session.send pins the socket while TLS retains the URL host."""
        resolver_calls = []

        def resolver(host, port, *args, **kwargs):
            resolver_calls.append((host, port))
            return resolver_for("93.184.216.34")(host, port, *args, **kwargs)

        normalized, addresses = resolve_public_http_url(
            "https://example.com/article",
            resolver=resolver,
        )
        adapter = url_module._PinnedHTTPAdapter(addresses[0])
        client_socket, server_socket = socket.socketpair()
        socket_targets = []
        pool_hosts = []
        tls_hostnames = []
        hook_calls = []

        def connect(target, *args, **kwargs):
            socket_targets.append(target)
            return client_socket

        original_hook = adapter.get_connection_with_tls_context

        def hook(request, verify, proxies=None, cert=None):
            hook_calls.append(request.url)
            pool = original_hook(request, verify, proxies=proxies, cert=cert)
            pool_hosts.append(pool.host)
            return pool

        def wrap_tls(sock, **kwargs):
            tls_hostnames.append(kwargs["server_hostname"])
            return SimpleNamespace(socket=sock, is_verified=True)

        def serve_one_response():
            request_bytes = bytearray()
            while b"\r\n\r\n" not in request_bytes:
                request_bytes.extend(server_socket.recv(4096))
            server_socket.sendall(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 2\r\n"
                b"Connection: close\r\n\r\nOK"
            )
            server_socket.close()

        monkeypatch.setattr(url_module.urllib3_connection, "create_connection", connect)
        monkeypatch.setattr(
            url_module.urllib3_connection_module,
            "_ssl_wrap_socket_and_match_hostname",
            wrap_tls,
        )
        monkeypatch.setattr(adapter, "get_connection_with_tls_context", hook)
        server = threading.Thread(target=serve_one_response)
        server.start()
        session = requests.Session()
        session.trust_env = False
        session.mount("https://", adapter)
        try:
            response = session.get(normalized, timeout=1, verify=True)
            assert response.text == "OK"
        finally:
            session.close()
            server.join(timeout=2)

        assert server.is_alive() is False
        assert hook_calls == [normalized]
        assert pool_hosts == ["example.com"]
        assert tls_hostnames == ["example.com"]
        assert resolver_calls == [("example.com", 443)]
        assert socket_targets == [("93.184.216.34", 443)]

    def test_pinned_adapter_fails_fast_without_required_requests_hook(self, monkeypatch):
        """Unsupported Requests releases fail at startup, not during a fetch."""
        monkeypatch.setattr(
            requests.adapters.HTTPAdapter,
            "get_connection_with_tls_context",
            None,
        )

        with pytest.raises(RuntimeError, match="Requests transport hook"):
            url_module._PinnedHTTPAdapter("93.184.216.34")


class TestSafeURLDownload:
    """Every response hop is manually validated and streamed into a hard cap."""

    def test_safe_html_is_streamed_with_redirects_disabled(self):
        response = FakeResponse(chunks=[b"<html><main><p>Safe page</p></main></html>"])
        session = FakeSession([response])
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=session,
        )

        result = adapter.extract_content("https://example.com/page")

        assert result["text"] == "Safe page"
        assert response.closed is True
        _, options = session.calls[0]
        assert options["stream"] is True
        assert options["allow_redirects"] is False
        assert options["timeout"] == (5, 30)

    def test_redirect_destination_is_revalidated_before_request(self):
        first = FakeResponse(status=302, headers={"Location": "http://127.0.0.1/admin"})
        session = FakeSession([first])

        def resolver(host, port, *args, **kwargs):
            address = "127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"
            return resolver_for(address)(host, port, *args, **kwargs)

        adapter = URLAdapter(resolver=resolver, session=session)

        with pytest.raises(UnsafeURLError):
            adapter.extract_content("https://example.com/start")

        assert len(session.calls) == 1
        assert first.closed is True

    def test_sixth_redirect_is_rejected(self):
        redirects = [
            FakeResponse(status=302, headers={"Location": "/hop/%s" % index})
            for index in range(6)
        ]
        session = FakeSession(redirects)
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=session,
        )

        with pytest.raises(UnsafeURLError, match="redirect"):
            adapter.extract_content("https://example.com/start")

        assert len(session.calls) == 6
        assert all(response.closed for response in redirects)

    @pytest.mark.parametrize(
        "content_type",
        ["application/json", "application/octet-stream", "image/svg+xml"],
    )
    def test_non_text_response_is_rejected_and_closed(self, content_type):
        response = FakeResponse(headers={"Content-Type": content_type}, chunks=[b"ignored"])
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=FakeSession([response]),
        )

        with pytest.raises(UnsafeURLError, match="content type"):
            adapter.extract_content("https://example.com/data")

        assert response.chunks_read == 0
        assert response.closed is True

    def test_oversized_chunked_body_stops_at_the_cap(self):
        mebibyte = 1024 * 1024
        response = FakeResponse(chunks=[b"x" * mebibyte] * 11)
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=FakeSession([response]),
        )

        with pytest.raises(UnsafeURLError, match="10MB"):
            adapter.extract_content("https://example.com/large")

        assert response.chunks_read == 11
        assert response.closed is True

    def test_oversized_content_length_is_rejected_before_body_read(self):
        response = FakeResponse(
            headers={
                "Content-Type": "text/plain",
                "Content-Length": str(10 * 1024 * 1024 + 1),
            },
            chunks=[b"must not be read"],
        )
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=FakeSession([response]),
        )

        with pytest.raises(UnsafeURLError, match="10MB"):
            adapter.extract_content("https://example.com/large")

        assert response.chunks_read == 0
        assert response.closed is True

    def test_size_error_uses_the_configured_download_cap(self):
        """A non-default deployment reports its real cap rather than 10MB."""
        response = FakeResponse(
            headers={
                "Content-Type": "text/plain",
                "Content-Length": str(2 * 1024 * 1024 + 1),
            },
        )
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=FakeSession([response]),
            max_download_bytes=2 * 1024 * 1024,
        )

        with pytest.raises(UnsafeURLError, match="2MB"):
            adapter.extract_content("https://example.com/large")

    def test_download_stops_when_total_time_cap_is_crossed(self):
        response = FakeResponse(chunks=[b"first", b"must not be read"])
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=FakeSession([response]),
            clock=SequenceClock(0, 0, 31),
            max_download_seconds=30,
        )

        with pytest.raises(UnsafeURLError, match="time limit"):
            adapter.extract_content("https://example.com/slow")

        assert response.chunks_read == 1
        assert response.closed is True

    def test_wall_deadline_returns_while_dns_worker_is_still_blocked(self):
        """A stalled resolver cannot hold the caller beyond the global cap."""
        resolver_started = threading.Event()
        release_resolver = threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)

        def delayed_resolver(host, port, *args, **kwargs):
            resolver_started.set()
            release_resolver.wait(timeout=2)
            return resolver_for("93.184.216.34")(host, port, *args, **kwargs)

        adapter = URLAdapter(
            resolver=delayed_resolver,
            session=FakeSession([]),
            max_download_seconds=0.05,
            executor=executor,
        )
        started_at = time.monotonic()
        try:
            with pytest.raises(UnsafeURLError, match="time limit"):
                adapter.extract_content("https://example.com/slow-dns")
            elapsed = time.monotonic() - started_at
            assert resolver_started.is_set()
            assert elapsed < 0.2
        finally:
            release_resolver.set()
            executor.shutdown(wait=True)

    def test_wall_deadline_closes_session_blocked_on_redirect_headers(self):
        """The same deadline covers a later redirect hop waiting on headers."""
        class RedirectThenBlockingSession:
            def __init__(self):
                self.calls = 0
                self.closed = threading.Event()

            def get(self, url, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse(status=302, headers={"Location": "/next"})
                self.closed.wait(timeout=2)
                raise requests.ConnectionError("closed while waiting for headers")

            def close(self):
                self.closed.set()

        session = RedirectThenBlockingSession()
        executor = ThreadPoolExecutor(max_workers=1)
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=session,
            max_download_seconds=0.05,
            executor=executor,
        )
        started_at = time.monotonic()
        try:
            with pytest.raises(UnsafeURLError, match="time limit"):
                adapter.extract_content("https://example.com/start")
            assert time.monotonic() - started_at < 0.2
            assert session.closed.wait(timeout=0.2)
            assert session.calls == 2
        finally:
            session.close()
            executor.shutdown(wait=True)

    def test_wall_deadline_closes_a_slow_trickle_response(self):
        """Repeated body progress cannot reset the total download deadline."""
        class SlowResponse(FakeResponse):
            def __init__(self):
                super().__init__()
                self.close_event = threading.Event()

            def iter_content(self, chunk_size):
                while not self.close_event.wait(timeout=0.01):
                    yield b"x"

            def close(self):
                super().close()
                self.close_event.set()

        response = SlowResponse()
        executor = ThreadPoolExecutor(max_workers=1)
        adapter = URLAdapter(
            resolver=resolver_for("93.184.216.34"),
            session=FakeSession([response]),
            max_download_seconds=0.05,
            executor=executor,
        )
        started_at = time.monotonic()
        try:
            with pytest.raises(UnsafeURLError, match="time limit"):
                adapter.extract_content("https://example.com/trickle")
            assert time.monotonic() - started_at < 0.2
            assert response.close_event.wait(timeout=0.2)
        finally:
            response.close()
            executor.shutdown(wait=True)

    def test_stalled_dns_is_confined_to_the_configured_worker_bound(self):
        """Timed-out requests consume no more than the fixed resolver workers."""
        release_resolvers = threading.Event()
        state_lock = threading.Lock()
        active = 0
        peak = 0
        executor = ThreadPoolExecutor(max_workers=2)

        def delayed_resolver(host, port, *args, **kwargs):
            nonlocal active, peak
            with state_lock:
                active += 1
                peak = max(peak, active)
            try:
                release_resolvers.wait(timeout=2)
                return resolver_for("93.184.216.34")(host, port, *args, **kwargs)
            finally:
                with state_lock:
                    active -= 1

        adapter = URLAdapter(
            resolver=delayed_resolver,
            session=FakeSession([]),
            max_download_seconds=0.05,
            executor=executor,
        )

        def fetch(index):
            with pytest.raises(UnsafeURLError, match="time limit"):
                adapter.extract_content("https://example.com/%s" % index)

        try:
            with ThreadPoolExecutor(max_workers=6) as callers:
                futures = [callers.submit(fetch, index) for index in range(6)]
                for future in futures:
                    future.result(timeout=1)
            assert peak == 2
        finally:
            release_resolvers.set()
            executor.shutdown(wait=True)


# A miniature of the structure that caused the trouble: chrome and a reference
# list wrapped around a short article.
WIKI_LIKE = """
<html><head><title>Transformer (deep learning) - Wikipedia</title></head>
<body>
  <nav id="p-lang"><ul><li>Afrikaans</li><li>العربية</li><li>日本語</li></ul></nav>
  <div id="toc">Toggle the table of contents</div>
  <div class="ambox"><p>This article needs more citations. Please help improve it.</p></div>
  <main>
    <div id="mw-content-text">
      <p>A <a href="/wiki/transformer">transformer</a> is a neural architecture.</p>
      <h2>Architecture<span class="mw-editsection">[edit]</span></h2>
      <p>The encoder and the decoder each stack identical blocks.<sup class="reference">[1]</sup></p>
      <table>
        <tr><th>Variant</th><th>Note</th></tr>
        <tr><td>Linformer</td><td>low-rank attention</td></tr>
      </table>
      <ol class="references">
        <li>Vaswani, Ashish. Attention Is All You Need. arXiv:1706.03762. doi:10.5555/1</li>
      </ol>
    </div>
  </main>
  <footer><p>Privacy Policy</p></footer>
</body></html>
"""

CHINESE_INLINE = """
<html><body><main><p>注意力機制是<a href="/x">類神經網路</a>中一種模仿認知注意力的技術。</p></main></body></html>
"""

MATH_PAGE = """
<html><body><main>
<p>網路計算出滿足
<span class="mwe-math-element"><math><annotation>{\\displaystyle \\sum _{i}w_{i}=1}</annotation></math></span>
的非負軟權重。</p>
</main></body></html>
"""

DIV_ONLY_PAGE = """
<html><body><main><div>Some sites put their prose straight inside a div with no
paragraph element at all, and it still has to be extracted.</div></main></body></html>
"""


def extract(html: str) -> str:
    """Run the adapter's extraction over a literal document.

    Args:
        html: Page source.

    Returns:
        Extracted text.
    """
    adapter = URLAdapter()
    soup = BeautifulSoup(html, "html.parser")
    adapter._strip_non_content(soup)
    adapter._inline_math(soup)
    return adapter._extract_main_content(soup, "test://page")["text"]


class TestBoilerplateRemoval:
    """The furniture that used to outrank real passages has to be gone."""

    def test_language_list_is_dropped(self):
        text = extract(WIKI_LIKE)
        assert "Afrikaans" not in text
        assert "日本語" not in text

    def test_table_of_contents_toggle_is_dropped(self):
        assert "Toggle the table of contents" not in extract(WIKI_LIKE)

    def test_maintenance_banner_is_dropped(self):
        assert "needs more citations" not in extract(WIKI_LIKE)

    def test_reference_list_is_dropped(self):
        # Reference entries were the single worst pollutant: dense, numerous and
        # topically close to the article, so they filled the top of every result.
        text = extract(WIKI_LIKE)
        assert "arXiv:1706.03762" not in text
        assert "Vaswani" not in text

    def test_edit_link_is_dropped_from_the_heading(self):
        assert "[edit]" not in extract(WIKI_LIKE)

    def test_footer_boilerplate_is_dropped(self):
        assert "Privacy Policy" not in extract(WIKI_LIKE)


class TestContentPreservation:
    """Stripping furniture must not take content with it."""

    def test_prose_survives(self):
        assert "is a neural architecture" in extract(WIKI_LIKE)

    def test_headings_become_markdown(self):
        # The chunker reads these back to rebuild a section path.
        assert "## Architecture" in extract(WIKI_LIKE)

    def test_table_content_survives(self):
        # readability discards tables outright, which is why an explicit content
        # container is preferred over it.
        assert "Linformer" in extract(WIKI_LIKE)

    def test_table_row_is_one_line_with_its_cells(self):
        lines = extract(WIKI_LIKE).split("\n")
        assert any("Linformer | low-rank attention" == line for line in lines)

    def test_prose_inside_a_bare_div_is_not_lost(self):
        assert "straight inside a div" in extract(DIV_ONLY_PAGE)


class TestChineseSpacing:
    """A separator between inline elements lands inside Chinese sentences."""

    def test_inline_link_does_not_split_a_chinese_term(self):
        text = extract(CHINESE_INLINE)
        assert "注意力機制是類神經網路中一種模仿認知注意力的技術。" in text

    def test_math_is_folded_inline_instead_of_becoming_its_own_lines(self):
        text = extract(MATH_PAGE)
        # One line, not four one-character ones.
        assert len([line for line in text.split("\n") if line.strip()]) == 1
        assert "非負軟權重" in text
        assert "displaystyle" not in text


class TestNoiseLines:
    """Line-level filtering, never mid-sentence substitution."""

    def test_a_whole_line_of_boilerplate_is_dropped(self):
        adapter = URLAdapter()
        assert adapter._is_noise_line("Privacy Policy")
        assert adapter._is_noise_line("Jump to content")
        assert adapter._is_noise_line("12")

    def test_a_sentence_about_boilerplate_is_kept(self):
        # Substituting these globally used to delete the phrase out of an article
        # that was about privacy policies.
        adapter = URLAdapter()
        line = "The Privacy Policy of a data broker is rarely read in full."
        assert not adapter._is_noise_line(line)
        assert adapter._clean_text(line) == line

    def test_a_bibliography_line_needs_two_markers(self):
        adapter = URLAdapter()
        assert adapter._is_noise_line("Smith, J. Title. arXiv:1234.5678 . doi:10.1/x")
        assert not adapter._is_noise_line("The registry issues a doi: for each dataset.")

    def test_paragraph_breaks_survive_cleaning(self):
        adapter = URLAdapter()
        cleaned = adapter._clean_text("First paragraph.\n\nSecond paragraph.")
        assert cleaned == "First paragraph.\n\nSecond paragraph."
