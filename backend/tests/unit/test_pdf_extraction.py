"""Regression tests for PDF text extraction fallbacks."""
import json
from pathlib import Path

import fitz

from app.adapters import pdf as pdf_module
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
