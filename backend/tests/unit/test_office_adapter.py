"""Tests for local text and Office source extraction."""
from pathlib import Path
import zipfile

import pytest

from app.adapters.office import (
    InvalidOfficeFileError,
    OfficeAdapter,
)


def write_docx(path: Path, document_xml: str | None = None) -> None:
    """Create a small OpenXML Word document without storing a binary fixture."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            document_xml or (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                '<w:r><w:t>Chapter One</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Useful paragraph content.</w:t></w:r></w:p>'
                '<w:sectPr/></w:body></w:document>'
            ),
        )


def write_epub(path: Path) -> None:
    """Create a minimal EPUB 3 package with one chapter."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="book-id">book</dc:identifier><dc:title>Sample Book</dc:title>'
            '<dc:language>en</dc:language></metadata><manifest>'
            '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
            '</manifest><spine><itemref idref="chapter"/></spine></package>',
        )
        archive.writestr(
            "OEBPS/chapter.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title></head>'
            '<body><h1>Book Chapter</h1><p>EPUB chapter content.</p></body></html>',
        )


def result_for(path: Path) -> dict:
    """Extract a generated fixture through the production adapter."""
    return OfficeAdapter().extract_text_from_file(str(path))


def test_text_and_markdown_are_utf8_decoded_with_replacement(tmp_path):
    """Plain text input remains local and malformed UTF-8 stays readable."""
    text_path = tmp_path / "notes.txt"
    text_path.write_bytes(b"first line\n\xffsecond line")
    markdown_path = tmp_path / "guide.md"
    markdown_path.write_text("# Guide\n\nA useful section.", encoding="utf-8")

    text_result = result_for(text_path)
    markdown_result = result_for(markdown_path)

    assert "first line\n\ufffdsecond line" == text_result["text"]
    assert "# Guide" in markdown_result["text"]
    assert text_result["pages"] == []
    assert text_result["num_pages"] == 0
    assert set(text_result) == {"text", "pages", "num_pages", "metadata"}


def test_docx_heading_style_becomes_markdown_heading(tmp_path):
    """Word heading styles survive conversion for section citations."""
    path = tmp_path / "report.docx"
    write_docx(path)

    result = result_for(path)

    assert "# Chapter One" in result["text"]
    assert "Useful paragraph content." in result["text"]


def test_pptx_has_one_markdown_heading_per_slide(tmp_path):
    """Each slide title is a heading that can become a citation section."""
    from pptx import Presentation

    path = tmp_path / "deck.pptx"
    presentation = Presentation()
    for title in ("Opening", "Findings"):
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])
        slide.shapes.title.text = title
        slide.placeholders[1].text = "Slide body text"
    presentation.save(path)

    text = result_for(path)["text"]

    assert "## Slide 1: Opening" in text
    assert "## Slide 2: Findings" in text
    assert text.count("## Slide 1:") == 1
    assert text.count("## Slide 2:") == 1


def test_xlsx_has_sheet_headings_and_markdown_tables(tmp_path):
    """Each workbook sheet is named and represented as a Markdown table."""
    from openpyxl import Workbook

    path = tmp_path / "metrics.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quarterly Data"
    sheet.append(["Region", "Revenue"])
    sheet.append(["North", 42])
    workbook.create_sheet("Notes").append(["Comment"])
    workbook.save(path)

    text = result_for(path)["text"]

    assert "## Sheet: Quarterly Data" in text
    assert "## Sheet: Notes" in text
    assert "| Region | Revenue |" in text
    assert "| North | 42 |" in text


def test_epub_chapter_headings_are_preserved(tmp_path):
    """EPUB chapters keep their headings when converted to searchable text."""
    path = tmp_path / "book.epub"
    write_epub(path)

    text = result_for(path)["text"]

    assert "Book Chapter" in text
    assert "EPUB chapter content." in text


def test_non_archive_renamed_as_docx_is_rejected(tmp_path):
    """A renamed executable is refused before it can enter the job queue."""
    path = tmp_path / "renamed.exe.docx"
    path.write_bytes(b"MZ\x00\x01not a Word document")

    with pytest.raises(InvalidOfficeFileError, match="valid Office document"):
        OfficeAdapter().validate_file(str(path), ".docx")


def test_docx_with_malformed_required_xml_is_rejected(tmp_path):
    """A package with the right names but broken XML cannot enter the queue."""
    path = tmp_path / "malformed.docx"
    write_docx(path, document_xml="<w:document><w:body>")

    with pytest.raises(InvalidOfficeFileError, match="valid Office document"):
        OfficeAdapter().validate_file(str(path), ".docx")


def test_docx_with_corrupted_package_part_is_rejected(tmp_path):
    """A bad CRC in a non-XML member is caught before MarkItDown reads it."""
    path = tmp_path / "corrupted.docx"
    write_docx(path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("word/media/image1.png", b"image bytes")
    with zipfile.ZipFile(path) as archive:
        part = archive.getinfo("word/media/image1.png")
    data_offset = (
        part.header_offset
        + 30
        + len(part.filename.encode("utf-8"))
        + len(part.extra)
    )
    with path.open("r+b") as package:
        package.seek(data_offset)
        package.write(bytes([package.read(1)[0] ^ 1]))

    with pytest.raises(InvalidOfficeFileError, match="corrupted package part"):
        OfficeAdapter().validate_file(str(path), ".docx")


def test_xlsx_above_cell_cap_is_rejected(tmp_path, monkeypatch):
    """The configured worksheet cell ceiling is checked before pandas loads it."""
    from openpyxl import Workbook
    import app.adapters.office as office

    path = tmp_path / "too-many-cells.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["one", "two", "three"])
    workbook.save(path)
    monkeypatch.setattr(office, "MAX_SPREADSHEET_CELLS", 2)

    with pytest.raises(InvalidOfficeFileError, match="cell limit"):
        OfficeAdapter().validate_file(str(path), ".xlsx")


def test_xlsx_within_the_cell_cap_is_accepted(tmp_path):
    """A small valid spreadsheet passes content validation."""
    from openpyxl import Workbook

    path = tmp_path / "small.xlsx"
    workbook = Workbook()
    workbook.active.append(["one", "two"])
    workbook.save(path)

    OfficeAdapter().validate_file(str(path), ".xlsx")


def test_xlsx_sparse_cells_exceeding_grid_cap_are_rejected(tmp_path, monkeypatch):
    """Far-apart populated cells cannot expand into an oversized DataFrame."""
    from openpyxl import Workbook
    import app.adapters.office as office

    path = tmp_path / "sparse.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "first"
    sheet["Z100"] = "last"
    workbook.save(path)
    monkeypatch.setattr(office, "MAX_SPREADSHEET_CELLS", 10)

    with pytest.raises(InvalidOfficeFileError, match="cell limit"):
        OfficeAdapter().validate_file(str(path), ".xlsx")
