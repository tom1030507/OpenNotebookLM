"""Regression tests for PDF text extraction fallbacks."""
from io import BytesIO
import json
from pathlib import Path

import fitz
from PIL import Image
import pytest

from app.adapters import pdf as pdf_module
from app.adapters.ocr import InvalidImageError
from app.adapters.pdf import PDFAdapter


def _write_nested_text_pdf(path: Path) -> None:
    """Write text inside a Form XObject instead of the page's top-level layout.

    Args:
        path: Destination for the generated PDF.

    Returns:
        None.
    """
    source = fitz.open()
    source_page = source.new_page()
    source_page.insert_text((72, 72), "Nested searchable text")

    document = fitz.open()
    page = document.new_page()
    page.show_pdf_page(page.rect, source, 0)
    document.save(path)

    document.close()
    source.close()


def test_pdfminer_empty_result_falls_back_to_pymupdf(tmp_path):
    """Nested text remains searchable when the primary parser returns empty."""
    pdf_path = tmp_path / "nested-text.pdf"
    _write_nested_text_pdf(pdf_path)
    adapter = PDFAdapter(use_pymupdf=False)

    primary_result = adapter._extract_with_pdfminer(pdf_path)
    result = adapter.extract_text_from_file(pdf_path)

    assert primary_result["text"].strip() == ""
    assert result["text"].strip() == "Nested searchable text"
    assert result["num_pages"] == 1
    assert result["pages"][0]["char_count"] == len("Nested searchable text")


def test_pdfminer_failure_falls_back_to_pymupdf(tmp_path, monkeypatch):
    """A parser-specific exception does not reject an otherwise readable PDF."""
    pdf_path = tmp_path / "primary-parser-failure.pdf"
    _write_nested_text_pdf(pdf_path)
    adapter = PDFAdapter(use_pymupdf=False)

    def fail_pdfminer(_file_path):
        raise RuntimeError("pdfminer could not decode this document")

    monkeypatch.setattr(adapter, "_extract_with_pdfminer", fail_pdfminer)

    result = adapter.extract_text_from_file(pdf_path)

    assert result["text"].strip() == "Nested searchable text"


def test_fallback_page_metadata_is_json_serializable(tmp_path):
    """Fallback metadata can be persisted in the document JSON column."""
    pdf_path = tmp_path / "serializable-metadata.pdf"
    _write_nested_text_pdf(pdf_path)

    result = PDFAdapter(use_pymupdf=False).extract_text_from_file(pdf_path)

    persisted = json.loads(json.dumps(result))
    assert persisted["pages"][0]["bbox"] == [0, 0, 595, 842]


def test_empty_result_is_preserved_when_no_fallback_is_installed(
    tmp_path,
    monkeypatch,
):
    """An unavailable alternate parser does not turn a valid result into None."""
    pdf_path = tmp_path / "no-fallback.pdf"
    _write_nested_text_pdf(pdf_path)
    monkeypatch.setattr(pdf_module, "HAS_PYMUPDF", False)
    adapter = PDFAdapter(use_pymupdf=False)

    result = adapter.extract_text_from_file(pdf_path)

    assert result["text"] == ""
    assert result["num_pages"] == 1


def _write_scanned_pdf(path: Path, page_count: int = 2, page_size=(72, 72)) -> None:
    """Write image-only PDF pages at a known one-inch size."""
    image_bytes = BytesIO()
    Image.new("RGB", (96, 96), "white").save(image_bytes, format="PNG")

    document = fitz.open()
    for _ in range(page_count):
        page = document.new_page(width=page_size[0], height=page_size[1])
        page.insert_image(page.rect, stream=image_bytes.getvalue())
    document.save(path)
    document.close()


class _PageOCR:
    """Return a page-specific line and retain rendered input dimensions."""

    max_image_pixels = 40_000_000

    def __init__(self):
        self.images = []

    def recognize_image(self, image):
        self.images.append(image)
        return "Recognized page %d" % len(self.images)


def test_scanned_two_page_pdf_uses_200_dpi_and_preserves_page_order(tmp_path):
    """Only rendered scan pages are OCRed and remain mapped to their PDF pages."""
    pdf_path = tmp_path / "scanned-two-pages.pdf"
    _write_scanned_pdf(pdf_path)
    ocr = _PageOCR()

    result = PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert [page["text"] for page in result["pages"]] == [
        "Recognized page 1",
        "Recognized page 2",
    ]
    assert [image.shape[:2] for image in ocr.images] == [(200, 200), (200, 200)]
    assert result["metadata"]["ocr_pages"] == 2
    assert result["text"].split("\n\n") == [
        "Recognized page 1",
        "Recognized page 2",
    ]


def test_tiled_scanned_page_uses_ocr(tmp_path):
    """Several raster tiles together identify a scanned PDF page."""
    pdf_path = tmp_path / "tiled-scan.pdf"
    page = fitz.open()
    pdf_page = page.new_page(width=72, height=72)
    tile_rectangles = (
        fitz.Rect(0, 0, 36, 36),
        fitz.Rect(36, 0, 72, 36),
        fitz.Rect(0, 36, 36, 72),
        fitz.Rect(36, 36, 72, 72),
    )
    for index, rectangle in enumerate(tile_rectangles):
        image_bytes = BytesIO()
        Image.new("RGB", (48, 48), (index * 60, 20, 20)).save(
            image_bytes,
            format="PNG",
        )
        pdf_page.insert_image(rectangle, stream=image_bytes.getvalue())
    page.save(pdf_path)
    page.close()
    ocr = _PageOCR()

    result = PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert result["pages"][0]["text"] == "Recognized page 1"
    assert len(ocr.images) == 1


def test_searchable_pdf_does_not_load_or_call_ocr(tmp_path):
    """A normal text PDF stays on the parser path with no OCR invocation."""
    pdf_path = tmp_path / "searchable.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "This page already contains searchable text.")
    document.save(pdf_path)
    document.close()
    ocr = _PageOCR()

    result = PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert "already contains searchable text" in result["text"]
    assert ocr.images == []
    assert "ocr_pages" not in result["metadata"]


def test_sparse_searchable_pages_do_not_trigger_ocr_or_page_cap(tmp_path):
    """Many pages with short native text remain on the normal PDF path."""
    pdf_path = tmp_path / "sparse-searchable.pdf"
    document = fitz.open()
    for page_num in range(1, 22):
        page = document.new_page()
        page.insert_text((72, 72), "Slide %d" % page_num)
    document.save(pdf_path)
    document.close()
    ocr = _PageOCR()

    result = PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert result["num_pages"] == 21
    assert result["pages"][0]["text"] == "Slide 1"
    assert result["pages"][-1]["text"] == "Slide 21"
    assert ocr.images == []
    assert "ocr_pages" not in result["metadata"]


def test_sparse_searchable_pages_with_raster_background_skip_ocr(tmp_path):
    """Short native text stays searchable without OCRing full-page photos."""
    pdf_path = tmp_path / "photo-background-slides.pdf"
    _write_scanned_pdf(pdf_path, page_count=21)
    with fitz.open(pdf_path) as document:
        for page_num, page in enumerate(document, start=1):
            page.insert_text((4, 12), "Slide %d" % page_num)
        document.saveIncr()
    ocr = _PageOCR()

    result = PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert result["num_pages"] == 21
    assert result["pages"][0]["text"] == "Slide 1"
    assert result["pages"][-1]["text"] == "Slide 21"
    assert ocr.images == []
    assert "ocr_pages" not in result["metadata"]


def test_mixed_pdf_keeps_searchable_text_and_adds_ocr_text(tmp_path):
    """OCR fills a scan page while preserving text extracted from other pages."""
    pdf_path = tmp_path / "mixed.pdf"
    _write_scanned_pdf(pdf_path, page_count=2, page_size=(300, 300))
    with fitz.open(pdf_path) as document:
        document[0].insert_text((20, 30), "This page already has searchable text.")
        document.saveIncr()
    ocr = _PageOCR()

    result = PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert "already has searchable text" in result["pages"][0]["text"]
    assert result["pages"][1]["text"] == "Recognized page 1"
    assert len(ocr.images) == 1


def test_ocr_disabled_pdf_skips_scanned_pages(tmp_path):
    """Disabling OCR preserves the ordinary empty extraction result."""
    pdf_path = tmp_path / "ocr-disabled.pdf"
    _write_scanned_pdf(pdf_path, page_count=1)
    ocr = _PageOCR()

    result = PDFAdapter(ocr_adapter=ocr, ocr_enabled=False).extract_text_from_file(
        str(pdf_path)
    )

    assert result["text"] == ""
    assert ocr.images == []


def test_pdf_page_above_pixel_cap_is_rejected_before_render(tmp_path):
    """A huge scanned page fails before PyMuPDF allocates its rendered pixels."""
    pdf_path = tmp_path / "huge-page.pdf"
    _write_scanned_pdf(pdf_path, page_count=1, page_size=(5000, 5000))
    ocr = _PageOCR()

    with pytest.raises(InvalidImageError, match="PDF page 1 exceeds the image safety limit"):
        PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert ocr.images == []


def test_more_than_20_scanned_pages_reports_the_cap(tmp_path):
    """The page cap appears in an error before an over-limit OCR job starts."""
    pdf_path = tmp_path / "too-many-scans.pdf"
    _write_scanned_pdf(pdf_path, page_count=21)
    ocr = _PageOCR()

    with pytest.raises(ValueError, match="at most 20 pages"):
        PDFAdapter(ocr_adapter=ocr).extract_text_from_file(str(pdf_path))

    assert ocr.images == []
