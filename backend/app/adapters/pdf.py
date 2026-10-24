"""PDF processing adapter."""
import io
import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path
import structlog
import numpy as np

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
from app.adapters.ocr import (
    InvalidImageError,
    MAX_OCR_IMAGE_PIXELS,
    OCRAdapter,
)

logger = structlog.get_logger()

# A whole line that is a page label, e.g. "Page 7 of 12".
PAGE_LABEL_RE = re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.IGNORECASE)

# Digits and the punctuation a page number is usually dressed in. A line left
# empty by removing these was nothing but a page number.
PAGE_DECORATION_RE = re.compile(r"[\d\s\-–—.·|/()\[\]]+")
OCR_RENDER_DPI = 200
MAX_OCR_PAGES_PER_DOCUMENT = 20
OCR_MIN_PAGE_IMAGE_COVERAGE = 0.5
OCR_IMAGE_COVERAGE_GRID_SIZE = 64


class OCRPageLimitError(ValueError):
    """Raised when a PDF has more scanned pages than this worker can OCR."""


class PDFAdapter:
    """Adapter for processing PDF files."""
    
    def __init__(
        self,
        use_pymupdf: bool = True,
        ocr_adapter: Optional[OCRAdapter] = None,
        ocr_enabled: bool = True,
        max_ocr_pages: int = MAX_OCR_PAGES_PER_DOCUMENT,
    ):
        """Initialize PDF adapter.
        
        Args:
            use_pymupdf: Whether to use PyMuPDF (True) or pdfminer (False)
            ocr_adapter: Optional local OCR implementation for scanned pages.
            ocr_enabled: Whether scanned pages may be rendered and OCRed.
            max_ocr_pages: Maximum textless pages to OCR in one document.

        Returns:
            None.
        """
        self.use_pymupdf = use_pymupdf and HAS_PYMUPDF
        self.ocr_adapter = ocr_adapter or OCRAdapter("./models/rapidocr")
        self.ocr_enabled = ocr_enabled
        self.max_ocr_pages = max_ocr_pages
        
        if not HAS_PYMUPDF and not HAS_PDFMINER:
            raise ImportError("No PDF library available. Install PyMuPDF or pdfminer.six")
    
    def extract_text_from_file(self, file_path: str) -> Dict[str, Any]:
        """Extract text from a PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        return self.extract_with_ocr(file_path)

    def extract_with_ocr(self, file_path: str) -> Dict[str, Any]:
        """Extract normal PDF text and OCR scanned pages with no text layer.

        Args:
            file_path: Path to the PDF file.

        Returns:
            Normal PDF extraction metadata with OCR text on scanned pages.
        """
        if self.use_pymupdf:
            result = self._extract_file_with_fallback(
                primary=lambda: self._extract_with_pymupdf(file_path),
                fallback=(
                    lambda: self._extract_with_pdfminer(file_path)
                ) if HAS_PDFMINER else None,
                primary_parser="pymupdf",
                fallback_parser="pdfminer",
            )
        else:
            result = self._extract_file_with_fallback(
                primary=lambda: self._extract_with_pdfminer(file_path),
                fallback=(
                    lambda: self._extract_with_pymupdf(file_path)
                ) if HAS_PYMUPDF else None,
                primary_parser="pdfminer",
                fallback_parser="pymupdf",
            )

        return self._ocr_scanned_pages(file_path, result)

    def _ocr_scanned_pages(
        self,
        file_path: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """OCR only pages with no extracted text and substantial raster content."""
        if not self.ocr_enabled or not HAS_PYMUPDF:
            return result

        pages = result.get("pages", [])
        textless_pages = [
            index
            for index, page in enumerate(pages)
            if not str(page.get("text") or "").strip()
        ]
        if not textless_pages:
            return result

        max_image_pixels = getattr(
            self.ocr_adapter,
            "max_image_pixels",
            MAX_OCR_IMAGE_PIXELS,
        )
        scale = OCR_RENDER_DPI / 72.0
        document = fitz.open(file_path)
        try:
            # Photo-heavy slides can still have a searchable title, so only
            # textless pages reach this raster-coverage check.
            candidates = [
                index
                for index in textless_pages
                if self._has_scan_sized_image(
                    document.load_page(index),
                )
            ]
            if not candidates:
                return result
            if len(candidates) > self.max_ocr_pages:
                raise OCRPageLimitError(
                    "This PDF has %d scan pages with no searchable text; OCR can "
                    "process at most %d pages per document."
                    % (len(candidates), self.max_ocr_pages)
                )

            for page_index in candidates:
                page_info = pages[page_index]
                page_number = int(page_info.get("page_num") or page_index + 1)
                pdf_page = document.load_page(page_number - 1)
                width_pixels = math.ceil(pdf_page.rect.width * scale)
                height_pixels = math.ceil(pdf_page.rect.height * scale)
                if width_pixels * height_pixels > max_image_pixels:
                    raise InvalidImageError(
                        "PDF page %d exceeds the image safety limit of %s pixels"
                        % (page_number, format(max_image_pixels, ","))
                    )

                pixmap = pdf_page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                rendered = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    pixmap.n,
                )
                if pixmap.n == 4:
                    rendered = rendered[:, :, :3]
                recognized_text = self.ocr_adapter.recognize_image(rendered)
                existing_text = str(page_info.get("text") or "").strip()
                combined_text = "\n".join(
                    text for text in (existing_text, recognized_text.strip()) if text
                )
                page_info["text"] = combined_text
                page_info["char_count"] = len(combined_text)
        finally:
            document.close()

        metadata = dict(result.get("metadata") or {})
        metadata.update({
            "ocr_engine": "RapidOCR",
            "ocr_pages": len(candidates),
            "ocr_page_limit": self.max_ocr_pages,
        })
        result["metadata"] = metadata
        result["text"] = PAGE_SEPARATOR.join(
            str(page.get("text") or "") for page in pages
        )
        return result

    @staticmethod
    def _has_scan_sized_image(page: Any) -> bool:
        """Check for a raster image that covers a substantial part of a page.

        Args:
            page: An open PyMuPDF page.

        Returns:
            Whether visible images cover at least half of the page area.
        """
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        if page_area <= 0:
            return False

        # Sampling the union keeps tiled scans recognizable without counting
        # overlapping image objects more than once or doing pairwise geometry.
        grid_size = OCR_IMAGE_COVERAGE_GRID_SIZE
        coverage_grid = np.zeros((grid_size, grid_size), dtype=bool)
        covered_cells = 0
        scale_x = grid_size / page_rect.width
        scale_y = grid_size / page_rect.height
        for image_info in page.get_images(full=True):
            image_xref = int(image_info[0])
            if image_xref <= 0:
                continue
            for image_rect in page.get_image_rects(image_xref):
                visible_rect = image_rect & page_rect
                if visible_rect.width <= 0 or visible_rect.height <= 0:
                    continue

                # Only cells whose centers lie inside an image count as covered.
                column_start = max(
                    0,
                    math.ceil((visible_rect.x0 - page_rect.x0) * scale_x - 0.5),
                )
                column_end = min(
                    grid_size,
                    math.ceil((visible_rect.x1 - page_rect.x0) * scale_x - 0.5),
                )
                row_start = max(
                    0,
                    math.ceil((visible_rect.y0 - page_rect.y0) * scale_y - 0.5),
                )
                row_end = min(
                    grid_size,
                    math.ceil((visible_rect.y1 - page_rect.y0) * scale_y - 0.5),
                )
                if column_start >= column_end or row_start >= row_end:
                    continue

                covered = coverage_grid[row_start:row_end, column_start:column_end]
                covered_cells += covered.size - int(np.count_nonzero(covered))
                covered[:] = True
                if covered_cells / coverage_grid.size >= OCR_MIN_PAGE_IMAGE_COVERAGE:
                    return True
        return False

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
