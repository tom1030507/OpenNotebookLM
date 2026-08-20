"""Turn a project's sources into a mind map tree.

The tree is always three levels: the project, one branch per source, and the
topics inside each source. Topics come from whichever of three sources can
actually supply them, in descending order of quality:

1. an LLM, asked once for the whole project and required to answer in JSON;
2. the chunks' ``heading_path`` — real document structure, already in the
   database for anything imported from the web;
3. the most frequent meaningful words in the text.

The last step exists because the common case is a PDF with no headings and no
LLM configured, and a mind map whose branches have nothing on them is not worth
opening. Which one answered is reported as ``model_used``, the same way
``/query`` reports it, so a caller can tell a generated map from an extracted
one instead of guessing.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

import structlog
from sqlalchemy.orm import Session

from app.db.models import Document, Project, ProjectDocument
from app.services.llm import FALLBACK_MODEL, LLMService
from app.utils.time import utc_now

logger = structlog.get_logger()

# A branch wider than this stops being readable, and the LLM prompt that asks
# for it stops being cheap.
MAX_TOPICS_PER_DOCUMENT = 6

# How much of each document the model is shown. The whole corpus would not fit,
# and the opening of a document is where its subject is stated.
DOCUMENT_EXCERPT_CHARS = 1200

# The topic call's token budget. A reasoning model writes its thinking into this
# same budget before any content, so the floor has to clear the thinking or the
# reply comes back empty and the map silently falls back to keywords — which is
# exactly what Groq's qwen3.6-27b did at the provider's configured 2048-token
# floor, spending all of it on hidden reasoning and returning nothing.
#
# Measured against that model: 2 documents spent 2916, 4 spent 4121, 6 spent
# 5126. The marginal cost is roughly 550 per document, so 512 keeps a margin of
# about 1000 that neither grows nor shrinks across that range.
TOPIC_TOKEN_BUDGET_BASE = 3072
TOPIC_TOKEN_BUDGET_PER_DOCUMENT = 512
# One mind map is one request; a 200-source project must not make it unbounded.
TOPIC_TOKEN_BUDGET_CAP = 16384

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

TOPIC_SYSTEM_PROMPT = (
    "You organize study notes into mind maps. Answer with a single JSON object "
    "and nothing else."
)


def topic_token_budget(document_count: int) -> int:
    """Size the topic call's token budget for the project.

    Args:
        document_count: How many documents the one call covers.

    Returns:
        A `max_tokens` value with room for a reasoning model's thinking as well
        as the JSON, capped so a large project stays one bounded request.
    """
    budget = TOPIC_TOKEN_BUDGET_BASE + TOPIC_TOKEN_BUDGET_PER_DOCUMENT * document_count

    return min(budget, TOPIC_TOKEN_BUDGET_CAP)


def topics_from_headings(
    heading_paths: Iterable[Optional[str]],
    limit: int = MAX_TOPICS_PER_DOCUMENT,
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
    limit: int = MAX_TOPICS_PER_DOCUMENT,
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
        appear in, so the same document always produces the same map.
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


def parse_llm_topics(text: str, document_count: int) -> Dict[int, List[str]]:
    """Read a model's reply into topics keyed by document index.

    The reply is untrusted input: models wrap JSON in prose and code fences,
    invent indexes, and — when no provider is configured at all — answer with
    the extractive fallback, which is prose. Anything that cannot be read as
    the agreed shape yields nothing, so the caller falls back to structure
    rather than rendering garbage.

    Indexes rather than ids keep uuids out of the prompt and the reply, where
    they only invite the model to mistype one.

    Args:
        text: The model's raw reply.
        document_count: How many documents were asked about. Indexes are
            1-based and anything outside the range is dropped.

    Returns:
        Topic lists by document index. Empty if the reply was unusable.
    """
    payload = _load_json_object(text)
    if payload is None:
        return {}

    entries = payload.get("documents")
    if not isinstance(entries, list):
        return {}

    topics_by_index: Dict[int, List[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if not isinstance(index, int) or not 1 <= index <= document_count:
            continue
        topics = _clean_topics(entry.get("topics"))
        if topics:
            topics_by_index[index] = topics

    return topics_by_index


def _load_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Parse the first JSON object in a reply, ignoring anything around it.

    Args:
        text: The model's raw reply.

    Returns:
        The decoded object, or None if there is no readable one.
    """
    if not text:
        return None

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


def _clean_topics(topics: Any) -> List[str]:
    """Keep the usable topic labels from whatever the model listed.

    Args:
        topics: The `topics` value from one entry of the reply.

    Returns:
        Trimmed, non-empty labels, capped at `MAX_TOPICS_PER_DOCUMENT`.
    """
    if not isinstance(topics, list):
        return []

    cleaned: List[str] = []
    for topic in topics:
        if not isinstance(topic, str):
            continue
        label = topic.strip()
        if label:
            cleaned.append(label)
        if len(cleaned) == MAX_TOPICS_PER_DOCUMENT:
            break

    return cleaned


class MindMapService:
    """Build the mind map a project's Studio panel draws."""

    def __init__(self, llm_service: Optional[Any] = None):
        """Wire up the model used to name topics.

        Args:
            llm_service: Object with `generate`. Defaults to the shared
                `LLMService`, whose construction performs no network I/O.
        """
        self.llm = llm_service if llm_service is not None else LLMService()
        # What produced the topics in the tree built most recently. Read by the
        # route to fill `model_used`, so a caller can tell a generated map from
        # an extracted one.
        self.last_model: str = FALLBACK_MODEL

    def generate(self, db: Session, project: Project) -> Dict[str, Any]:
        """Build the mind map for a project.

        Args:
            db: Database session.
            project: The project to map. Ownership is the caller's problem —
                resolve the id through `routers.ownership` first.

        Returns:
            The tree plus the metadata the API exposes: which model named the
            topics, when it was built, and how many nodes it holds.
        """
        documents = self._project_documents(db, project)
        root = self.build_tree(project.name, documents)

        return {
            "project_id": project.id,
            "project_name": project.name,
            "generated_at": utc_now(),
            "model_used": self.last_model,
            "node_count": _count_nodes(root),
            "root": root,
        }

    def build_tree(self, project_name: str, documents: List[Any]) -> Dict[str, Any]:
        """Assemble the project/document/topic tree.

        Args:
            project_name: Label for the root node.
            documents: The project's documents, in the order to draw them.

        Returns:
            The root node. `last_model` is updated as a side effect.
        """
        generated = self._generated_topics(documents)
        self.last_model = generated[1]
        topics_by_index = generated[0]

        children = []
        for index, document in enumerate(documents, start=1):
            topics = topics_by_index.get(index) or self._structural_topics(document)
            children.append({
                "id": "doc-%s" % document.id,
                "label": document.title,
                "kind": "document",
                "detail": document.source_type,
                "document_id": document.id,
                "children": [
                    {
                        # Namespaced by document id: two sources in one project
                        # can carry the same heading, and a repeated node id
                        # would collapse them into one in the browser.
                        "id": "doc-%s-topic-%d" % (document.id, position),
                        "label": topic,
                        "kind": "topic",
                        "detail": None,
                        "document_id": document.id,
                        "children": [],
                    }
                    for position, topic in enumerate(topics)
                ],
            })

        return {
            "id": "root",
            "label": project_name,
            "kind": "project",
            "detail": None,
            "document_id": None,
            "children": children,
        }

    def _generated_topics(
        self,
        documents: List[Any],
    ) -> tuple[Dict[int, List[str]], str]:
        """Ask the model to name each document's topics.

        Args:
            documents: The project's documents.

        Returns:
            Topics by 1-based document index, and the model name to report.
            Both are empty and `FALLBACK_MODEL` when the model could not be
            used — including when it answered but the answer was unreadable,
            because in that case the structure did the work, not the model.
        """
        if not documents:
            return {}, FALLBACK_MODEL

        try:
            result = self.llm.generate(
                prompt=self._topic_prompt(documents),
                temperature=0.2,
                max_tokens=topic_token_budget(len(documents)),
                system_prompt=TOPIC_SYSTEM_PROMPT,
            )
        except Exception as e:
            # A failed call must not fail the mind map: the structural tree is
            # still worth drawing. Log it, because the fallback looks like a
            # deliberate map and would otherwise hide a broken provider.
            logger.warning(
                "Mind map topic generation failed; falling back to structure",
                error_type=type(e).__name__,
                error=str(e),
            )
            return {}, FALLBACK_MODEL

        topics = parse_llm_topics(result.get("text", ""), len(documents))
        if not topics:
            logger.info(
                "Mind map topics came from document structure",
                model=result.get("model"),
                documents=len(documents),
            )
            return {}, FALLBACK_MODEL

        return topics, result.get("model") or FALLBACK_MODEL

    def _topic_prompt(self, documents: List[Any]) -> str:
        """Compose the single request that covers every document.

        One call rather than one per document: the cost of a mind map should
        not scale with the size of the project.

        Args:
            documents: The project's documents.

        Returns:
            The prompt.
        """
        sections = []
        for index, document in enumerate(documents, start=1):
            excerpt = _document_excerpt(document)
            sections.append(
                "%d. %s\n%s" % (index, document.title, excerpt or "(no text extracted)")
            )

        return (
            "Name the main topics of each source below, for a mind map.\n\n"
            "Rules:\n"
            "- At most %d topics per source, fewest that cover it.\n"
            "- Each topic is a noun phrase of at most six words.\n"
            "- Use only the source's own content; do not invent topics.\n"
            "- Reply with exactly this JSON and nothing else:\n"
            '  {"documents": [{"index": 1, "topics": ["..."]}]}\n\n'
            "Sources:\n\n%s"
        ) % (MAX_TOPICS_PER_DOCUMENT, "\n\n".join(sections))

    def _structural_topics(self, document: Any) -> List[str]:
        """Derive topics without a model, from whatever the document carries.

        Args:
            document: A document with its chunks loaded.

        Returns:
            Topic labels, possibly empty for a document with no text yet.
        """
        chunks = list(document.chunks or [])

        headings = topics_from_headings(chunk.heading_path for chunk in chunks)
        if headings:
            return headings

        text = document.content or "\n".join(chunk.text or "" for chunk in chunks)
        return topics_from_keywords(text)

    def _project_documents(self, db: Session, project: Project) -> List[Document]:
        """List the documents attached to a project, in a stable order.

        Args:
            db: Database session.
            project: The project.

        Returns:
            The documents. Ordered by title after `added_at`, because
            `added_at` comes from SQLite's second-resolution clock and every
            document of one upload ties.
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


def _document_excerpt(document: Any) -> str:
    """Take the opening of a document, for the topic prompt.

    Args:
        document: A document with its chunks loaded.

    Returns:
        At most `DOCUMENT_EXCERPT_CHARS` characters of text.
    """
    text = document.content
    if not text:
        text = "\n".join(chunk.text or "" for chunk in (document.chunks or []))

    return (text or "").strip()[:DOCUMENT_EXCERPT_CHARS]


def _count_nodes(node: Dict[str, Any]) -> int:
    """Count the nodes in a tree, including the root.

    Args:
        node: The root of the tree.

    Returns:
        Total node count.
    """
    return 1 + sum(_count_nodes(child) for child in node["children"])
