"""Embedding-based checks for sentences and their cited passages."""
import re
from typing import Any, Dict, List

import numpy as np


SOURCE_LABEL = re.compile(r"\[Source\s+(\d+)(?::[^\]\r\n]*)?\]", re.IGNORECASE)
SENTENCE_END = re.compile(
    r"(?<!\d)[.!?。！？]+(?:\s*\[Source\s+\d+\])*|\n+",
    re.IGNORECASE,
)


def check_citation_support(
    answer: str,
    context_chunks: List[Dict[str, Any]],
    embedding_service: Any,
    threshold: float,
) -> List[Dict[str, Any]]:
    """Score each cited sentence against only the passages it names.

    Args:
        answer: Final answer text after invalid source labels are removed.
        context_chunks: Passages in source-label order.
        embedding_service: Existing embedding service with role-aware batching.
        threshold: Minimum cosine similarity considered supported.

    Returns:
        JSON-safe checks for sentences with at least one valid citation.
    """
    sentences = []
    sentence_index = 0
    start = 0
    for boundary in SENTENCE_END.finditer(answer):
        sentence = answer[start:boundary.end()].strip()
        if sentence:
            labels = list(dict.fromkeys(
                int(match.group(1))
                for match in SOURCE_LABEL.finditer(sentence)
                if 1 <= int(match.group(1)) <= len(context_chunks)
                and str(context_chunks[int(match.group(1)) - 1].get("text", "")).strip()
            ))
            if labels:
                sentence_text = SOURCE_LABEL.sub("", sentence).strip()
                if sentence_text:
                    sentences.append((sentence_index, sentence_text, labels))
            sentence_index += 1
        start = boundary.end()

    sentence = answer[start:].strip()
    if sentence:
        labels = list(dict.fromkeys(
            int(match.group(1))
            for match in SOURCE_LABEL.finditer(sentence)
            if 1 <= int(match.group(1)) <= len(context_chunks)
            and str(context_chunks[int(match.group(1)) - 1].get("text", "")).strip()
        ))
        if labels:
            sentence_text = SOURCE_LABEL.sub("", sentence).strip()
            if sentence_text:
                sentences.append((sentence_index, sentence_text, labels))

    if not sentences:
        return []

    passage_labels = list(dict.fromkeys(
        label for _, _, labels in sentences for label in labels
    ))
    passage_texts = [str(context_chunks[label - 1]["text"]) for label in passage_labels]
    sentence_embeddings = np.asarray(embedding_service.generate_embedding(
        [text for _, text, _ in sentences], role="query",
    ))
    passage_embeddings = np.asarray(embedding_service.generate_embedding(
        passage_texts, role="passage",
    ))
    passage_index = {label: index for index, label in enumerate(passage_labels)}

    checks = []
    for index, (_, _, labels) in enumerate(sentences):
        similarity = max(
            float(np.dot(sentence_embeddings[index], passage_embeddings[passage_index[label]]))
            for label in labels
        )
        score = round(float(np.clip(similarity, -1.0, 1.0)), 4)
        checks.append({
            "sentence_index": sentences[index][0],
            "cited_labels": labels,
            "score": score,
            "supported": similarity >= threshold,
        })
    return checks
