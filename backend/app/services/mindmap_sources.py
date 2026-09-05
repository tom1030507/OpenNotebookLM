"""Ground mind maps in representative passages and intact section hierarchies.

These selections are specific to concept maps. Other Studio features still use
the shared source digest's short opening excerpts.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from app.services.overview import overview_chunk_ids, overview_passage_text
from app.services.source_digest import document_text

_REFERENCES = re.compile(
    r"^\s*(?:\d+\.?\s+)?(?:references|bibliography|參考文獻|参考文献)\s*[:：]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# A year at the start of a wrapped dataset description is not a section number;
# accepting it would move every later subsection under that body sentence.
_HEADING = re.compile(
    r"^\s*(?:(#{1,4})\s+|(\d{1,2}(?:\.\d{1,2})*\.?)[ \t]+)([^\n]{2,96})$"
)
_PASSAGE_CHARS = 700


def ordered_chunks(document: Any) -> list[Any]:
    """Read source chunks in extraction order, independent of database row order.

    Args:
        document: Source with its chunk relationship loaded.

    Returns:
        Chunks sorted by extraction offset, retaining input order for ties.
    """
    chunks = list(document.chunks or [])
    return sorted(chunks, key=lambda chunk: (
        getattr(chunk, "start_offset", None) is None,
        getattr(chunk, "start_offset", None) or 0,
    ))


def _passages(document: Any) -> list[Any]:
    passages = []
    chunks = ordered_chunks(document)
    sources = [(chunk.text or "", chunk.heading_path) for chunk in chunks]
    if not sources:
        sources = [(document_text(document), None)]
    for text, heading in sources:
        if _REFERENCES.fullmatch((heading or "").split("/")[-1]):
            break
        reference = _REFERENCES.search(text)
        if reference:
            text = text[:reference.start()]
        # Keeping section titles with the next passage lets the overview
        # selector find abstracts and conclusions even in unstructured PDFs.
        buffer = ""
        for line in text.splitlines(keepends=True):
            if buffer and len(buffer) + len(line) > _PASSAGE_CHARS:
                passages.append(SimpleNamespace(
                    id=len(passages), text=buffer, heading_path=heading,
                ))
                buffer = ""
            while len(line) > _PASSAGE_CHARS:
                passages.append(SimpleNamespace(
                    id=len(passages), text=line[:_PASSAGE_CHARS], heading_path=heading,
                ))
                line = line[_PASSAGE_CHARS:]
            buffer += line
        if buffer.strip():
            passages.append(SimpleNamespace(id=len(passages), text=buffer, heading_path=heading))
        if reference:
            break
    return passages


def representative_excerpt(document: Any, limit: int = 6000) -> str:
    """Sample summary sections and the body instead of just the opening bytes.

    Args:
        document: Source whose extracted text and chunks are available.
        limit: Maximum excerpt characters, shared fairly by selected passages.

    Returns:
        Bounded verbatim passages, with summary sections prioritized and no
        bibliography. Sources without named sections are sampled throughout.
    """
    passages = _passages(document)
    if not passages or limit <= 0:
        return ""
    selected = overview_chunk_ids(passages, top_k=9)
    # Reserve room for distributed body evidence as well as the overview;
    # a summary alone rarely supports the map's deeper concept branches.
    for position in range(8):
        index = round(position * (len(passages) - 1) / 7)
        if index not in selected:
            selected.append(index)
    selected = selected[:14]
    per_passage = max(1, (limit - 2 * (len(selected) - 1)) // len(selected))
    return "\n\n".join(
        overview_passage_text(passages[index].text).strip()[:per_passage]
        for index in selected
    )[:limit]


def heading_paths(document: Any, limit: int = 48) -> list[list[str]]:
    """Preserve heading ancestors or recover explicit headings from plain text.

    Args:
        document: Source with extracted text and optional heading paths.
        limit: Most distinct paths retained per source.

    Returns:
        Ordered section paths with a repeated document title removed.
    """
    paths = []
    title = str(document.title or "").strip().casefold()
    chunks = ordered_chunks(document)
    for chunk in chunks:
        path = getattr(chunk, "heading_path", None)
        if not isinstance(path, str):
            continue
        parts = [part.strip() for part in re.split(r"\s*(?:/|>)\s*", path) if part.strip()]
        if parts and parts[0].casefold() == title:
            parts = parts[1:]
        if parts and parts not in paths:
            paths.append(parts[:3])
        if len(paths) >= limit:
            return paths
    if paths:
        return paths

    ancestors: list[tuple[int, str]] = []
    text = document.content or "\n".join(chunk.text or "" for chunk in chunks)
    for line in text.splitlines():
        if _REFERENCES.fullmatch(line):
            break
        match = _HEADING.match(line)
        if not match:
            continue
        markdown, number, label = match.groups()
        # Sentence-like numbered list items are evidence, not section titles.
        if label.rstrip().endswith((".", "。", ";", ":")):
            continue
        level = len(markdown) if markdown else len(number.rstrip(".").split("."))
        while ancestors and ancestors[-1][0] >= level:
            ancestors.pop()
        ancestors.append((level, label.strip().rstrip("#").strip()))
        parts = [label for _, label in ancestors]
        if parts[0].casefold() == title:
            parts = parts[1:]
        if parts and parts not in paths:
            paths.append(parts[:3])
        if len(paths) >= limit:
            break
    return paths
