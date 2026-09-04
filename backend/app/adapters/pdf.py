"""PDF processing adapter."""
import io
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path
import structlog

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextBox
    HAS_PDFMINER = True
except ImportError:
    HAS_PDFMINER = False

from app.utils.text import PAGE_SEPARATOR

logger = structlog.get_logger()

# A whole line that is a page label, e.g. "Page 7 of 12".
PAGE_LABEL_RE = re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.IGNORECASE)

# Digits and the punctuation a page number is usually dressed in. A line left
# empty by removing these was nothing but a page number.
PAGE_DECORATION_RE = re.compile(r"[\d\s\-–—.·|/()\[\]]+")


class PDFAdapter:
    """Adapter for processing PDF files."""
    
    def __init__(self, use_pymupdf: bool = True):
        """Initialize PDF adapter.
        
        Args:
            use_pymupdf: Whether to use PyMuPDF (True) or pdfminer (False)
        """
        self.use_pymupdf = use_pymupdf and HAS_PYMUPDF
        
        if not HAS_PYMUPDF and not HAS_PDFMINER:
            raise ImportError("No PDF library available. Install PyMuPDF or pdfminer.six")
    
    def extract_text_from_file(self, file_path: str) -> Dict[str, Any]:
        """Extract text from a PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        if self.use_pymupdf:
            return self._extract_file_with_fallback(
                primary=lambda: self._extract_with_pymupdf(file_path),
                fallback=(
                    lambda: self._extract_with_pdfminer(file_path)
                ) if HAS_PDFMINER else None,
                primary_parser="pymupdf",
                fallback_parser="pdfminer",
            )

        return self._extract_file_with_fallback(
            primary=lambda: self._extract_with_pdfminer(file_path),
            fallback=(
                lambda: self._extract_with_pymupdf(file_path)
            ) if HAS_PYMUPDF else None,
            primary_parser="pdfminer",
            fallback_parser="pymupdf",
        )

    def _extract_file_with_fallback(
        self,
        primary: Callable[[], Dict[str, Any]],
        fallback: Optional[Callable[[], Dict[str, Any]]],
        primary_parser: str,
        fallback_parser: str,
    ) -> Dict[str, Any]:
        """Try the alternate parser when the preferred one cannot find text."""
        try:
            result = primary()
        except Exception as error:
            if fallback is None:
                raise
            logger.warning(
                "Primary PDF parser failed; trying fallback",
                primary_parser=primary_parser,
                fallback_parser=fallback_parser,
                error=str(error),
            )
            return fallback()

        if str(result.get("text") or "").strip() or fallback is None:
            return result

        # Some valid PDFs place every glyph inside a Form XObject. pdfminer can
        # expose those glyphs without grouping them into the top-level text
        # boxes this adapter reads, so an empty result is parser-specific rather
        # than proof that the document needs OCR.
        logger.warning(
            "Primary PDF parser found no text; trying fallback",
            primary_parser=primary_parser,
            fallback_parser=fallback_parser,
        )
        return fallback()
    
    def extract_text_from_bytes(self, pdf_bytes: bytes) -> Dict[str, Any]:
        """Extract text from PDF bytes.
        
        Args:
            pdf_bytes: PDF file content as bytes
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        if self.use_pymupdf:
            return self._extract_bytes_with_pymupdf(pdf_bytes)
        else:
            return self._extract_bytes_with_pdfminer(pdf_bytes)
    
    def _extract_with_pymupdf(self, file_path: str) -> Dict[str, Any]:
        """Extract text using PyMuPDF."""
        try:
            doc = fitz.open(file_path)
            pages = []
            full_text = []
            
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text()
                
                # Clean up text
                text = self._clean_text(text)
                bbox = page.rect.irect
                
                pages.append({
                    "page_num": page_num,
                    "text": text,
                    "char_count": len(text),
                    # SQLAlchemy's JSON serializer cannot persist PyMuPDF's
                    # IRect object, which would fail ingestion after fallback.
                    "bbox": [bbox.x0, bbox.y0, bbox.x1, bbox.y1],
                })
                full_text.append(text)
            
            metadata = doc.metadata or {}
            doc.close()
            
            return {
                "text": "\n\n".join(full_text),
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {
                    "title": metadata.get("title", ""),
                    "author": metadata.get("author", ""),
                    "subject": metadata.get("subject", ""),
                    "keywords": metadata.get("keywords", ""),
                    "creator": metadata.get("creator", ""),
                    "producer": metadata.get("producer", ""),
                }
            }
        except Exception as e:
            logger.error("Failed to extract text with PyMuPDF", error=str(e))
            raise
    
    def _extract_bytes_with_pymupdf(self, pdf_bytes: bytes) -> Dict[str, Any]:
        """Extract text from bytes using PyMuPDF."""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages = []
            full_text = []
            
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text()
                text = self._clean_text(text)
                
                pages.append({
                    "page_num": page_num,
                    "text": text,
                    "char_count": len(text),
                })
                full_text.append(text)
            
            metadata = doc.metadata or {}
            doc.close()
            
            return {
                "text": "\n\n".join(full_text),
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {
                    "title": metadata.get("title", ""),
                    "author": metadata.get("author", ""),
                    "subject": metadata.get("subject", ""),
                }
            }
        except Exception as e:
            logger.error("Failed to extract text from bytes with PyMuPDF", error=str(e))
            raise
    
    def _extract_with_pdfminer(self, file_path: str) -> Dict[str, Any]:
        """Extract text using pdfminer."""
        try:
            # Build the document text by joining the pages, rather than parsing
            # the file a second time with extract_text(). `text` is then exactly
            # the pages joined by a blank line, which is what lets the chunker
            # map a chunk's offset to its real page instead of guessing.
            pages = []
            laparams = LAParams()

            for page_num, page_layout in enumerate(extract_pages(file_path, laparams=laparams), start=1):
                page_text = []
                for element in page_layout:
                    if isinstance(element, LTTextBox):
                        page_text.append(element.get_text())

                page_content = self._clean_text("".join(page_text))

                pages.append({
                    "page_num": page_num,
                    "text": page_content,
                    "char_count": len(page_content),
                })

            return {
                "text": PAGE_SEPARATOR.join(page["text"] for page in pages),
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {}  # pdfminer doesn't extract metadata easily
            }
        except Exception as e:
            logger.error("Failed to extract text with pdfminer", error=str(e))
            raise
    
    def _extract_bytes_with_pdfminer(self, pdf_bytes: bytes) -> Dict[str, Any]:
        """Extract text from bytes using pdfminer."""
        try:
            # Create a file-like object from bytes
            pdf_file = io.BytesIO(pdf_bytes)

            # As in _extract_with_pdfminer: one parse, and `text` is the pages
            # joined, so chunk offsets locate their page exactly.
            pages = []
            laparams = LAParams()

            for page_num, page_layout in enumerate(extract_pages(pdf_file, laparams=laparams), start=1):
                page_text = []
                for element in page_layout:
                    if isinstance(element, LTTextBox):
                        page_text.append(element.get_text())

                page_content = self._clean_text("".join(page_text))

                pages.append({
                    "page_num": page_num,
                    "text": page_content,
                    "char_count": len(page_content),
                })

            return {
                "text": PAGE_SEPARATOR.join(page["text"] for page in pages),
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {}
            }
        except Exception as e:
            logger.error("Failed to extract text from bytes with pdfminer", error=str(e))
            raise
    
    def _is_running_header(self, line: str) -> bool:
        """Whether a whole line is a page number or a running footer.

        Matches a line that is nothing but a number with decoration — "12",
        "- 3 -", "[4]", "Page 7 of 12". The previous rule was "a short line
        containing a digit", which both missed the decorated forms and discarded
        real content such as "H2O".

        Args:
            line: One line of extracted text.

        Returns:
            True if the line should be dropped.
        """
        if not line:
            return False
        if PAGE_LABEL_RE.match(line):
            return True
        return not PAGE_DECORATION_RE.sub("", line) and any(c.isdigit() for c in line)

    def _clean_text(self, text: str) -> str:
        """Clean extracted text.

        Order matters here. `re.sub(r'\\s+', ' ', text)` used to run first, which
        deleted every newline and left the header/footer rule below matching
        against a single line — it could never fire, so running headers and page
        numbers were repeated into every chunk.

        Args:
            text: Raw extracted text

        Returns:
            Cleaned text
        """
        # Rejoin words the layout broke across lines, before the line structure
        # that reveals them is gone.
        text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)

        cleaned_lines = []
        for raw_line in text.split('\n'):
            # Collapse horizontal whitespace only; the newlines stay meaningful.
            line = re.sub(r'[^\S\n]+', ' ', raw_line).strip()

            if self._is_running_header(line):
                continue

            cleaned_lines.append(line)

        text = '\n'.join(cleaned_lines)

        # Remove multiple consecutive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()
    
    def extract_with_ocr(self, file_path: str) -> Dict[str, Any]:
        """Extract text using OCR (placeholder for future implementation).
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        # This would use libraries like pytesseract or cloud OCR services
        raise NotImplementedError("OCR extraction not yet implemented")
