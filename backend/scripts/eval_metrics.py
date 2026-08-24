"""Retrieval-quality metrics.

Deliberately dependency-free (stdlib only) so the maths can be unit-tested in
the green suite without loading the ML stack.

Ground truth here is *answer-bearing text*, not chunk ids: a retrieved chunk
counts as relevant when it comes from the expected document and contains one of
the query's `must_contain` strings. That choice is what lets a single question
set compare runs across changes to the chunker, which necessarily move every
chunk boundary and every chunk id.
"""
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence

# Signatures of Wikipedia/site furniture that has no business being retrievable.
# Matched against normalised chunk text; used to report a boilerplate rate
# rather than to filter anything at query time.
BOILERPLATE_SIGNATURES = (
    "toggle the table of contents",
    "what links here",
    "learn how and when to remove",
    "this article needs more citations",
    "please help improve",
    "find sources:",
    "jump to content",
    "create account log in",
    "personal tools",
    "move to sidebar",
    "edit view history",
    "permanent link page information",
    "cite this page",
    "printable version",
    "add languages",
    "本頁面最後修訂於",
    "維基百科，自由的百科全書",
    "檢視方式",
    "不转换 简体 繁體",
)


# Markers of a bibliography entry. Reference lists turned out to be the real
# pollutant: they are dense, numerous and topically close to the article, so they
# outranked genuine passages for every Chinese query in the first measurement.
# The boilerplate signatures above never caught them.
CITATION_MARKERS = (
    "doi:", "arxiv:", "isbn", "issn", "s2cid", "bibcode", "pmid",
    "原始內容", "存檔於", "永久失效連結", "檢自",
)


def normalize(text: str) -> str:
    """Fold text to a form that survives extraction changes.

    Collapses every whitespace run to one space, applies NFKC, and lowercases.
    Deliberately does not strip punctuation: the eval dataset avoids punctuation
    inside `must_contain` strings for exactly that reason.

    Args:
        text: Raw text.

    Returns:
        Normalised text.
    """
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def hit_at_k(relevance: Sequence[bool], k: int) -> float:
    """Whether at least one relevant item appears in the top k.

    Reported as Recall@k. With answer-bearing ground truth there is no fixed
    count of relevant chunks to divide by, so this is a hit rate, and averaging
    it over queries gives the share of questions whose answer was retrievable.

    Args:
        relevance: Relevance flags in rank order.
        k: Cutoff.

    Returns:
        1.0 or 0.0.
    """
    return 1.0 if any(relevance[:k]) else 0.0


def precision_at_k(relevance: Sequence[bool], k: int) -> float:
    """Share of the top k that is relevant.

    Args:
        relevance: Relevance flags in rank order.
        k: Cutoff.

    Returns:
        Precision in [0, 1]; 0.0 when nothing was retrieved.
    """
    window = relevance[:k]
    if not window:
        return 0.0
    return sum(1 for hit in window if hit) / len(window)


def reciprocal_rank(relevance: Sequence[bool], k: Optional[int] = None) -> float:
    """Reciprocal of the first relevant rank, or 0.0 if there is none.

    Args:
        relevance: Relevance flags in rank order.
        k: Optional cutoff.

    Returns:
        1/rank of the first hit.
    """
    window = relevance if k is None else relevance[:k]
    for index, hit in enumerate(window, start=1):
        if hit:
            return 1.0 / index
    return 0.0


def mean(values: Iterable[float]) -> float:
    """Arithmetic mean, 0.0 for an empty input.

    Args:
        values: Numbers.

    Returns:
        The mean.
    """
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile, 0.0 for an empty input.

    Args:
        values: Numbers, any order.
        fraction: Percentile as a fraction, e.g. 0.95.

    Returns:
        The value at that rank.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return float(ordered[index])


def is_boilerplate(text: str, signatures: Sequence[str] = BOILERPLATE_SIGNATURES) -> bool:
    """Whether a chunk looks like site furniture rather than content.

    Args:
        text: Chunk text.
        signatures: Lowercased substrings to look for.

    Returns:
        True if any signature is present.
    """
    haystack = normalize(text)
    return any(signature in haystack for signature in signatures)


def squash(text: str) -> str:
    """Normalise and drop whitespace entirely.

    HTML extraction injects a separator between inline elements, which lands
    *inside* Chinese sentences: a linked term comes back as "類神經網路 中一種".
    Fixing the extractor changes where those spaces fall, so a whitespace-
    sensitive match would score the same chunk differently before and after.
    Comparing squashed text keeps one question set valid across that change.

    Args:
        text: Any text.

    Returns:
        Normalised text with every space removed.
    """
    return re.sub(r"\s+", "", normalize(text))


def is_citation_like(text: str) -> bool:
    """Whether a chunk reads as a bibliography entry rather than prose.

    Two markers are required so that an article legitimately mentioning a DOI in
    one sentence is not flagged.

    Args:
        text: Chunk text.

    Returns:
        True if the chunk looks like reference-list output.
    """
    haystack = normalize(text)
    return sum(1 for marker in CITATION_MARKERS if marker in haystack) >= 2


def judge(chunk_text: str, must_contain: Sequence[str]) -> bool:
    """Whether a chunk carries the answer.

    Args:
        chunk_text: Retrieved chunk text.
        must_contain: Answer-bearing strings; any one is enough.

    Returns:
        True if at least one string is present, ignoring whitespace placement.
    """
    haystack = squash(chunk_text)
    return any(squash(needle) in haystack for needle in must_contain)


def summarise(relevance_by_query: Dict[str, List[bool]], cutoffs=(1, 3, 5, 10)) -> Dict[str, float]:
    """Aggregate per-query relevance lists into the headline metrics.

    Args:
        relevance_by_query: Query id to relevance flags in rank order.
        cutoffs: The k values to report.

    Returns:
        Metric name to value.
    """
    lists = list(relevance_by_query.values())
    summary: Dict[str, float] = {"queries": len(lists)}
    for k in cutoffs:
        summary[f"recall_at_{k}"] = mean(hit_at_k(r, k) for r in lists)
    summary["precision_at_5"] = mean(precision_at_k(r, 5) for r in lists)
    summary["mrr_at_10"] = mean(reciprocal_rank(r, 10) for r in lists)
    return summary


def index_health(chunk_texts: Sequence[str], chunk_size: int, headings: Sequence[Optional[str]]) -> Dict[str, float]:
    """Describe the shape of the index the retriever has to work with.

    Args:
        chunk_texts: Every chunk's text.
        chunk_size: The configured chunk size, for the oversize share.
        headings: Each chunk's heading_path, aligned with chunk_texts.

    Returns:
        Counts, length percentiles and problem shares.
    """
    lengths = [len(text) for text in chunk_texts]
    total = len(lengths) or 1
    return {
        "chunks": len(lengths),
        "len_p50": percentile(lengths, 0.50),
        "len_p95": percentile(lengths, 0.95),
        "len_max": float(max(lengths)) if lengths else 0.0,
        "share_tiny_lt_80": sum(1 for n in lengths if n < 80) / total,
        "share_oversize_gt_2x": sum(1 for n in lengths if n > 2 * chunk_size) / total,
        "share_boilerplate": sum(1 for text in chunk_texts if is_boilerplate(text)) / total,
        "share_citation_like": sum(1 for text in chunk_texts if is_citation_like(text)) / total,
        "share_with_heading_path": sum(1 for h in headings if h) / total,
    }


def retrieval_performance(results: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """Aggregate request latency and candidate-pool sizes.

    Args:
        results: Per-query eval rows carrying latency and candidate counts.

    Returns:
        Comparable latency percentiles and mean candidate counts.
    """
    latencies = [float(row.get("latency_ms", 0.0)) for row in results]
    return {
        "latency_ms_mean": mean(latencies),
        "latency_ms_p50": percentile(latencies, 0.50),
        "latency_ms_p95": percentile(latencies, 0.95),
        "latency_ms_max": max(latencies, default=0.0),
        "dense_candidates_mean": mean(
            float(row.get("dense_candidates", 0)) for row in results
        ),
        "lexical_candidates_mean": mean(
            float(row.get("lexical_candidates", 0)) for row in results
        ),
        "fused_candidates_mean": mean(
            float(row.get("fused_candidates", 0)) for row in results
        ),
    }
