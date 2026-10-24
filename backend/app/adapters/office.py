"""Local text and Office document conversion for searchable sources."""
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree
from typing import Any, Dict, Optional


SUPPORTED_FILE_EXTENSIONS = frozenset({
    ".txt",
    ".md",
    ".docx",
    ".pptx",
    ".xlsx",
    ".epub",
})
SUPPORTED_UPLOAD_EXTENSIONS = frozenset({".pdf", *SUPPORTED_FILE_EXTENSIONS})

# Pandas materializes a worksheet during MarkItDown conversion, so bound the
# number of cells before that allocation can be driven by an uploaded workbook.
MAX_SPREADSHEET_CELLS = 1_000_000

# A small compressed Office file can expand into a large in-memory workbook or
# XML tree, so cap the package size before any converter opens its contents.
MAX_OFFICE_ARCHIVE_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

_OFFICE_PACKAGE_PARTS = {
    ".docx": {"[Content_Types].xml", "word/document.xml"},
    ".pptx": {"[Content_Types].xml", "ppt/presentation.xml"},
    ".xlsx": {"[Content_Types].xml", "xl/workbook.xml"},
    ".epub": {"META-INF/container.xml", "mimetype"},
}
_SLIDE_MARKER = re.compile(r"<!--\s*Slide number:\s*(\d+)\s*-->")


class InvalidOfficeFileError(ValueError):
    """Raised when an Office file's extension and package contents disagree."""


class OfficeAdapter:
    """Convert local source files to the text shape consumed by indexing."""

    def validate_file(self, file_path: str, file_extension: str) -> None:
        """Check an uploaded file's package before it is durably queued.

        Args:
            file_path: Local path to the saved upload.
            file_extension: Original filename extension, including its dot.

        Returns:
            None.

        Raises:
            InvalidOfficeFileError: If the file is unsupported or malformed.
        """
        extension = self._normalize_extension(file_extension)
        if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            raise InvalidOfficeFileError(
                "Files with the %s extension are not supported" % extension
            )

        if extension in {".txt", ".md", ".pdf"}:
            return

        try:
            with zipfile.ZipFile(file_path) as archive:
                parts = archive.infolist()
                uncompressed_size = sum(part.file_size for part in parts)
                if uncompressed_size > MAX_OFFICE_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise InvalidOfficeFileError(
                        "The %s file expands beyond the allowed Office document size"
                        % extension[1:].upper()
                    )

                names = {part.filename for part in parts}
                required_parts = _OFFICE_PACKAGE_PARTS.get(extension, set())
                if not required_parts.issubset(names):
                    raise InvalidOfficeFileError(
                        "The %s file is not a valid Office document"
                        % extension[1:].upper()
                    )

                if extension == ".epub":
                    if archive.read("mimetype") != b"application/epub+zip":
                        raise InvalidOfficeFileError("The EPUB file has an invalid mimetype")
                elif extension == ".xlsx":
                    self._validate_spreadsheet_cells(archive, names)
        except InvalidOfficeFileError:
            raise
        except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError) as error:
            raise InvalidOfficeFileError(
                "The %s file is not a valid Office document" % extension[1:].upper()
            ) from error

    def extract_text_from_file(
        self,
        file_path: str,
        file_extension: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract a local file as Markdown and return the PDF adapter shape.

        Args:
            file_path: Local path to the uploaded source.
            file_extension: Persisted source extension, inferred from the path
                when omitted.

        Returns:
            Extracted text, empty page metadata, and the detected file format.
        """
        extension = self._normalize_extension(file_extension or Path(file_path).suffix)
        self.validate_file(file_path, extension)

        if extension in {".txt", ".md"}:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        else:
            # convert_local never treats the filename as a URL. Mammoth also
            # disables external file access by default, so linked images cannot
            # make an uploaded document perform network or filesystem reads.
            from markitdown import MarkItDown

            converted = MarkItDown(enable_plugins=False).convert_local(file_path)
            text = converted.markdown
            if extension == ".pptx":
                text = self._format_slides(text)
            elif extension == ".xlsx":
                text = self._format_sheets(text)

        text = text.strip()
        return {
            "text": text,
            "pages": [],
            "num_pages": 0,
            "metadata": {"format": extension[1:]},
        }

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        """Normalize a filename extension without trusting its case or dot."""
        normalized = extension.strip().lower()
        return normalized if normalized.startswith(".") else "." + normalized

    @staticmethod
    def _validate_spreadsheet_cells(
        archive: zipfile.ZipFile,
        names: set[str],
    ) -> None:
        """Count actual worksheet cells before pandas materializes the file.

        Args:
            archive: Open XLSX package.
            names: Package member names.

        Returns:
            None.

        Raises:
            InvalidOfficeFileError: If the workbook is malformed or too large.
        """
        worksheet_names = sorted(
            name for name in names
            if name.startswith("xl/worksheets/") and name.endswith(".xml")
        )
        if not worksheet_names:
            raise InvalidOfficeFileError("The XLSX file contains no worksheets")

        cell_count = 0
        for name in worksheet_names:
            with archive.open(name) as worksheet:
                for _, element in ElementTree.iterparse(worksheet, events=("start",)):
                    if element.tag.rsplit("}", 1)[-1] == "c":
                        cell_count += 1
                        if cell_count > MAX_SPREADSHEET_CELLS:
                            raise InvalidOfficeFileError(
                                "The XLSX file exceeds the %s cell limit"
                                % MAX_SPREADSHEET_CELLS
                            )
                    element.clear()

    @staticmethod
    def _format_slides(markdown: str) -> str:
        """Turn MarkItDown's slide markers and titles into section headings.

        Args:
            markdown: MarkItDown output for a PowerPoint file.

        Returns:
            Markdown with one level-two heading for each slide.
        """
        markers = list(_SLIDE_MARKER.finditer(markdown))
        if not markers:
            return markdown

        sections = []
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(markdown)
            body = markdown[marker.end():end].strip()
            number = int(marker.group(1))
            title_match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
            if title_match:
                title = title_match.group(1).strip()
                body = body[:title_match.start()] + body[title_match.end():]
                heading = "## Slide %s: %s" % (number, title)
            else:
                heading = "## Slide %s: Untitled" % number

            sections.append("\n\n".join(part for part in (heading, body.strip()) if part))

        return "\n\n".join(sections)

    @staticmethod
    def _format_sheets(markdown: str) -> str:
        """Name each MarkItDown worksheet table with a stable section prefix.

        Args:
            markdown: MarkItDown output for a spreadsheet.

        Returns:
            Markdown with a ``Sheet:`` heading before each worksheet table.
        """
        return re.sub(
            r"(?m)^## (?!Sheet:\s)(.+?)\s*$",
            r"## Sheet: \1",
            markdown,
        )
