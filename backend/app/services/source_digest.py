"""Reading a project's sources, and extracting structure from them.

Every derived view of a project — the mind map, the video summary — starts the
same way: list the project's documents in a stable order, take the opening of
each, and name what is in it using whatever the document actually carries. That
work is here rather than in either feature, so the two cannot drift apart on
what "the project's sources, in order" means.

Naming a document's contents degrades in a fixed order: real heading structure
first, then the most frequent meaningful words. Callers layer their own steps
onto that — the video summary reads opening sentences between the two, because
a keyword cannot be read aloud.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Document, Project, ProjectDocument

# How much of a document a model is shown. The whole corpus would not fit, and
# the opening of a document is where its subject is stated.
DOCUMENT_EXCERPT_CHARS = 1200

# Words that are frequent in every English document and therefore say nothing
# about this one. Short tokens are dropped by length, so this only needs the
# three-letter-and-longer offenders.
STOPWORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "have", "has", "had",
    "was", "were", "are", "not", "but", "you", "your", "they", "them", "their",
    "its", "his", "her", "our", "out", "who", "which", "what", "when", "where",
    "how", "why", "all", "any", "can", "will", "would", "could", "should",
    "may", "might", "must", "into", "over", "than", "then", "there", "these",
    "those", "such", "some", "more", "most", "other", "also", "been", "being",
    "about", "after", "before", "between", "because", "while", "does", "did",
    "each", "only", "same", "very", "just", "much", "many", "one", "two",
    "three", "use", "used", "using", "make", "made", "way", "well", "get",
    "see", "new", "now", "may", "per", "via", "etc",
})

WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")

# Default width of a branch or a slide. Wider than this stops being readable,
# and the prompt that asks for it stops being cheap.
MAX_LABELS = 6


def project_documents(db: Session, project: Project) -> List[Document]:
    """List the documents attached to a project, in a stable order.

    Args:
        db: Database session.
        project: The project.

    Returns:
        The documents. Ordered by title after `added_at`, because `added_at`
        comes from SQLite's second-resolution clock and every document of one
        upload ties.
    """
    return db.query(Document).join(
        ProjectDocument,
        ProjectDocument.document_id == Document.id,
    ).filter(
        ProjectDocument.project_id == project.id,
    ).order_by(
        ProjectDocument.added_at,
        Document.title,
    ).all()


def document_text(document: Any) -> str:
    """Read whatever text a document can offer.

    Args:
        document: A document with its chunks loaded.

    Returns:
        The stored content, or the chunks joined when the content column is
        empty. Empty for a document whose extraction has not run or failed.
    """
    text = document.content
    if not text:
        text = "\n".join(chunk.text or "" for chunk in (document.chunks or []))

    return (text or "").strip()


def document_excerpt(document: Any) -> str:
    """Take the opening of a document, for a prompt.

    Args:
        document: A document with its chunks loaded.

    Returns:
        At most `DOCUMENT_EXCERPT_CHARS` characters of text.
    """
    return document_text(document)[:DOCUMENT_EXCERPT_CHARS]


def topics_from_headings(
    heading_paths: Iterable[Optional[str]],
    limit: int = MAX_LABELS,
) -> List[str]:
    """Read topic labels off the heading path of a document's chunks.

    A heading path names every ancestor ("Guide/Setup/Install"), so only the
    last segment is the topic; the ancestors are the document itself. Every
    chunk of one section carries that section's path, so repeats are the norm
    and first-occurrence order is the document's own order.

    Args:
        heading_paths: The `heading_path` of each chunk, in document order.
            Missing and blank values are expected — PDF and video chunks have
            none.
        limit: Most topics to return.

    Returns:
        Distinct topic labels, in the order they first appear.
    """
    topics: List[str] = []
    for path in heading_paths:
        if not path or not path.strip():
            continue
        label = path.strip().rstrip("/").split("/")[-1].strip()
        if label and label not in topics:
            topics.append(label)
            if len(topics) == limit:
                break
    return topics


def topics_from_keywords(
    text: Optional[str],
    limit: int = MAX_LABELS,
) -> List[str]:
    """Pick the most frequent meaningful words in a document.

    The last resort, for a document with no headings and no model to read it.
    Frequency across the whole document is the only signal available without
    either.

    Args:
        text: Document text, or None for a document not yet extracted.
        limit: Most keywords to return.

    Returns:
        Lowercased keywords, most frequent first. Ties keep the order the words
        appear in, so the same document always produces the same result.
    """
    if not text:
        return []

    counts: Counter = Counter()
    first_seen: Dict[str, int] = {}
    for position, match in enumerate(WORD_PATTERN.finditer(text)):
        word = match.group(0).lower()
        if word in STOPWORDS:
            continue
        counts[word] += 1
        first_seen.setdefault(word, position)

    ranked = sorted(counts, key=lambda word: (-counts[word], first_seen[word]))
    return ranked[:limit]


def load_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Parse the first JSON object in a model's reply, ignoring anything around it.

    Models wrap JSON in prose and code fences however firmly they are told not
    to, and an unconfigured provider answers with the extractive fallback, which
    is prose.

    Args:
        text: The model's raw reply.

    Returns:
        The decoded object, or None if there is no readable one.
    """
    if not text:
        return None

    import json

    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload

    return None
