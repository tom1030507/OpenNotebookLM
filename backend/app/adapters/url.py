"""URL content extraction adapter."""
import asyncio
import re
import socket
import threading
import time
from concurrent.futures import (
    Executor,
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse
import structlog
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup, NavigableString
from urllib3 import connection as urllib3_connection_module
from urllib3 import connectionpool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
from urllib3.util import connection as urllib3_connection

from app.utils.network import (
    UnsafeURLError,
    resolve_public_http_url,
)

try:
    # readability-lxml exports `Document`. An earlier version of this module
    # imported a `Readability` symbol that does not exist, so the flag was
    # always False and every page silently fell through to `soup.body` —
    # navigation, language lists and reference sections included.
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:  # pragma: no cover - depends on the environment
    HAS_READABILITY = False

logger = structlog.get_logger()

MAX_URL_DOWNLOAD_MB = 10
MAX_URL_DOWNLOAD_BYTES = MAX_URL_DOWNLOAD_MB * 1024 * 1024
MAX_URL_REDIRECTS = 5
URL_STREAM_BLOCK_BYTES = 64 * 1024
URL_DOWNLOAD_WORKERS = 4
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
ACCEPTED_CONTENT_TYPES = frozenset({
    "text/html",
    "application/xhtml+xml",
    "text/plain",
})
_URL_DOWNLOAD_EXECUTOR = ThreadPoolExecutor(
    max_workers=URL_DOWNLOAD_WORKERS,
    thread_name_prefix="url-download",
)


def _require_supported_requests_transport() -> None:
    """Fail before serving requests when the DNS-pin hook is unavailable."""
    if not callable(getattr(HTTPAdapter, "get_connection_with_tls_context", None)):
        raise RuntimeError(
            "Requests transport hook get_connection_with_tls_context is unavailable; "
            "install requests==2.34.2 with urllib3==2.7.0"
        )


class _FetchControl:
    """Thread-safe cancellation and active transport registry for one fetch."""

    def __init__(self):
        self._cancelled = False
        self._closeables = []
        self._lock = threading.Lock()

    def register(self, closeable) -> None:
        """Register an active session, response, or socket for cancellation."""
        should_close = False
        with self._lock:
            if self._cancelled:
                should_close = True
            elif closeable not in self._closeables:
                self._closeables.append(closeable)
        if should_close:
            self._close(closeable)

    def unregister(self, closeable) -> None:
        """Stop retaining a transport that has already been closed."""
        with self._lock:
            if closeable in self._closeables:
                self._closeables.remove(closeable)

    def cancel(self) -> None:
        """Close active transports and prevent a later one from opening."""
        with self._lock:
            self._cancelled = True
            closeables = list(reversed(self._closeables))
        for closeable in closeables:
            self._close(closeable)

    def raise_if_cancelled(self) -> None:
        """Raise the stable deadline error after cancellation."""
        with self._lock:
            cancelled = self._cancelled
        if cancelled:
            raise UnsafeURLError("URL download exceeded the time limit")

    @staticmethod
    def _close(closeable) -> None:
        """Best-effort close without hiding the caller's timeout refusal."""
        try:
            closeable.close()
        except Exception:
            # Cancellation is already returning a stable timeout. A close race
            # must not replace it with a transport-specific cleanup exception.
            pass


class URLFetchOperation:
    """A bounded caller-facing handle for one fixed-pool URL extraction."""

    def __init__(
        self,
        future: Future,
        control: _FetchControl,
        timeout_seconds: float,
    ):
        """Store the underlying worker and its absolute caller deadline.

        Args:
            future: Actual fixed-pool extraction future.
            control: Registry used to interrupt active transports.
            timeout_seconds: Total caller wall-clock allowance from submission.
        """
        self.future = future
        self._control = control
        self._deadline = time.monotonic() + timeout_seconds

    def result(self):
        """Wait only until the global deadline and return extracted content.

        Returns:
            Extracted URL content dictionary.

        Raises:
            UnsafeURLError: When the global caller deadline expires.
        """
        try:
            return self.future.result(timeout=self._remaining())
        except FutureTimeoutError as exc:
            self._abort()
            raise UnsafeURLError("URL download exceeded the time limit") from exc

    async def wait(self):
        """Asynchronously wait only until the same global deadline.

        Returns:
            Extracted URL content dictionary.

        Raises:
            UnsafeURLError: When the global caller deadline expires.
            asyncio.CancelledError: When the awaiting request is cancelled.
        """
        wrapped = asyncio.wrap_future(self.future)
        try:
            return await asyncio.wait_for(
                asyncio.shield(wrapped),
                timeout=self._remaining(),
            )
        except asyncio.TimeoutError as exc:
            self._abort()
            raise UnsafeURLError("URL download exceeded the time limit") from exc
        except asyncio.CancelledError:
            self._abort()
            raise

    def _remaining(self) -> float:
        """Return non-negative caller time remaining."""
        return max(0.0, self._deadline - time.monotonic())

    def _abort(self) -> None:
        """Cancel queued work and interrupt active transports where possible."""
        self._control.cancel()
        self.future.cancel()


class _PinnedConnectionMixin:
    """Connect an urllib3 connection to a pre-validated literal address."""

    def __init__(
        self,
        *args,
        pinned_address: str,
        fetch_control: Optional[_FetchControl] = None,
        **kwargs,
    ):
        """Store the address that DNS validation approved.

        Args:
            *args: Positional connection arguments.
            pinned_address: Literal public IP used for the socket.
            fetch_control: Optional deadline cancellation registry.
            **kwargs: Keyword connection arguments.
        """
        self._pinned_address = pinned_address
        self._fetch_control = fetch_control
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        """Open a socket without performing a second DNS lookup.

        Returns:
            A connected socket.
        """
        try:
            connected_socket = urllib3_connection.create_connection(
                (self._pinned_address, self.port),
                self.timeout,
                source_address=self.source_address,
                socket_options=self.socket_options,
            )
            if self._fetch_control is not None:
                self._fetch_control.register(connected_socket)
                self._fetch_control.raise_if_cancelled()
            return connected_socket
        except (TimeoutError, socket.timeout) as exc:
            raise ConnectTimeoutError(
                self,
                "Connection to %s timed out" % self.host,
            ) from exc
        except OSError as exc:
            raise NewConnectionError(
                self,
                "Failed to connect to validated address: %s" % exc,
            ) from exc


class _PinnedHTTPConnection(_PinnedConnectionMixin, urllib3_connection_module.HTTPConnection):
    """HTTP connection whose socket target is a validated IP."""


class _PinnedHTTPSConnection(_PinnedConnectionMixin, urllib3_connection_module.HTTPSConnection):
    """HTTPS connection that keeps the URL hostname for SNI verification."""


class _PinnedHTTPConnectionPool(connectionpool.HTTPConnectionPool):
    """Pool using DNS-pinned HTTP connections."""

    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSConnectionPool(connectionpool.HTTPSConnectionPool):
    """Pool using DNS-pinned HTTPS connections."""

    ConnectionCls = _PinnedHTTPSConnection


class _PinnedHTTPAdapter(HTTPAdapter):
    """Requests adapter that connects to one validated address per attempt."""

    def __init__(
        self,
        pinned_address: str,
        fetch_control: Optional[_FetchControl] = None,
    ):
        """Initialize an adapter for a single literal IP.

        Args:
            pinned_address: Public address approved by URL validation.
            fetch_control: Optional deadline cancellation registry.
        """
        _require_supported_requests_transport()
        self._pinned_address = pinned_address
        self._fetch_control = fetch_control
        super().__init__(max_retries=0)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        """Build a one-origin pool whose sockets cannot re-resolve DNS.

        Args:
            request: Prepared requests request.
            verify: TLS verification configuration.
            proxies: Ignored; outbound imports never trust environment proxies.
            cert: Optional client certificate configuration.

        Returns:
            A pinned HTTP or HTTPS connection pool.
        """
        host_params, pool_kwargs = self.build_connection_pool_key_attributes(
            request,
            verify,
            cert,
        )
        pool_kwargs["pinned_address"] = self._pinned_address
        pool_kwargs["fetch_control"] = self._fetch_control
        pool_class = (
            _PinnedHTTPSConnectionPool
            if host_params["scheme"] == "https"
            else _PinnedHTTPConnectionPool
        )
        return pool_class(
            host=host_params["host"],
            port=host_params["port"],
            **pool_kwargs,
        )

# Containers that are never article content. Removing them before extraction is
# what keeps navigation, edit links, language lists, maintenance banners and
# above all *reference lists* out of the index. Reference entries are the worst
# offenders: they are dense, numerous, and topically similar to the article, so
# they crowd out real passages in a vector search.
NON_CONTENT_SELECTORS = (
    "script", "style", "noscript", "template", "svg", "form",
    "nav", "header", "footer", "aside",
    "[role='navigation']", "[role='banner']", "[role='contentinfo']",
    "[role='search']",
    ".navbox", ".vertical-navbox", ".sidebar", ".sistersitebox",
    ".mw-editsection", ".mw-jump-link", ".mw-indicators", ".mw-footer",
    "#toc", ".toc", "#siteSub", "#contentSub",
    ".reflist", ".references", "ol.references", ".reference",
    ".refbegin", ".mw-references-wrap", ".citation",
    ".hatnote", ".ambox", ".mbox-text", ".metadata", ".ambox-content",
    ".catlinks", ".printfooter", ".noprint", ".shortdescription",
    ".cookie-banner", ".cookie-consent", ".newsletter", ".breadcrumb",
    ".share", ".social", ".related-posts", ".comments", "#comments",
)

# Explicit content containers, tried in order. Preferred over readability:
# readability is a text-density heuristic and drops `<table>` outright, which on
# a reference page throws away comparison tables that are real content.
CONTENT_SELECTORS = (
    "main",
    "article",
    "[role='main']",
    "#mw-content-text",
    ".mw-parser-output",
    ".main-content",
    "#main-content",
    ".entry-content",
    ".post-content",
    ".article-body",
    ".content",
    "#content",
    ".post",
)

# Elements whose text forms one line of output. Only *leaf* blocks are emitted,
# so a `li` wrapping a `p` does not duplicate its own text. `tr` stands in for
# its cells so a table row stays one line instead of one line per cell.
BLOCK_TAGS = (
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "li", "dd", "dt", "blockquote", "pre", "figcaption", "caption", "tr",
)

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

CELL_TAGS = ("th", "td")

# Whole lines matching these are furniture, not prose. Matched against a whole
# line, never mid-sentence: substituting them globally used to delete the phrase
# "Privacy Policy" out of an article that was *about* privacy policies.
NOISE_LINE_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"^cookie policy$",
    r"^privacy policy$",
    r"^terms of (service|use)$",
    r"^accept (all )?cookies$",
    r"^we use cookies\b.*",
    r"^(share|tweet|print|email) this\b.*",
    r"^(read|edit|view history|view source)$",
    r"^jump to (content|navigation|search)$",
    r"^\[?edit\]?$",
    r"^\d+(\.\d+)*$",
    r"^\^.*",
    r"^retrieved \d",
    r"^（?原始內容存檔於.*",
))

# Markers of a bibliography entry. A line carrying several of them is a citation
# even when the reference container was not matched by a selector.
CITATION_MARKERS = ("doi:", "arxiv:", "isbn", "issn", "s2cid", "bibcode", "pmid",
                    "原始內容", "存檔於", "[永久失效連結]")

# A block-level walk misses text that a site puts straight inside a `div`. When
# the walk recovers less than this share of the container's own text, fall back
# to flattening every line instead of silently dropping content.
BLOCK_COVERAGE_FLOOR = 0.4


class URLAdapter:
    """Adapter for extracting content from URLs."""

    def __init__(
        self,
        timeout: int = 30,
        use_readability: bool = True,
        resolver: Callable = socket.getaddrinfo,
        session=None,
        connect_timeout: int = 5,
        max_download_bytes: int = MAX_URL_DOWNLOAD_BYTES,
        max_redirects: int = MAX_URL_REDIRECTS,
        max_download_seconds: int = 30,
        clock: Callable[[], float] = time.monotonic,
        executor: Optional[Executor] = None,
    ):
        """Initialize URL adapter.

        Args:
            timeout: Request timeout in seconds
            use_readability: Whether to fall back to readability when the page
                exposes no recognisable content container.
            resolver: DNS resolver compatible with ``socket.getaddrinfo``.
            session: Optional requests-like session for tests. Production uses
                a DNS-pinned session per request.
            connect_timeout: Socket connection timeout in seconds.
            max_download_bytes: Maximum decompressed response bytes.
            max_redirects: Maximum manually validated redirects.
            max_download_seconds: Total wall-clock cap across redirects/body.
            clock: Monotonic seconds provider, injectable for tests.
            executor: Optional fixed-size executor. Production shares a bounded
                process-wide pool so stalled DNS cannot create one thread per
                request.
        """
        _require_supported_requests_transport()
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.use_readability = use_readability and HAS_READABILITY
        self.resolver = resolver
        self.session = session
        self.max_download_bytes = max_download_bytes
        self.max_redirects = max_redirects
        self.max_download_seconds = max_download_seconds
        self.clock = clock
        self.executor = executor or _URL_DOWNLOAD_EXECUTOR
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def extract_content(self, url: str) -> Dict[str, any]:
        """Extract content from a URL.

        Args:
            url: URL to extract content from

        Returns:
            Dictionary containing extracted content and metadata
        """
        return self.start_extract_content(url).result()

    def start_extract_content(self, url: str) -> URLFetchOperation:
        """Submit extraction to the fixed worker pool without waiting.

        Args:
            url: User-supplied URL to validate and extract.

        Returns:
            Operation exposing both the bounded wait and actual worker future.
        """
        control = _FetchControl()
        future = self.executor.submit(self._extract_content, url, control)
        return URLFetchOperation(future, control, self.max_download_seconds)

    def _extract_content(self, url: str, control: _FetchControl) -> Dict[str, any]:
        """Run validation, download, and parsing inside one bounded worker."""
        try:
            final_url, body = self._download(url, control)

            # Parse with BeautifulSoup
            soup = BeautifulSoup(body, 'html.parser')

            # Read metadata before pruning, so <title> and <meta> survive
            metadata = self._extract_metadata(soup, final_url)

            self._strip_non_content(soup)
            self._inline_math(soup)

            content = self._extract_main_content(soup, final_url)

            # Extract headings structure from the pruned document
            headings = self._extract_headings(soup)

            return {
                "url": final_url,
                "title": metadata.get("title", ""),
                "text": content["text"],
                "html": content.get("html", ""),
                "metadata": metadata,
                "headings": headings,
                "links": self._extract_links(soup, final_url),
            }

        except requests.RequestException as e:
            logger.error("Failed to fetch URL", url=url, error=str(e))
            raise
        except Exception as e:
            logger.error("Failed to extract content from URL", url=url, error=str(e))
            raise

    def _download(self, url: str, control: _FetchControl):
        """Download a validated response while checking every redirect hop.

        Args:
            url: Initial user-supplied URL.
            control: Cancellation registry for this extraction.

        Returns:
            A pair of final normalized URL and its capped body bytes.

        Raises:
            UnsafeURLError: If a hop, content type, redirect count, or body size
                violates the import policy.
        """
        current_url = url
        redirect_count = 0
        started_at = self.clock()

        while True:
            control.raise_if_cancelled()
            self._ensure_within_time_limit(started_at)
            current_url, addresses = resolve_public_http_url(
                current_url,
                resolver=self.resolver,
            )
            control.raise_if_cancelled()
            response = self._request(current_url, addresses, control)
            control.register(response)
            try:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("Location")
                    if not location:
                        raise UnsafeURLError("Redirect response has no destination")
                    if redirect_count >= self.max_redirects:
                        raise UnsafeURLError("URL exceeded the redirect limit")
                    current_url = urljoin(current_url, location)
                    redirect_count += 1
                    continue

                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                if media_type not in ACCEPTED_CONTENT_TYPES:
                    raise UnsafeURLError("URL response content type is not accepted")

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_bytes = int(content_length)
                    except ValueError as exc:
                        raise UnsafeURLError("URL response has invalid Content-Length") from exc
                    if declared_bytes > self.max_download_bytes:
                        raise UnsafeURLError(
                            "URL response exceeds the %sMB limit"
                            % self._download_limit_mb()
                        )

                body = bytearray()
                for block in response.iter_content(chunk_size=URL_STREAM_BLOCK_BYTES):
                    self._ensure_within_time_limit(started_at)
                    if not block:
                        continue
                    if len(body) + len(block) > self.max_download_bytes:
                        raise UnsafeURLError(
                            "URL response exceeds the %sMB limit"
                            % self._download_limit_mb()
                        )
                    body.extend(block)
                self._ensure_within_time_limit(started_at)
                return current_url, bytes(body)
            finally:
                response.close()
                control.unregister(response)
                owned_session = getattr(response, "_opennotebook_session", None)
                if owned_session is not None:
                    owned_session.close()
                    control.unregister(owned_session)

    def _ensure_within_time_limit(self, started_at: float) -> None:
        """Refuse a download whose total wall-clock cap has elapsed.

        Args:
            started_at: Monotonic timestamp captured before URL validation.

        Raises:
            UnsafeURLError: If the configured total duration is exceeded.
        """
        if self.clock() - started_at > self.max_download_seconds:
            raise UnsafeURLError("URL download exceeded the time limit")

    def _request(
        self,
        url: str,
        addresses: List[str],
        control: _FetchControl,
    ):
        """Open one streamed request pinned to the validated DNS result.

        Args:
            url: Normalized destination URL.
            addresses: Public IP strings resolved during validation.
            control: Cancellation registry for this extraction.

        Returns:
            A streamed requests response.
        """
        options = {
            "headers": self.headers,
            "timeout": (self.connect_timeout, self.timeout),
            "stream": True,
            "allow_redirects": False,
        }
        if self.session is not None:
            control.register(self.session)
            control.raise_if_cancelled()
            return self.session.get(url, **options)

        last_error = None
        scheme = urlparse(url).scheme
        for address in addresses:
            session = requests.Session()
            session.trust_env = False
            control.register(session)
            session.mount(
                scheme + "://",
                _PinnedHTTPAdapter(address, fetch_control=control),
            )
            try:
                control.raise_if_cancelled()
                response = session.get(url, **options)
            except requests.RequestException as exc:
                session.close()
                control.unregister(session)
                last_error = exc
                continue
            response._opennotebook_session = session
            return response

        if last_error is not None:
            raise last_error
        raise UnsafeURLError("URL hostname resolved to no usable address")

    def _download_limit_mb(self):
        """Return the configured cap in compact user-facing mebibytes."""
        mebibyte = 1024 * 1024
        if self.max_download_bytes % mebibyte == 0:
            return self.max_download_bytes // mebibyte
        return self.max_download_bytes / mebibyte

    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, str]:
        """Extract metadata from HTML."""
        metadata = {
            "url": url,
            "domain": urlparse(url).netloc,
        }

        # Title
        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text().strip()

        # Meta tags
        meta_tags = soup.find_all("meta")
        for tag in meta_tags:
            # Description
            if tag.get("name") == "description":
                metadata["description"] = tag.get("content", "")
            # Keywords
            elif tag.get("name") == "keywords":
                metadata["keywords"] = tag.get("content", "")
            # Author
            elif tag.get("name") == "author":
                metadata["author"] = tag.get("content", "")
            # Open Graph
            elif tag.get("property") == "og:title":
                metadata["og_title"] = tag.get("content", "")
            elif tag.get("property") == "og:description":
                metadata["og_description"] = tag.get("content", "")
            elif tag.get("property") == "og:image":
                metadata["og_image"] = tag.get("content", "")

        return metadata

    def _strip_non_content(self, soup: BeautifulSoup) -> None:
        """Remove furniture from the parsed document, in place.

        Args:
            soup: Parsed document, modified in place.
        """
        for selector in NON_CONTENT_SELECTORS:
            for node in soup.select(selector):
                node.decompose()

    def _inline_math(self, soup: BeautifulSoup) -> None:
        """Collapse rendered math into inline text, in place.

        A MathML element carries an image plus a TeX annotation. Left alone it
        becomes its own output line, so a sentence with three symbols in it turns
        into four lines of one or two characters each. Folding the TeX back
        inline keeps the sentence whole.

        Args:
            soup: Parsed document, modified in place.
        """
        for node in soup.select(".mwe-math-element, math"):
            annotation = node.find("annotation")
            tex = annotation.get_text() if annotation else node.get_text()
            tex = re.sub(r"^\s*\{\\displaystyle\s*(.*)\}\s*$", r"\1", tex, flags=re.S)
            collapsed = " ".join(tex.split())
            node.replace_with(NavigableString(" " + collapsed + " " if collapsed else " "))

    def _find_content_container(self, soup: BeautifulSoup):
        """Return the first recognisable content container, if any.

        Args:
            soup: Pruned document.

        Returns:
            The matching element, or None.
        """
        for selector in CONTENT_SELECTORS:
            container = soup.select_one(selector)
            if container and container.get_text(strip=True):
                return container
        return None

    def _extract_main_content(self, soup: BeautifulSoup, url: str) -> Dict[str, str]:
        """Pick the best available extraction strategy for this page.

        Args:
            soup: Pruned document.
            url: Source URL, for logging.

        Returns:
            Dictionary with `text` and `html`.
        """
        container = self._find_content_container(soup)
        if container is not None:
            return {
                "text": self._clean_text(self._html_to_text(container)),
                "html": str(container),
            }

        if self.use_readability:
            readability_result = self._extract_with_readability(str(soup), url)
            if readability_result is not None:
                return readability_result

        body = soup.body if soup.body else soup
        return {
            "text": self._clean_text(self._html_to_text(body)),
            "html": str(body),
        }

    def _extract_with_readability(self, html: str, url: str) -> Optional[Dict[str, str]]:
        """Extract content with readability's text-density heuristic.

        Only used for pages with no recognisable content container, because
        readability discards tables.

        Args:
            html: Pruned page HTML.
            url: Source URL, for logging.

        Returns:
            Dictionary with `text`, `html` and `title`, or None if it produced
            nothing usable.
        """
        try:
            doc = ReadabilityDocument(html)
            summary = doc.summary(html_partial=True)

            soup = BeautifulSoup(summary, 'html.parser')
            text = self._clean_text(self._html_to_text(soup))

            if not text:
                raise ValueError("readability returned no text")

            return {"text": text, "html": summary, "title": doc.short_title()}
        except Exception as e:
            logger.warning("Readability extraction failed", url=url, error=str(e))
            return None

    def _extract_with_beautifulsoup(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract content from an unpruned document.

        Kept as the standalone entry point for callers that hand over raw soup.

        Args:
            soup: Parsed document.

        Returns:
            Dictionary with `text` and `html`.
        """
        self._strip_non_content(soup)
        self._inline_math(soup)
        return self._extract_main_content(soup, "")

    def _html_to_text(self, root) -> str:
        """Flatten HTML to text, one line per block and headings kept as Markdown.

        Two details matter for retrieval. Headings are emitted as `## Heading` so
        the chunker can rebuild a section path — the previous extractor dropped
        that structure and every chunk lost its context. And inline elements are
        joined with no separator: `get_text(separator=...)` puts one between
        every `<a>` and its neighbour, which lands *inside* Chinese sentences and
        splits a term in two.

        Args:
            root: Element to flatten.

        Returns:
            Text with newlines between blocks.
        """
        lines: List[str] = []
        for element in root.find_all(BLOCK_TAGS):
            if element.find(BLOCK_TAGS):
                # Not a leaf block; its children are emitted on their own.
                continue

            if element.name == "tr":
                cells = [
                    self._collapse(cell.get_text())
                    for cell in element.find_all(CELL_TAGS)
                ]
                text = " | ".join(cell for cell in cells if cell)
            else:
                text = self._collapse(element.get_text())

            if not text:
                continue

            if element.name in HEADING_TAGS:
                level = int(element.name[1])
                lines.append("")
                lines.append("#" * level + " " + text)
                lines.append("")
            else:
                lines.append(text)

        text = "\n".join(lines)

        # A site that puts prose straight inside a div exposes no leaf block, so
        # the walk above would return almost nothing. Detect that and flatten.
        whole = self._collapse(root.get_text(" "))
        if whole and len(self._collapse(text.replace("\n", " "))) < BLOCK_COVERAGE_FLOOR * len(whole):
            logger.info("Block walk covered too little text, flattening instead")
            return root.get_text("\n", strip=True)

        return text

    @staticmethod
    def _collapse(text: str) -> str:
        """Collapse horizontal whitespace and trim.

        Args:
            text: Any text.

        Returns:
            Text with runs of spaces and tabs reduced to one space.
        """
        return re.sub(r"[^\S\n]+", " ", text).replace("\n", " ").strip()

    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict[str, any]]:
        """Extract heading structure from HTML."""
        headings = []

        for heading in soup.find_all(HEADING_TAGS):
            text = heading.get_text(strip=True)
            if not text:
                continue
            headings.append({
                "level": int(heading.name[1]),
                "text": text,
                "tag": heading.name,
            })

        return headings

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract links from HTML."""
        links = []
        base_domain = urlparse(base_url).netloc

        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True)

            # Skip empty links
            if not href or href == '#':
                continue

            # Determine if internal or external
            parsed = urlparse(href)
            is_internal = not parsed.netloc or parsed.netloc == base_domain

            links.append({
                "href": href,
                "text": text[:100],  # Limit text length
                "is_internal": is_internal,
            })

        return links[:100]  # Limit to 100 links

    def _is_noise_line(self, line: str) -> bool:
        """Whether a whole line is furniture rather than prose.

        Args:
            line: One line of extracted text.

        Returns:
            True if the line should be dropped.
        """
        if any(pattern.match(line) for pattern in NOISE_LINE_PATTERNS):
            return True

        lowered = line.lower()
        markers = sum(1 for marker in CITATION_MARKERS if marker in lowered)
        return markers >= 2

    def _clean_text(self, text: str) -> str:
        """Clean extracted text.

        Line-based filtering runs *before* whitespace is normalised. The previous
        order collapsed every newline first, which left the header/footer and
        blank-line rules below matching against a single line — they could never
        fire.

        Args:
            text: Text produced by `_html_to_text`.

        Returns:
            Cleaned text with paragraph breaks preserved.
        """
        cleaned: List[str] = []
        for raw_line in text.split("\n"):
            line = self._collapse(raw_line)

            if not line:
                cleaned.append("")
                continue

            if self._is_noise_line(line):
                continue

            cleaned.append(line)

        text = "\n".join(cleaned)

        # Collapse runs of blank lines to a single paragraph break
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()
