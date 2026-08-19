"""URL content extraction adapter."""
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse
import structlog
import requests
from bs4 import BeautifulSoup, NavigableString

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

    def __init__(self, timeout: int = 30, use_readability: bool = True):
        """Initialize URL adapter.

        Args:
            timeout: Request timeout in seconds
            use_readability: Whether to fall back to readability when the page
                exposes no recognisable content container
        """
        self.timeout = timeout
        self.use_readability = use_readability and HAS_READABILITY
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
        try:
            # Fetch the page
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            # Parse with BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')

            # Read metadata before pruning, so <title> and <meta> survive
            metadata = self._extract_metadata(soup, url)

            self._strip_non_content(soup)
            self._inline_math(soup)

            content = self._extract_main_content(soup, url)

            # Extract headings structure from the pruned document
            headings = self._extract_headings(soup)

            return {
                "url": url,
                "title": metadata.get("title", ""),
                "text": content["text"],
                "html": content.get("html", ""),
                "metadata": metadata,
                "headings": headings,
                "links": self._extract_links(soup, url),
            }

        except requests.RequestException as e:
            logger.error("Failed to fetch URL", url=url, error=str(e))
            raise
        except Exception as e:
            logger.error("Failed to extract content from URL", url=url, error=str(e))
            raise

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
