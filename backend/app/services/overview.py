"""Select overview passages without mistaking a bibliography for a summary."""
import re
from typing import Any, List, Sequence


_DOCUMENT = r"(?:this|the)\s+(?:paper|article|document|study|report|source)"
_OVERVIEW_EN = re.compile(
    rf"(?:please\s+)?(?:"
    rf"what\s+is\s+{_DOCUMENT}\s+about|"
    rf"summari[sz]e\s+{_DOCUMENT}|"
    rf"(?:give\s+me\s+|provide\s+)?(?:a\s+summary|an?\s+overview)\s+of\s+{_DOCUMENT}|"
    rf"what\s+are\s+the\s+(?:main|key)\s+(?:contributions|findings|points)\s+of\s+{_DOCUMENT}"
    r")[.!?\s]*",
    re.IGNORECASE,
)
_OVERVIEW_ZH = re.compile(
    r"(?:(?:請|请|幫我|帮我)\s*)?(?:"
    r"(?:這|这)(?:篇|份|個|个)?(?:論文|论文|文章|文件|報告|报告)"
    r"(?:主要)?(?:在)?(?:講|讲|說|说|談|谈)(?:些)?什[麼么]|"
    r"(?:總結|总结|摘要|概述)(?:一下)?(?:這|这)(?:篇|份|個|个)?"
    r"(?:論文|论文|文章|文件|報告|报告)"
    r")[。！？?！\s]*"
)
_SECTIONS = {
    "abstract": "abstract", "summary": "abstract", "摘要": "abstract",
    "introduction": "introduction", "引言": "introduction", "緒論": "introduction",
    "绪论": "introduction", "前言": "introduction",
    "conclusion": "conclusion", "conclusions": "conclusion",
    "conclusion and future work": "conclusion", "結論": "conclusion", "结论": "conclusion",
    "model architecture": "method", "methods": "method", "method": "method",
    "methodology": "method", "方法": "method",
    "references": "references", "bibliography": "references",
    "參考文獻": "references", "参考文献": "references",
    "acknowledgements": "end", "acknowledgments": "end",
}


def is_overview_query(query: str) -> bool:
    """Recognize whole-document requests without redirecting detail questions.

    Args:
        query: The current user question, without conversation history.

    Returns:
        Whether the question explicitly requests a document overview.
    """
    normalized = " ".join(query.strip().split())
    return bool(_OVERVIEW_EN.fullmatch(normalized) or _OVERVIEW_ZH.fullmatch(normalized))


def _section(text: str) -> str | None:
    normalized = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", text.strip())
    return _SECTIONS.get(normalized.rstrip(":：").strip().casefold())


def overview_passage_text(text: str) -> str:
    """Start an overview passage at its section heading when one is present.

    Args:
        text: The original passage, possibly beginning with author metadata.

    Returns:
        A verbatim suffix beginning at the heading, or the unchanged passage.
    """
    offset = 0
    for line in text.splitlines(keepends=True):
        if _section(line) in {"abstract", "conclusion", "introduction", "method"}:
            return text[offset:]
        offset += len(line)
    return text


def overview_chunk_ids(chunks: Sequence[Any], top_k: int) -> List[str]:
    """Keep adjacent abstract and conclusion passages from one ordered document.

    Args:
        chunks: Rows containing id, text and heading_path in document order.
        top_k: Maximum number of passages to select.

    Returns:
        Unique chunk ids in overview priority order, or none if headings are absent.
    """
    headings = []
    for chunk in chunks:
        # Check the full final heading as well; splitting on spaces would lose
        # headings such as "Model Architecture".
        heading = re.split(r"\s*(?:/|>)\s*", chunk.heading_path or "")[-1]
        kinds = [_section(heading)] + [_section(line) for line in chunk.text.splitlines()]
        headings.append(next((kind for kind in kinds if kind), None))

    # A referenced paper can itself have a title such as "Abstract". Never
    # treat headings inside the bibliography as evidence about this document.
    end = next((i for i, kind in enumerate(headings) if kind == "references"), len(chunks))
    selected = []
    for section, width in [("abstract", 3), ("conclusion", 2), ("introduction", 2), ("method", 2)]:
        start = next((i for i in range(end) if headings[i] == section), None)
        if start is None:
            continue
        for i in range(start, min(start + width, end)):
            if i > start and headings[i] not in (None, section):
                break
            if chunks[i].id not in selected:
                selected.append(chunks[i].id)
            if len(selected) >= top_k:
                return selected
    return selected
