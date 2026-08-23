"""Unit tests for URLAdapter validation, streaming, and text extraction.

Extraction had no tests, which is how a `from readability import Readability`
that raises ImportError went unnoticed: the flag it set was simply False, so
every page fell back to `soup.body` and the index filled up with navigation,
language lists and reference entries.
"""
import socket

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
        """Socket target cannot rebind while TLS still verifies the URL host."""
        resolver_calls = []

        def resolver(host, port, *args, **kwargs):
            resolver_calls.append((host, port))
            return resolver_for("93.184.216.34")(host, port, *args, **kwargs)

        normalized, addresses = resolve_public_http_url(
            "https://example.com/article",
            resolver=resolver,
        )
        adapter = url_module._PinnedHTTPAdapter(addresses[0])
        prepared = requests.Request("GET", normalized).prepare()
        pool = adapter.get_connection_with_tls_context(prepared, verify=True)

        socket_sentinel = object()
        socket_targets = []

        def connect(target, *args, **kwargs):
            socket_targets.append(target)
            return socket_sentinel

        monkeypatch.setattr(url_module.urllib3_connection, "create_connection", connect)
        connection = pool._new_conn()

        assert pool.host == "example.com"
        assert connection.host == "example.com"
        assert connection._new_conn() is socket_sentinel
        assert resolver_calls == [("example.com", 443)]
        assert socket_targets == [("93.184.216.34", 443)]


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
