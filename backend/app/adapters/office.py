"""Local text and Office document conversion for searchable sources."""
from pathlib import Path
import posixpath
import re
import zipfile
import zlib
from xml.etree import ElementTree
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlsplit


SUPPORTED_FILE_EXTENSIONS = frozenset({
    ".txt",
    ".md",
    ".docx",
    ".pptx",
    ".xlsx",
    ".epub",
})
SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
SUPPORTED_AUDIO_EXTENSIONS = frozenset({
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
    ".webm",
    ".flac",
})
SUPPORTED_UPLOAD_EXTENSIONS = frozenset({
    ".pdf",
    *SUPPORTED_FILE_EXTENSIONS,
    *SUPPORTED_IMAGE_EXTENSIONS,
    *SUPPORTED_AUDIO_EXTENSIONS,
})

# Pandas materializes a worksheet during MarkItDown conversion, so bound the
# number of cells before that allocation can be driven by an uploaded workbook.
MAX_SPREADSHEET_CELLS = 1_000_000

# A small compressed Office file can expand into a large in-memory workbook or
# XML tree, so cap the package size before any converter opens its contents.
MAX_OFFICE_ARCHIVE_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

_OFFICE_PACKAGE_PARTS = {
    ".docx": {"[Content_Types].xml", "_rels/.rels", "word/document.xml"},
    ".pptx": {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    },
    ".xlsx": {
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
    },
    ".epub": {"META-INF/container.xml", "mimetype"},
}
_EXPECTED_XML_ROOTS = {
    ".docx": {
        "[Content_Types].xml": "{http://schemas.openxmlformats.org/package/2006/content-types}Types",
        "_rels/.rels": "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships",
        "word/document.xml": "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document",
    },
    ".pptx": {
        "[Content_Types].xml": "{http://schemas.openxmlformats.org/package/2006/content-types}Types",
        "_rels/.rels": "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships",
        "ppt/presentation.xml": "{http://schemas.openxmlformats.org/presentationml/2006/main}presentation",
        "ppt/_rels/presentation.xml.rels": "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships",
    },
    ".xlsx": {
        "[Content_Types].xml": "{http://schemas.openxmlformats.org/package/2006/content-types}Types",
        "_rels/.rels": "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships",
        "xl/workbook.xml": "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook",
        "xl/_rels/workbook.xml.rels": "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships",
    },
    ".epub": {
        "META-INF/container.xml": "{urn:oasis:names:tc:opendocument:xmlns:container}container",
    },
}
_MAIN_OFFICE_PARTS = {
    ".docx": (
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ),
    ".pptx": (
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    ),
    ".xlsx": (
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    ),
}
_RELATIONSHIPS_ROOT = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships"
_OPF_PACKAGE_ROOT = "{http://www.idpf.org/2007/opf}package"
_SPREADSHEET_WORKSHEET_ROOT = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}worksheet"
MAX_SPREADSHEET_ROWS = 1_048_576
MAX_SPREADSHEET_COLUMNS = 16_384
_CELL_REFERENCE = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]*)$")
_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_PRESENTATION_SLIDE_ROOT = "{%s}sld" % _PRESENTATION_NS
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_OFFICE_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


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
        if extension not in SUPPORTED_FILE_EXTENSIONS and extension != ".pdf":
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

                corrupt_part = archive.testzip()
                if corrupt_part is not None:
                    raise InvalidOfficeFileError(
                        "The %s file contains a corrupted package part"
                        % extension[1:].upper()
                    )

                self._validate_package_xml(archive, names, extension)

                if extension == ".epub":
                    if (
                        parts[0].filename != "mimetype"
                        or parts[0].compress_type != zipfile.ZIP_STORED
                        or archive.read("mimetype") != b"application/epub+zip"
                    ):
                        raise InvalidOfficeFileError("The EPUB file has an invalid mimetype")
        except InvalidOfficeFileError:
            raise
        except (
            OSError,
            EOFError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
            KeyError,
            RuntimeError,
            NotImplementedError,
            zlib.error,
        ) as error:
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
        elif extension == ".pptx":
            text = self._extract_pptx_text(file_path)
        else:
            # convert_local never treats the filename as a URL. Mammoth also
            # disables external file access by default, so linked images cannot
            # make an uploaded document perform network or filesystem reads.
            from markitdown import MarkItDown

            converted = MarkItDown(enable_plugins=False).convert_local(file_path)
            text = converted.markdown
            if extension == ".xlsx":
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

    @classmethod
    def _validate_package_xml(
        cls,
        archive: zipfile.ZipFile,
        names: set[str],
        extension: str,
    ) -> None:
        """Stream-parse package XML and bound XLSX conversion grid size.

        Args:
            archive: Open Office or EPUB package.
            names: Package member names.
            extension: Normalized package extension.

        Returns:
            None.

        Raises:
            InvalidOfficeFileError: If package XML is invalid or XLSX is too large.
        """
        xml_names = sorted(
            name for name in names
            if name.lower().endswith((".xml", ".rels", ".opf", ".xhtml"))
        )
        root_tags: Dict[str, str] = {}
        package_relationships: Dict[str, list[tuple[str, str, str, str]]] = {}
        content_type_overrides: Dict[str, str] = {}
        epub_rootfiles = []
        epub_manifests: Dict[str, Dict[str, str]] = {}
        epub_spines: Dict[str, list[str]] = {}
        presentation_slide_ids = []
        cell_count = 0
        total_grid_cells = 0
        worksheet_count = 0
        for name in xml_names:
            root_tag = None
            is_worksheet = False
            relationships = []
            manifest: Dict[str, str] = {}
            spine = []
            current_row = 0
            current_column = 0
            max_row = 0
            max_column = 0
            with archive.open(name) as xml_file:
                for _, element in ElementTree.iterparse(xml_file, events=("start",)):
                    local_name = element.tag.rsplit("}", 1)[-1]
                    if root_tag is None:
                        root_tag = element.tag
                        is_worksheet = (
                            extension == ".xlsx"
                            and root_tag == _SPREADSHEET_WORKSHEET_ROOT
                        )
                        if is_worksheet:
                            worksheet_count += 1

                    if name.endswith(".rels") and local_name == "Relationship":
                        relationships.append((
                            element.attrib.get("Id", ""),
                            element.attrib.get("Type", ""),
                            element.attrib.get("Target", ""),
                            element.attrib.get("TargetMode", ""),
                        ))
                    elif name == "[Content_Types].xml" and local_name == "Override":
                        part_name = element.attrib.get("PartName", "").lstrip("/")
                        if part_name:
                            content_type_overrides[part_name] = element.attrib.get(
                                "ContentType", ""
                            )
                    elif name == "ppt/presentation.xml" and local_name == "sldId":
                        presentation_slide_ids.append(
                            element.attrib.get(
                                "{%s}id" % _OFFICE_RELATIONSHIPS_NS,
                                "",
                            )
                        )
                    elif name == "META-INF/container.xml" and local_name == "rootfile":
                        epub_rootfiles.append(element.attrib.get("full-path", ""))
                    elif name.lower().endswith(".opf") and local_name == "item":
                        item_id = element.attrib.get("id", "")
                        href = element.attrib.get("href", "")
                        if item_id and href:
                            manifest[item_id] = href
                    elif name.lower().endswith(".opf") and local_name == "itemref":
                        item_id = element.attrib.get("idref", "")
                        if item_id:
                            spine.append(item_id)

                    if (
                        extension == ".xlsx"
                        and is_worksheet
                    ):
                        if local_name == "row":
                            row_reference = element.attrib.get("r")
                            if row_reference is None:
                                current_row += 1
                            elif re.fullmatch(r"[1-9][0-9]*", row_reference):
                                parsed_row = int(row_reference)
                                if parsed_row <= current_row:
                                    raise InvalidOfficeFileError(
                                        "The XLSX file contains invalid row references"
                                    )
                                current_row = parsed_row
                            else:
                                raise InvalidOfficeFileError(
                                    "The XLSX file contains invalid row references"
                                )

                            if current_row > MAX_SPREADSHEET_ROWS:
                                raise InvalidOfficeFileError(
                                    "The XLSX file contains invalid row references"
                                )
                            current_column = 0
                            max_row = max(max_row, current_row)
                        elif local_name == "c":
                            if current_row == 0:
                                raise InvalidOfficeFileError(
                                    "The XLSX file contains a cell outside a worksheet row"
                                )
                            cell_reference = element.attrib.get("r")
                            if cell_reference:
                                column, row = cls._cell_reference_dimensions(cell_reference)
                                if row != current_row:
                                    raise InvalidOfficeFileError(
                                        "The XLSX cell reference does not match its row reference"
                                    )
                                current_column = column
                            else:
                                current_column += 1
                                column = current_column
                                row = current_row

                            cell_count += 1
                            if cell_count > MAX_SPREADSHEET_CELLS:
                                raise InvalidOfficeFileError(
                                    "The XLSX file exceeds the %s cell limit"
                                    % MAX_SPREADSHEET_CELLS
                                )
                            max_column = max(max_column, column)
                            max_row = max(max_row, row)
                    element.clear()

            if root_tag is None:
                raise InvalidOfficeFileError(
                    "The %s file contains an empty XML package part"
                    % extension[1:].upper()
                )
            root_tags[name] = root_tag
            if name.endswith(".rels"):
                package_relationships[name] = relationships
            if name.lower().endswith(".opf"):
                epub_manifests[name] = manifest
                epub_spines[name] = spine

            if extension == ".xlsx" and is_worksheet:
                # pandas creates a rectangular DataFrame through the furthest
                # row and column; sparse references can otherwise allocate a
                # huge grid despite containing very few stored cells. Blank
                # rows count as one column so their generated row tuples are
                # bounded too.
                total_grid_cells += max_row * max(max_column, 1)
                if total_grid_cells > MAX_SPREADSHEET_CELLS:
                    raise InvalidOfficeFileError(
                        "The XLSX file exceeds the %s cell limit"
                        % MAX_SPREADSHEET_CELLS
                    )

        for part_name, expected_root in _EXPECTED_XML_ROOTS.get(extension, {}).items():
            if root_tags.get(part_name) != expected_root:
                raise InvalidOfficeFileError(
                    "The %s file is not a valid Office document"
                    % extension[1:].upper()
                )

        for part_name, relationships in package_relationships.items():
            if root_tags.get(part_name) != _RELATIONSHIPS_ROOT:
                raise InvalidOfficeFileError(
                    "The %s file contains invalid package relationships"
                    % extension[1:].upper()
                )

        resolved_relationships: Dict[str, list[tuple[str, str, str]]] = {}
        for part_name, relationships in package_relationships.items():
            source_directory = cls._relationship_source_directory(part_name)
            resolved = []
            for relationship_id, relationship_type, target, target_mode in relationships:
                if not relationship_id or not relationship_type or not target:
                    raise InvalidOfficeFileError(
                        "The %s file contains invalid package relationships"
                        % extension[1:].upper()
                    )
                if target_mode.lower() == "external":
                    continue
                resolved_target = cls._resolve_internal_target(
                    source_directory,
                    target,
                )
                if resolved_target not in names:
                    raise InvalidOfficeFileError(
                        "The %s file contains a missing relationship target"
                        % extension[1:].upper()
                    )
                resolved.append((relationship_id, relationship_type, resolved_target))
            resolved_relationships[part_name] = resolved

        if extension in _MAIN_OFFICE_PARTS:
            main_part, main_content_type = _MAIN_OFFICE_PARTS[extension]
            if content_type_overrides.get(main_part) != main_content_type:
                raise InvalidOfficeFileError(
                    "The %s file has invalid main-part content types"
                    % extension[1:].upper()
                )
            root_relationships = resolved_relationships.get("_rels/.rels", [])
            if not any(
                relationship_type.endswith("/officeDocument")
                and target == main_part
                for _, relationship_type, target in root_relationships
            ):
                raise InvalidOfficeFileError(
                    "The %s file has no valid main-part relationship"
                    % extension[1:].upper()
                )

        if extension == ".xlsx":
            worksheet_relationships = [
                target
                for _, relationship_type, target in resolved_relationships.get(
                    "xl/_rels/workbook.xml.rels",
                    [],
                )
                if relationship_type.endswith("/worksheet")
            ]
            if not worksheet_relationships:
                raise InvalidOfficeFileError("The XLSX file contains no worksheets")
            if any(
                root_tags.get(target) != _SPREADSHEET_WORKSHEET_ROOT
                for target in worksheet_relationships
            ):
                raise InvalidOfficeFileError(
                    "The XLSX file contains an invalid worksheet part"
                )
            if worksheet_count == 0:
                raise InvalidOfficeFileError("The XLSX file contains no worksheets")

        if extension == ".pptx":
            slide_relationships = {
                relationship_id: target
                for relationship_id, relationship_type, target in resolved_relationships.get(
                    "ppt/_rels/presentation.xml.rels",
                    [],
                )
                if relationship_type.endswith("/slide")
            }
            if not presentation_slide_ids or any(
                relationship_id not in slide_relationships
                for relationship_id in presentation_slide_ids
            ) or any(
                root_tags.get(target) != _PRESENTATION_SLIDE_ROOT
                for target in slide_relationships.values()
            ):
                raise InvalidOfficeFileError(
                    "The PPTX file contains an invalid slide relationship or slide part"
                )

        if extension == ".epub":
            if not epub_rootfiles:
                raise InvalidOfficeFileError(
                    "The EPUB file does not declare a package rootfile"
                )
            package_path = cls._resolve_archive_path(epub_rootfiles[0])
            if (
                package_path not in names
                or root_tags.get(package_path) != _OPF_PACKAGE_ROOT
            ):
                raise InvalidOfficeFileError(
                    "The EPUB file has an invalid package rootfile"
                )
            manifest = epub_manifests.get(package_path, {})
            spine = epub_spines.get(package_path, [])
            if not manifest or not spine:
                raise InvalidOfficeFileError(
                    "The EPUB file has no readable package spine"
                )
            package_directory = posixpath.dirname(package_path)
            for item_id in spine:
                href = manifest.get(item_id)
                if href is None:
                    raise InvalidOfficeFileError(
                        "The EPUB file has an invalid spine reference"
                    )
                target_path = urlsplit(href)
                if target_path.scheme or target_path.netloc or target_path.query or target_path.fragment:
                    raise InvalidOfficeFileError(
                        "The EPUB file has an invalid spine resource"
                    )
                resolved_target = cls._resolve_internal_target(
                    package_directory,
                    target_path.path,
                )
                if resolved_target not in names:
                    raise InvalidOfficeFileError(
                        "The EPUB file has a missing spine resource"
                    )

    @staticmethod
    def _relationship_source_directory(relationship_part: str) -> str:
        """Return the directory of the part a relationship file describes.

        Args:
            relationship_part: Package path ending in ``.rels``.

        Returns:
            The source part's containing directory.

        Raises:
            InvalidOfficeFileError: If the relationship path is not an OPC path.
        """
        if relationship_part == "_rels/.rels":
            return ""
        marker = "/_rels/"
        if marker not in relationship_part or not relationship_part.endswith(".rels"):
            raise InvalidOfficeFileError("The Office package has an invalid relationship path")
        directory, relationship_name = relationship_part.rsplit(marker, 1)
        source_name = relationship_name.removesuffix(".rels")
        if not source_name:
            raise InvalidOfficeFileError("The Office package has an invalid relationship path")
        return posixpath.dirname(posixpath.join(directory, source_name))

    @staticmethod
    def _resolve_internal_target(base_directory: str, target: str) -> str:
        """Normalize a package-internal target without allowing path escape.

        Args:
            base_directory: Package directory containing the referring part.
            target: URI reference from a relationship or EPUB manifest.

        Returns:
            Normalized package path.

        Raises:
            InvalidOfficeFileError: If the target is external or escapes the package.
        """
        parsed_target = urlsplit(target)
        if parsed_target.scheme or parsed_target.netloc:
            raise InvalidOfficeFileError("The Office package has an invalid internal target")
        target_path = unquote(parsed_target.path)
        if not target_path:
            raise InvalidOfficeFileError("The Office package has an empty internal target")
        if target_path.startswith("/"):
            resolved_target = posixpath.normpath(target_path.lstrip("/"))
        else:
            resolved_target = posixpath.normpath(
                posixpath.join(base_directory, target_path)
            )
        if resolved_target == ".." or resolved_target.startswith("../"):
            raise InvalidOfficeFileError("The Office package target escapes the package")
        return resolved_target

    @staticmethod
    def _resolve_archive_path(package_path: str) -> str:
        """Normalize a root-relative EPUB package path.

        Args:
            package_path: The path from an EPUB container rootfile element.

        Returns:
            Normalized ZIP member name, or an empty string for an invalid path.
        """
        if not package_path or package_path.startswith("/"):
            return ""
        normalized = posixpath.normpath(package_path)
        if normalized == ".." or normalized.startswith("../"):
            return ""
        return normalized

    @classmethod
    def _extract_pptx_text(cls, file_path: str) -> str:
        """Read slide text from OOXML without loading embedded images.

        Args:
            file_path: Local path to a previously validated PPTX package.

        Returns:
            Markdown with one heading per slide and its visible text.

        Raises:
            InvalidOfficeFileError: If slide relationships or text parts are invalid.
        """
        presentation_tag = "{%s}presentation" % _PRESENTATION_NS
        slide_tag = "{%s}sld" % _PRESENTATION_NS
        slide_id_tag = "{%s}sldId" % _PRESENTATION_NS
        relationship_id_attribute = "{%s}id" % _OFFICE_RELATIONSHIPS_NS
        relationship_tag = "{%s}Relationship" % "http://schemas.openxmlformats.org/package/2006/relationships"
        paragraph_tag = "{%s}p" % _DRAWING_NS
        text_tag = "{%s}t" % _DRAWING_NS
        placeholder_tag = "{%s}ph" % _PRESENTATION_NS
        shape_tree_tag = "{%s}spTree" % _PRESENTATION_NS

        with zipfile.ZipFile(file_path) as archive:
            names = set(archive.namelist())
            presentation_root = None
            slide_ids = []
            with archive.open("ppt/presentation.xml") as presentation_file:
                for _, element in ElementTree.iterparse(
                    presentation_file,
                    events=("start",),
                ):
                    if presentation_root is None:
                        presentation_root = element.tag
                    if element.tag == slide_id_tag:
                        slide_ids.append(
                            element.attrib.get(relationship_id_attribute, "")
                        )
                    element.clear()
            if presentation_root != presentation_tag:
                raise InvalidOfficeFileError("The PPTX file has an invalid presentation part")

            relationship_by_id = {}
            with archive.open("ppt/_rels/presentation.xml.rels") as relationship_file:
                for _, element in ElementTree.iterparse(
                    relationship_file,
                    events=("start",),
                ):
                    if element.tag == relationship_tag:
                        relationship_by_id[element.attrib.get("Id", "")] = dict(
                            element.attrib
                        )
                    element.clear()

            sections = []
            for slide_number, relationship_id in enumerate(slide_ids, start=1):
                relationship = relationship_by_id.get(relationship_id)
                if (
                    relationship is None
                    or not relationship.get("Type", "").endswith("/slide")
                ):
                    raise InvalidOfficeFileError(
                        "The PPTX file contains an invalid slide relationship"
                    )
                slide_path = cls._resolve_internal_target(
                    "ppt",
                    relationship.get("Target", ""),
                )
                if slide_path not in names:
                    raise InvalidOfficeFileError(
                        "The PPTX file is missing a slide part"
                    )

                slide_root = None
                shape_tree_found = False
                shape_tree_depth = None
                shape_depth = None
                shape_tag = None
                shape_is_title = False
                shape_paragraphs = []
                paragraph_text = None
                title = ""
                body = []
                stack = []
                with archive.open(slide_path) as slide_file:
                    for event, element in ElementTree.iterparse(
                        slide_file,
                        events=("start", "end"),
                    ):
                        if event == "start":
                            if slide_root is None:
                                slide_root = element.tag
                            if element.tag == shape_tree_tag:
                                shape_tree_found = True
                                shape_tree_depth = len(stack)
                            elif (
                                shape_tree_depth is not None
                                and shape_depth is None
                                and len(stack) == shape_tree_depth + 1
                            ):
                                shape_depth = len(stack)
                                shape_tag = element.tag
                                shape_is_title = False
                                shape_paragraphs = []

                            if shape_depth is not None:
                                if element.tag == placeholder_tag:
                                    shape_is_title = shape_is_title or element.attrib.get(
                                        "type"
                                    ) in {"title", "ctrTitle"}
                                elif element.tag == paragraph_tag:
                                    paragraph_text = []
                            stack.append(element)
                            continue

                        if element.tag == text_tag and paragraph_text is not None:
                            paragraph_text.append(element.text or "")
                        elif element.tag == paragraph_tag and paragraph_text is not None:
                            text_line = "".join(paragraph_text).strip()
                            if text_line:
                                shape_paragraphs.append(text_line)
                            paragraph_text = None

                        if (
                            shape_depth is not None
                            and len(stack) - 1 == shape_depth
                            and element.tag == shape_tag
                        ):
                            if shape_paragraphs:
                                if shape_is_title and not title:
                                    title = " ".join(shape_paragraphs)
                                else:
                                    body.extend(shape_paragraphs)
                            shape_depth = None
                            shape_tag = None
                            shape_is_title = False
                            shape_paragraphs = []
                        if element.tag == shape_tree_tag:
                            shape_tree_depth = None
                        element.clear()
                        stack.pop()

                if slide_root != slide_tag or not shape_tree_found:
                    raise InvalidOfficeFileError(
                        "The PPTX file contains an invalid slide part"
                    )

                heading = title or "Untitled"
                section = "## Slide %s: %s" % (slide_number, heading)
                if body:
                    section += "\n\n" + "\n".join(body)
                sections.append(section)

        if not sections:
            raise InvalidOfficeFileError("The PPTX file contains no slides")
        return "\n\n".join(sections)

    @staticmethod
    def _cell_reference_dimensions(cell_reference: str) -> tuple[int, int]:
        """Return one XLSX cell's column and row after validating its address.

        Args:
            cell_reference: A cell address such as ``BC42``.

        Returns:
            One-based column and row numbers.

        Raises:
            InvalidOfficeFileError: If the address is malformed or outside XLSX bounds.
        """
        match = _CELL_REFERENCE.fullmatch(cell_reference)
        if match is None:
            raise InvalidOfficeFileError("The XLSX file contains an invalid cell reference")

        column = 0
        for letter in match.group(1).upper():
            column = column * 26 + ord(letter) - ord("A") + 1
        row = int(match.group(2))
        if column > 16_384 or row > 1_048_576:
            raise InvalidOfficeFileError("The XLSX file contains an invalid cell reference")
        return column, row

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
