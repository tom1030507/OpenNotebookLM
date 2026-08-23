"""Deterministic service substitutes used only by browser E2E tests."""
from __future__ import annotations

import hashlib
import pickle
import re
import uuid
from typing import Any, List, Optional, Union

import numpy as np
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, Embedding

TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)
MODEL_NAME = "e2e-token-hash-v1"


class DeterministicEmbeddingService:
    """Small stable embedding implementation with the production interface."""

    def __init__(self, dimensions: int = 256):
        """Configure vector width.

        Args:
            dimensions: Number of token-hash buckets.

        Returns:
            None.
        """
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self.dimensions = dimensions

    def _vector(self, text: str, normalize: bool) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for token in TOKEN_PATTERN.findall(text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[bucket] += 1.0 if digest[4] & 1 else -1.0
        norm = float(np.linalg.norm(vector))
        if normalize and norm:
            vector /= norm
        return vector

    def generate_embedding(
        self,
        text: Union[str, List[str]],
        normalize: bool = True,
        use_cache: bool = True,
        role: str = "passage",
    ) -> Union[np.ndarray, List[np.ndarray]]:
        """Generate stable embeddings without a model download.

        Args:
            text: One string or a list of strings.
            normalize: Whether to L2-normalize each vector.
            use_cache: Accepted for production interface compatibility.
            role: Accepted for production interface compatibility.

        Returns:
            One float32 vector or a list of float32 vectors.
        """
        del use_cache, role
        if isinstance(text, str):
            return self._vector(text, normalize)
        return [self._vector(item, normalize) for item in text]

    def embed_chunks(
        self,
        db: Session,
        document_id: str,
        force_regenerate: bool = False,
    ) -> List[Embedding]:
        """Persist deterministic embeddings for every document chunk.

        Args:
            db: Database session.
            document_id: Document whose chunks are indexed.
            force_regenerate: Whether to replace existing vectors.

        Returns:
            All embedding rows for the document's chunks.
        """
        document = db.query(Document).filter(Document.id == document_id).first()
        if document is None:
            raise ValueError(f"Document {document_id} not found")
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.start_offset, Chunk.id)
            .all()
        )
        if not chunks:
            return []
        chunk_ids = [chunk.id for chunk in chunks]
        if force_regenerate:
            db.query(Embedding).filter(Embedding.chunk_id.in_(chunk_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        existing = {
            row.chunk_id: row
            for row in db.query(Embedding)
            .filter(Embedding.chunk_id.in_(chunk_ids))
            .all()
        }
        pending = [chunk for chunk in chunks if chunk.id not in existing]
        texts = []
        for chunk in pending:
            context = [part for part in (document.title, chunk.heading_path) if part]
            prefix = " > ".join(context)
            texts.append(f"{prefix}\n\n{chunk.text}" if prefix else chunk.text)
        vectors = self.generate_embedding(texts, role="passage") if texts else []
        for chunk, vector in zip(pending, vectors):
            vector = vector.astype(np.float32)
            db.add(
                Embedding(
                    id=str(uuid.uuid4()),
                    chunk_id=chunk.id,
                    vector=pickle.dumps(vector),
                    vector_json=vector.tolist(),
                    model_name=MODEL_NAME,
                )
            )
        db.commit()
        return (
            db.query(Embedding)
            .filter(Embedding.chunk_id.in_(chunk_ids))
            .all()
        )

    def search_similar_chunks(
        self,
        db: Session,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[dict[str, Any]]:
        """Rank stored chunks by deterministic cosine similarity.

        Args:
            db: Database session.
            query: Search text.
            document_ids: Optional exact document scope; an empty list means none.
            top_k: Maximum number of results.
            threshold: Minimum cosine score.

        Returns:
            Production-shaped chunk payloads sorted best first.
        """
        if document_ids is not None and not document_ids:
            return []
        rows = db.query(Embedding).join(Chunk)
        if document_ids is not None:
            rows = rows.filter(Chunk.document_id.in_(document_ids))
        query_vector = self.generate_embedding(query, role="query")
        ranked = []
        for record in rows.all():
            score = float(np.dot(query_vector, pickle.loads(record.vector)))
            if score < threshold:
                continue
            chunk = record.chunk
            document = (
                db.query(Document).filter(Document.id == chunk.document_id).first()
            )
            ranked.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "document_title": document.title if document else "Unknown",
                    "text": chunk.text,
                    "score": score,
                    "metadata": {
                        "page_num": chunk.page_num,
                        "timestamp": chunk.ts_start,
                        "section": (
                            chunk.meta_json.get("section")
                            if chunk.meta_json
                            else None
                        ),
                        "heading_path": chunk.heading_path,
                    },
                }
            )
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:top_k]


class FixedURLAdapter:
    """Return controlled URL content without public network access."""

    def extract_content(self, url: str) -> dict[str, Any]:
        """Return a fixed article for the requested URL.

        Args:
            url: Source URL retained in the result.

        Returns:
            Extracted-content data matching URLAdapter.
        """
        return {
            "url": url,
            "title": "E2E Observatory Field Notes",
            "text": (
                "# Observatory Operations\n\n"
                "The observatory access code is ORBIT-7319. "
                "Use it only for the deterministic browser test."
            ),
            "html": (
                "<h1>Observatory Operations</h1><p>The observatory access "
                "code is ORBIT-7319.</p>"
            ),
            "metadata": {"description": "Controlled E2E source", "url": url},
            "headings": [
                {"level": 1, "text": "Observatory Operations", "tag": "h1"}
            ],
            "links": [],
        }


class FixedYouTubeAdapter:
    """Return a controlled transcript without contacting YouTube."""

    def extract_transcript(self, url: str) -> dict[str, Any]:
        """Return a fixed timed transcript.

        Args:
            url: YouTube URL retained in metadata.

        Returns:
            Transcript data matching YouTubeAdapter.
        """
        video_id = "e2eOrbit7319"
        segments = [
            {
                "text": "Welcome to the observatory.",
                "start": 0.0,
                "end": 12.0,
                "duration": 12.0,
            },
            {
                "text": "The access code is ORBIT-7319.",
                "start": 12.0,
                "end": 42.0,
                "duration": 30.0,
            },
        ]
        return {
            "video_id": video_id,
            "url": url,
            "text": "Welcome to the observatory. The access code is ORBIT-7319.",
            "segments": segments,
            "duration": 42.0,
            "metadata": {
                "video_id": video_id,
                "url": url,
                "language": "en",
                "is_generated": False,
                "duration": 42.0,
            },
            "language": "en",
        }
