"""Turn a project's sources into the scene script Studio plays as a video.

There is no video file. Rendering one server-side would mean drawing slides,
synthesising speech and muxing with ffmpeg — a large image and a set of new
failure modes for something the browser already does: Studio's audio summary
takes its text from the backend and its voice from the Web Speech API. So this
service produces the script and the browser plays it, the same split the mind
map uses for its tree.

The scene skeleton is decided here and not by the model: a title card, one
scene per source in project order, and a closing recap. That keeps the length
predictable, keeps the token budget a function of the source count, and keeps
the script playable when there is no model at all — the model only writes the
source scenes.

Without a usable model, each source scene is extracted instead, in descending
order of quality:

1. the chunks' ``heading_path`` — real document structure, already in the
   database for anything imported from the web;
2. the document's opening sentences;
3. the most frequent meaningful words.

Sentences sit in the middle because a keyword cannot be read aloud, and the
narration has to be. Which one answered is reported as ``model_used``, the same
way ``/query`` and the mind map report it: a written script and an extracted one
look alike on screen, and the listener has to be able to tell them apart.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog
from sqlalchemy.orm import Session

from app.db.models import Project
from app.services.llm import FALLBACK_MODEL, LLMService
from app.services.source_digest import (
    document_excerpt,
    document_text,
    load_json_object,
    project_documents,
    topics_from_headings,
    topics_from_keywords,
)
from app.utils.time import utc_now

logger = structlog.get_logger()

# More lines than this stops being a slide and starts being a handout.
MAX_BULLETS_PER_SCENE = 4

# A slide line has to fit on the slide. Longer bullets are shortened at a word
# boundary rather than wrapped into a paragraph.
BULLET_MAX_CHARS = 120

# Extracted text is full of headers, page numbers and captions. Anything
# shorter than this many words is one of those, not a sentence.
MIN_SENTENCE_WORDS = 3

# The script call's token budget, which has to satisfy two limits at once.
#
# From below: a reasoning model writes its thinking into this same budget before
# any content, so the floor has to clear the thinking or the reply comes back
# empty and the script silently falls back to extraction — which is what Groq's
# qwen3.6-27b did to the mind map at the provider's configured 2048-token floor.
#
# From above: a provider counts the prompt and `max_tokens` together against its
# rate limit and refuses the whole request before the model sees it. Groq's
# on-demand tier allows 8000 per minute, and a generous budget is what pushes a
# six-source project over it — a 413 that costs the narration entirely.
#
# So the budget is fitted to measured use rather than padded. Against
# qwen3.6-27b, completions were 2757 for one document; 2555, 3272, 3663 and
# 4022 across four runs at two; 4263 at four; 4271 at six. Almost all of it is
# fixed reasoning cost, and run-to-run variance at one document count exceeds
# the difference between counts, so the base is large and the slope small.
#
# 4352 + 256 leaves the worst run measured at each count between 840 and 1850
# tokens spare, and keeps a six-document request at 7555 including its prompt —
# inside the 8000 ceiling, where the previous 900-per-document slope asked for
# 10139 and was refused.
NARRATION_TOKEN_BUDGET_BASE = 4352
NARRATION_TOKEN_BUDGET_PER_DOCUMENT = 256
# One script is one request; a 200-source project must not make it unbounded.
# Well past the point where a small tier's per-minute ceiling refuses the call,
# which is why a large project can still fall back to extraction on one.
NARRATION_TOKEN_BUDGET_CAP = 16384

# Reading pace used to size the progress bar only. Playback is driven by the
# voice finishing a scene, not by this estimate, so being out by a few seconds
# costs nothing.
WORDS_PER_SECOND = 2.6
# A scene with no narration still has to stay on screen long enough to read.
MIN_SCENE_SECONDS = 1

SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
SENTENCE_ENDINGS = (".", "!", "?")

SCRIPT_SYSTEM_PROMPT = (
    "You write short spoken walkthroughs of study material. Answer with a "
    "single JSON object and nothing else."
)


def narration_token_budget(document_count: int) -> int:
    """Size the script call's token budget for the project.

    Args:
        document_count: How many documents the one call covers.

    Returns:
        A `max_tokens` value with room for a reasoning model's thinking as well
        as the JSON, capped so a large project stays one bounded request.
    """
    budget = (
        NARRATION_TOKEN_BUDGET_BASE
        + NARRATION_TOKEN_BUDGET_PER_DOCUMENT * document_count
    )

    return min(budget, NARRATION_TOKEN_BUDGET_CAP)


def shorten(text: str, limit: int = BULLET_MAX_CHARS) -> str:
    """Fit a line onto a slide, cutting at a word boundary.

    Args:
        text: The line, with any internal whitespace.
        limit: Most characters to keep before the ellipsis.

    Returns:
        The line, collapsed to single spaces, with an ellipsis appended if it
        had to be cut. Never cut mid-word: a truncated word reads as a typo.
    """
    trimmed = " ".join((text or "").split())
    if len(trimmed) <= limit:
        return trimmed

    head = trimmed[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")

    return "%s…" % (head or trimmed[:limit])


def leading_sentences(
    text: Optional[str],
    limit: int = MAX_BULLETS_PER_SCENE,
) -> List[str]:
    """Take the opening sentences of a document.

    The middle of the extraction chain: a document with no headings still opens
    by saying what it is about, and unlike a keyword a sentence can be read out.

    A candidate has to end in terminal punctuation to count. Text with no
    sentence ends at all — a table, a word list, a bad PDF extraction — is not
    prose, and passing it off as a sentence would put a wall of words on a slide.

    Args:
        text: Document text, or None for a document not yet extracted.
        limit: Most sentences to return.

    Returns:
        The opening sentences, each shortened to fit a slide line.
    """
    if not text or not text.strip():
        return []

    sentences: List[str] = []
    for candidate in SENTENCE_BREAK.split(" ".join(text.split())):
        sentence = candidate.strip()
        if not sentence.endswith(SENTENCE_ENDINGS):
            continue
        if len(sentence.split()) < MIN_SENTENCE_WORDS:
            continue

        sentences.append(shorten(sentence))
        if len(sentences) == limit:
            break

    return sentences


def estimate_seconds(narrations: Iterable[Optional[str]]) -> int:
    """Estimate how long the script takes to read out.

    Args:
        narrations: Each scene's narration, in order.

    Returns:
        Whole seconds, with a floor per scene so a silent one still has time on
        screen. Used to draw the progress bar; the voice drives playback.
    """
    total = 0.0
    for narration in narrations:
        words = len((narration or "").split())
        total += max(float(MIN_SCENE_SECONDS), words / WORDS_PER_SECOND)

    return int(round(total))


def parse_llm_scenes(text: str, document_count: int) -> Dict[int, Dict[str, Any]]:
    """Read a model's reply into written scenes keyed by document index.

    The reply is untrusted input: models wrap JSON in prose and code fences,
    invent indexes, and — when no provider is configured at all — answer with
    the extractive fallback, which is prose. Anything that cannot be read as the
    agreed shape yields nothing, so the caller extracts instead of narrating
    garbage.

    An entry needs narration to be usable. Bullets and a headline without it are
    a handout, not a scene, and the extraction path writes better narration than
    a stitched-together fragment would.

    Indexes rather than ids keep uuids out of the prompt and the reply, where
    they only invite the model to mistype one.

    Args:
        text: The model's raw reply.
        document_count: How many documents were asked about. Indexes are
            1-based and anything outside the range is dropped.

    Returns:
        Written scenes by document index. Empty if the reply was unusable.
    """
    payload = load_json_object(text)
    if payload is None:
        return {}

    entries = payload.get("scenes")
    if not isinstance(entries, list):
        return {}

    scenes: Dict[int, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        index = entry.get("index")
        # `bool` is an `int` in Python, and `{"index": true}` is not a document.
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        if not 1 <= index <= document_count:
            continue

        narration = entry.get("narration")
        if not isinstance(narration, str) or not narration.strip():
            continue

        scenes[index] = {
            "headline": _clean_line(entry.get("headline")),
            "bullets": _clean_bullets(entry.get("bullets")),
            "narration": " ".join(narration.split()),
        }

    return scenes


def _clean_line(value: Any) -> Optional[str]:
    """Keep a model-written single line, or nothing.

    Args:
        value: The raw value from the reply.

    Returns:
        The line shortened to fit a slide, or None if it was not usable text.
    """
    if not isinstance(value, str) or not value.strip():
        return None

    return shorten(value)


def _clean_bullets(bullets: Any) -> List[str]:
    """Keep the usable bullets from whatever the model listed.

    Args:
        bullets: The `bullets` value from one entry of the reply.

    Returns:
        Trimmed, non-empty lines, each shortened to fit, capped at
        `MAX_BULLETS_PER_SCENE`.
    """
    if not isinstance(bullets, list):
        return []

    cleaned: List[str] = []
    for bullet in bullets:
        if not isinstance(bullet, str) or not bullet.strip():
            continue
        cleaned.append(shorten(bullet))
        if len(cleaned) == MAX_BULLETS_PER_SCENE:
            break

    return cleaned


def _join_phrase(labels: List[str]) -> str:
    """Join labels into something that reads aloud as a list.

    Args:
        labels: The labels, already in the order to say them.

    Returns:
        A spoken list. Trailing full stops are dropped so the sentence the
        caller wraps this in does not end in two of them.
    """
    spoken = [label.rstrip(".") for label in labels if label]
    if not spoken:
        return ""
    if len(spoken) == 1:
        return spoken[0]

    return "%s and %s" % (", ".join(spoken[:-1]), spoken[-1])


def _plural(count: int) -> str:
    """Return the plural suffix for a count of sources."""
    return "" if count == 1 else "s"


class VideoSummaryService:
    """Build the scene script Studio's video summary plays."""

    def __init__(self, llm_service: Optional[Any] = None):
        """Wire up the model used to write the source scenes.

        Args:
            llm_service: Object with `generate`. Defaults to the shared
                `LLMService`, whose construction performs no network I/O.
        """
        self.llm = llm_service if llm_service is not None else LLMService()
        # What wrote the source scenes of the script built most recently. Read
        # by the route to fill `model_used`, so a listener can tell a written
        # script from an extracted one.
        self.last_model: str = FALLBACK_MODEL

    def generate(self, db: Session, project: Project) -> Dict[str, Any]:
        """Build the video summary script for a project.

        Args:
            db: Database session.
            project: The project to summarise. Ownership is the caller's
                problem — resolve the id through `routers.ownership` first.

        Returns:
            The scenes plus the metadata the API exposes: which model wrote
            them, when they were built, and how long they take to play.
        """
        documents = project_documents(db, project)
        generated_at = utc_now()
        scenes = self.build_scenes(project.name, documents, generated_at)

        return {
            "project_id": project.id,
            "project_name": project.name,
            "generated_at": generated_at,
            "model_used": self.last_model,
            "scene_count": len(scenes),
            "estimated_seconds": estimate_seconds(
                scene["narration"] for scene in scenes
            ),
            "scenes": scenes,
        }

    def build_scenes(
        self,
        project_name: str,
        documents: List[Any],
        generated_at: datetime,
    ) -> List[Dict[str, Any]]:
        """Assemble the title, source and closing scenes.

        Args:
            project_name: Name of the project being summarised.
            documents: The project's documents, in the order to play them.
            generated_at: When the script was built, for the title card.

        Returns:
            The scenes in playback order. `last_model` is updated as a side
            effect.
        """
        written, model = self._written_scenes(documents)
        self.last_model = model

        source_scenes = [
            self._source_scene(document, written.get(index))
            for index, document in enumerate(documents, start=1)
        ]

        return [
            self._title_scene(project_name, len(documents), generated_at),
            *source_scenes,
            self._closing_scene(project_name, source_scenes),
        ]

    def _title_scene(
        self,
        project_name: str,
        source_count: int,
        generated_at: datetime,
    ) -> Dict[str, Any]:
        """Compose the opening card.

        Always written here rather than asked of the model: it states facts the
        database already holds, and a model given the chance would embellish
        them.

        Args:
            project_name: Name of the project.
            source_count: How many sources the script covers.
            generated_at: When the script was built.

        Returns:
            The title scene.
        """
        sources = "%d source%s" % (source_count, _plural(source_count))
        # `%-d` is not portable, and a leading zero reads oddly when spoken.
        date = "%d %s" % (generated_at.day, generated_at.strftime("%B %Y"))

        if source_count:
            bullets = [sources, "Generated %s" % date]
            narration = (
                "This is a video summary of the project %s. It covers %s."
                % (project_name, sources)
            )
        else:
            bullets = ["No sources yet", "Generated %s" % date]
            narration = (
                "The project %s has no sources yet. Add one and this summary "
                "will cover it." % project_name
            )

        return {
            "id": "title",
            "kind": "title",
            "headline": project_name,
            "bullets": bullets,
            "narration": narration,
            "document_id": None,
            "source_label": None,
        }

    def _source_scene(
        self,
        document: Any,
        written: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compose one source's scene, written by the model or extracted.

        Args:
            document: The document this scene covers, with its chunks loaded.
            written: What the model wrote for it, or None to extract instead.

        Returns:
            The source scene.
        """
        bullets, origin = self._extracted_bullets(document)

        if written:
            headline = written["headline"] or document.title
            # A model that writes a paragraph and no points still needs points:
            # a scene with nothing on the slide is a voice over a blank screen.
            scene_bullets = written["bullets"] or bullets
            narration = written["narration"]
        else:
            headline = document.title
            scene_bullets = bullets
            narration = self._extracted_narration(document, bullets, origin)

        return {
            # Namespaced by document id: two sources in one project can carry
            # the same title, and a repeated scene id would collapse them into
            # one in the browser.
            "id": "doc-%s" % document.id,
            "kind": "source",
            "headline": headline,
            "bullets": scene_bullets,
            "narration": narration,
            "document_id": document.id,
            # The title, always — the headline may be the model's sentence, and
            # the slide has to name the source it is citing.
            "source_label": document.title,
        }

    def _closing_scene(
        self,
        project_name: str,
        source_scenes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compose the recap, from the scenes rather than from the model.

        Args:
            project_name: Name of the project.
            source_scenes: The source scenes, in playback order.

        Returns:
            The closing scene.
        """
        count = len(source_scenes)
        headlines = [scene["headline"] for scene in source_scenes]
        shown = headlines[:MAX_BULLETS_PER_SCENE]

        if not shown:
            narration = "There is nothing to summarise in %s yet." % project_name
        else:
            listed = _join_phrase(shown)
            # Say what was left off rather than implying four is all there was.
            if count > len(shown):
                listed = "%s, and %d more" % (listed, count - len(shown))
            narration = "That is %s, covering %d source%s: %s." % (
                project_name, count, _plural(count), listed,
            )

        return {
            "id": "closing",
            "kind": "closing",
            "headline": "What this project covers",
            "bullets": shown,
            "narration": narration,
            "document_id": None,
            "source_label": None,
        }

    def _extracted_bullets(self, document: Any) -> Tuple[List[str], str]:
        """Derive a source's bullets without a model.

        Args:
            document: A document with its chunks loaded.

        Returns:
            The bullets and which step of the chain produced them — the caller
            words the narration differently for sentences than for labels.
            `("", "none")` for a document with no text yet.
        """
        chunks = list(document.chunks or [])

        headings = topics_from_headings(
            (chunk.heading_path for chunk in chunks),
            limit=MAX_BULLETS_PER_SCENE,
        )
        if headings:
            return [shorten(heading) for heading in headings], "headings"

        text = document_text(document)

        sentences = leading_sentences(text)
        if sentences:
            return sentences, "sentences"

        keywords = topics_from_keywords(text, limit=MAX_BULLETS_PER_SCENE)
        if keywords:
            return keywords, "keywords"

        return [], "none"

    def _extracted_narration(
        self,
        document: Any,
        bullets: List[str],
        origin: str,
    ) -> str:
        """Compose narration for a scene no model wrote.

        Flat by design. `model_used` reports the fallback, so a listener knows
        this was assembled rather than written, and a plain sentence is better
        than a stitched-together imitation of one.

        Args:
            document: The document the scene covers.
            bullets: The scene's bullets.
            origin: Which step of the extraction chain produced them.

        Returns:
            Narration, never empty.
        """
        if origin == "sentences":
            # Already sentences: reading them out is the honest thing to do.
            return "This source is %s. It begins: %s" % (
                document.title, " ".join(bullets),
            )

        if bullets:
            return "This source is %s. It covers %s." % (
                document.title, _join_phrase(bullets),
            )

        return (
            "This source is %s. Its text has not been extracted yet."
            % document.title
        )

    def _written_scenes(
        self,
        documents: List[Any],
    ) -> Tuple[Dict[int, Dict[str, Any]], str]:
        """Ask the model to write a scene for each document.

        Args:
            documents: The project's documents.

        Returns:
            Written scenes by 1-based document index, and the model name to
            report. Both are empty and `FALLBACK_MODEL` when the model could
            not be used — including when it answered but the answer was
            unreadable, because then extraction did the work, not the model.
        """
        if not documents:
            return {}, FALLBACK_MODEL

        try:
            result = self.llm.generate(
                prompt=self._script_prompt(documents),
                temperature=0.3,
                max_tokens=narration_token_budget(len(documents)),
                system_prompt=SCRIPT_SYSTEM_PROMPT,
            )
        except Exception as e:
            # A failed call must not fail the script: the extracted one is
            # still worth playing. Log it, because the fallback looks like a
            # deliberate script and would otherwise hide a broken provider.
            logger.warning(
                "Video summary narration failed; falling back to extraction",
                error_type=type(e).__name__,
                error=str(e),
            )
            return {}, FALLBACK_MODEL

        scenes = parse_llm_scenes(result.get("text", ""), len(documents))
        if not scenes:
            logger.info(
                "Video summary script came from document structure",
                model=result.get("model"),
                documents=len(documents),
            )
            return {}, FALLBACK_MODEL

        return scenes, result.get("model") or FALLBACK_MODEL

    def _script_prompt(self, documents: List[Any]) -> str:
        """Compose the single request that covers every document.

        One call rather than one per document: the cost of a summary should not
        scale with the size of the project.

        Args:
            documents: The project's documents.

        Returns:
            The prompt.
        """
        sections = []
        for index, document in enumerate(documents, start=1):
            excerpt = document_excerpt(document)
            sections.append(
                "%d. %s\n%s" % (
                    index, document.title, excerpt or "(no text extracted)",
                )
            )

        return (
            "Write one slide of a spoken walkthrough for each source below.\n\n"
            "Rules:\n"
            "- headline: one clause naming what the source says, at most ten "
            "words.\n"
            "- bullets: at most %d, each at most twelve words.\n"
            "- narration: two or three sentences to be read aloud over the "
            "slide. Plain prose, no markup, no lists.\n"
            "- Use only the source's own content; do not invent findings.\n"
            "- Reply with exactly this JSON and nothing else:\n"
            '  {"scenes": [{"index": 1, "headline": "...", '
            '"bullets": ["..."], "narration": "..."}]}\n\n'
            "Sources:\n\n%s"
        ) % (MAX_BULLETS_PER_SCENE, "\n\n".join(sections))
