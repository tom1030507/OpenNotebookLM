"""Lexical scoring and rank fusion for hybrid retrieval.

Pure functions, stdlib only — no model, no extra dependency, no memory cost.
That constraint is deliberate: this project runs on an 8 GB host where a
cross-encoder reranker does not fit.

Why a lexical signal is needed at all: with a multilingual e5 model the cosine
similarities sit compressed in a narrow band (measured here: 0.67-0.71 across
both relevant and irrelevant chunks, a spread of ~0.01 between rank 1 and rank
10). Dense ranking alone is therefore close to noise for exact-term questions,
and a proper name that appears verbatim in the text is the strongest evidence
available. The previous "rerank" tried to supply that with
`set(query.lower().split())`, which yields a single token for a Chinese sentence
and so scored zero for exactly the languages the multilingual model was chosen
to serve.
"""
import math
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Callable, Dict, Iterable, List, Sequence

# Han, Hiragana, Katakana and Hangul. Runs of these carry no spaces, so they are
# tokenised as overlapping character bigrams instead of by splitting.
CJK_PATTERN = re.compile(
    "["
    "\u3040-\u30ff"  # Hiragana, Katakana
    "\u3400-\u4dbf"  # CJK unified ideographs, extension A
    "\u4e00-\u9fff"  # CJK unified ideographs
    "\uf900-\ufaff"  # CJK compatibility ideographs
    "\uac00-\ud7af"  # Hangul syllables
    "]+"
)

# Latin/digit words, keeping internal hyphens and dots so "query-key", "bge-m3"
# and "u.s." survive as one token.
WORD_PATTERN = re.compile(r"[a-z0-9]+(?:[-_.'][a-z0-9]+)*")

BM25_K1 = 1.2
BM25_B = 0.75

# Standard RRF constant from Cormack et al.; large enough that the fusion is
# driven by rank agreement rather than by the top rank of either list.
RRF_K = 60


def tokenize(text: str) -> List[str]:
    """Tokenise mixed Chinese/English text for lexical matching.

    Args:
        text: Any text.

    Returns:
        Lowercased tokens: Latin words plus CJK character bigrams.
    """
    if not text:
        return []

    folded = unicodedata.normalize("NFKC", text).lower()

    tokens: List[str] = []
    for run in CJK_PATTERN.findall(folded):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))

    tokens.extend(WORD_PATTERN.findall(CJK_PATTERN.sub(" ", folded)))
    return tokens


def bm25_scores(
    query_tokens: Sequence[str],
    documents: Sequence[Sequence[str]],
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> List[float]:
    """Score every document against the query with Okapi BM25.

    Statistics come from the documents passed in, i.e. the chunks in scope for
    this query, so a term that is common in this project is discounted for this
    project.

    Args:
        query_tokens: Tokenised query.
        documents: One token list per document, in a stable order.
        k1: Term-frequency saturation.
        b: Length-normalisation strength.

    Returns:
        One score per document, aligned with `documents`.
    """
    if not documents or not query_tokens:
        return [0.0] * len(documents)

    counts = [Counter(tokens) for tokens in documents]
    lengths = [len(tokens) for tokens in documents]
    total = len(documents)
    average_length = sum(lengths) / total if total else 0.0

    document_frequency: Counter = Counter()
    for count in counts:
        document_frequency.update(count.keys())

    weights = {
        token: math.log(
            1 + (total - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5)
        )
        for token in set(query_tokens)
        if document_frequency.get(token)
    }
    if not weights:
        return [0.0] * total

    scores = []
    for count, length in zip(counts, lengths):
        score = 0.0
        for token, weight in weights.items():
            frequency = count.get(token, 0)
            if not frequency:
                continue
            denominator = frequency + k1 * (
                1 - b + b * (length / average_length if average_length else 1.0)
            )
            score += weight * frequency * (k1 + 1) / denominator
        scores.append(score)
    return scores


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[str]], k: int = RRF_K
) -> Dict[str, float]:
    """Fuse several ranked id lists into one score per id.

    Fusing *ranks* rather than scores is what makes this safe here. The scores
    being combined live on incomparable scales — cosine in a narrow high band,
    BM25 unbounded from zero — and the previous linear blend simply added them,
    so the weights did not mean what they claimed.

    Args:
        rankings: Ranked id lists, best first.
        k: Rank-damping constant.

    Returns:
        Id to fused score; higher is better.
    """
    scores: Dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, identifier in enumerate(ranking, start=1):
            scores[identifier] += 1.0 / (k + rank)
    return dict(scores)


def fuse_rankings(
    rankings: Iterable[Sequence[str]], k: int = RRF_K
) -> Dict[str, tuple]:
    """Fuse ranked id lists, ranking by the best evidence rather than the sum.

    Plain RRF sums the reciprocal ranks, which credits an id for merely appearing
    in both lists. That backfires when one retriever is weak: measured here, the
    dense list and the BM25 list shared 11-14 of their 30 candidates, and every
    one of those doubly-credited items outranked a BM25 rank-1 hit that the dense
    search had missed entirely. Two questions whose answer BM25 put first were
    pushed out of the top ten that way.

    So the primary key is the *best* reciprocal rank any list gave an id -- a
    verbatim term match at rank one is strong evidence on its own -- and the sum
    is kept as the tie-break, which is where agreement between retrievers earns
    its keep.

    Args:
        rankings: Ranked id lists, best first.
        k: Rank-damping constant.

    Returns:
        Id to (best, total) reciprocal-rank scores; sort descending.
    """
    totals = reciprocal_rank_fusion(rankings, k=k)
    best: Dict[str, float] = {}
    for ranking in rankings:
        for rank, identifier in enumerate(ranking, start=1):
            contribution = 1.0 / (k + rank)
            if contribution > best.get(identifier, 0.0):
                best[identifier] = contribution
    return {identifier: (best[identifier], totals[identifier]) for identifier in best}


def jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    """Token-set overlap of two token sequences.

    Args:
        left: Tokens.
        right: Tokens.

    Returns:
        Similarity in [0, 1].
    """
    first, second = set(left), set(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def dedupe_near_duplicates(
    items: Sequence[dict],
    tokens_of: Callable[[dict], Sequence[str]],
    threshold: float,
) -> List[dict]:
    """Drop candidates that repeat one already kept.

    Chunk overlap means neighbouring chunks share text, so without this a single
    passage can occupy several of the few slots the prompt has room for.

    Args:
        items: Candidates in rank order.
        tokens_of: Extracts the tokens to compare for one candidate.
        threshold: Jaccard similarity at or above which a candidate is dropped.

    Returns:
        The kept candidates, in the order given.
    """
    if threshold >= 1.0:
        return list(items)

    kept: List[dict] = []
    kept_tokens: List[Sequence[str]] = []
    for item in items:
        tokens = tokens_of(item)
        if any(jaccard(tokens, seen) >= threshold for seen in kept_tokens):
            continue
        kept.append(item)
        kept_tokens.append(tokens)
    return kept
