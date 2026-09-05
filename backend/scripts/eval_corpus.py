"""Fetch and cache the evaluation corpus.

The eval corpus is a handful of live web pages. They are fetched once into a
gitignored cache so every later run is offline and byte-identical: without that,
a re-run could not tell a retrieval change from an upstream edit.

The cache is replayed through the real `URLAdapter`, so extraction itself stays
under test. Only the network call is stubbed.
"""
import contextlib
import json
from pathlib import Path
from typing import Dict, Iterable, List
from unittest import mock

import requests

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
CACHE_DIR = EVAL_DIR / ".cache"
DATASET_PATH = EVAL_DIR / "dataset.json"

# Matches the adapter's own header so cached bytes are what the app would see.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def load_dataset(path: Path = DATASET_PATH) -> Dict:
    """Read the corpus + question set.

    Args:
        path: Dataset location.

    Returns:
        The parsed dataset.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def cache_path(doc_id: str) -> Path:
    """Where a corpus entry's bytes live.

    Args:
        doc_id: Corpus entry id.

    Returns:
        Path to the cached HTML.
    """
    return CACHE_DIR / f"{doc_id}.html"


def fetch_into_cache(entries: Iterable[Dict], refresh: bool = False) -> List[str]:
    """Populate the cache, fetching only what is missing.

    Args:
        entries: Corpus entries with `id` and `url`.
        refresh: Re-fetch even when a cached copy exists.

    Returns:
        Ids that were fetched over the network this call.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fetched = []
    for entry in entries:
        target = cache_path(entry["id"])
        if target.exists() and not refresh:
            continue
        response = requests.get(entry["url"], headers={"User-Agent": USER_AGENT}, timeout=30)
        response.raise_for_status()
        target.write_bytes(response.content)
        fetched.append(entry["id"])
    return fetched


@contextlib.contextmanager
def serve_from_cache(entries: Iterable[Dict]):
    """Replay cached corpus bytes through the real URL extraction pipeline.

    Replaces the adapter's download boundary, including DNS resolution, so
    replay remains offline even as its HTTP transport changes. HTML parsing,
    metadata extraction, and content cleanup still use the real adapter. The
    patch is process-wide and intended only for this one-off eval script.

    Args:
        entries: Corpus entries with `id` and `url`.

    Yields:
        None.
    """
    from app.adapters.url import URLAdapter

    by_url = {entry["url"]: entry["id"] for entry in entries}

    def cached_download(_adapter, url, _control):
        doc_id = by_url.get(url)
        if doc_id is None:
            raise requests.RequestException(f"{url} is not part of the eval corpus")
        return url, cache_path(doc_id).read_bytes()

    with mock.patch.object(URLAdapter, "_download", cached_download):
        yield
