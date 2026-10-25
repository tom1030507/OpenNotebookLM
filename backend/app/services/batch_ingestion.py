"""Batch URL and YouTube playlist ingestion."""
from typing import Any, Dict, List

from sqlalchemy.orm import Session
import structlog

from app.schemas import (
    FileUploadResponse,
    URLBatchUploadFailure,
    URLBatchUploadResponse,
)
from app.services.rate_limit import (
    ConcurrencyLimitError,
    ConcurrencyLimiter,
    OperationLeaseGroup,
    SlidingWindowRateLimiter,
    UnlimitedConcurrencyLease,
)
from app.services.youtube_playlist import (
    expand_youtube_playlist,
    is_youtube_playlist_url,
    is_youtube_url,
)
from app.utils.network import UnsafeURLError, validate_public_http_url

logger = structlog.get_logger()
MAX_BATCH_INGESTION_SOURCES = 50


async def process_url_batch(
    urls: List[str],
    db: Session,
    project_id: str,
    user_id: str,
    document_service: Any,
    request_limiter: SlidingWindowRateLimiter,
    concurrency_limiter: ConcurrencyLimiter,
    rate_limit_enabled: bool,
    youtube_transcription_enabled: bool,
) -> URLBatchUploadResponse:
    """Validate and enqueue each URL or expanded playlist video independently.

    Args:
        urls: User-supplied web and YouTube URLs.
        db: Database session used by the document service.
        project_id: Project receiving the sources.
        user_id: Authenticated account owning the ingestion quota.
        document_service: Service that creates durable ingestion jobs.
        request_limiter: Per-account sliding-window limiter.
        concurrency_limiter: Per-account active-operation limiter.
        rate_limit_enabled: Whether request and concurrency limits are active.
        youtube_transcription_enabled: Whether YouTube jobs are allowed.

    Returns:
        Successfully queued documents, per-source failures, and cap status.
    """
    failures = []
    candidates: List[Dict[str, Any]] = []
    truncated = False
    for index, submitted_url in enumerate(urls):
        if len(candidates) >= MAX_BATCH_INGESTION_SOURCES:
            truncated = True
            failures.extend(
                URLBatchUploadFailure(
                    url=remaining_url.strip(),
                    message=f"Batch limit of {MAX_BATCH_INGESTION_SOURCES} sources reached",
                )
                for remaining_url in urls[index:]
                if remaining_url.strip()
            )
            break
        url = submitted_url.strip()
        try:
            url = validate_public_http_url(url)
        except UnsafeURLError as error:
            failures.append(URLBatchUploadFailure(url=url, message=str(error)))
            continue

        youtube = is_youtube_url(url)
        if youtube and not youtube_transcription_enabled:
            failures.append(URLBatchUploadFailure(
                url=url,
                message="YouTube transcription is disabled",
            ))
            continue

        if youtube and is_youtube_playlist_url(url):
            try:
                videos, playlist_truncated = expand_youtube_playlist(url)
            except Exception as error:
                logger.warning(
                    "Could not expand YouTube playlist",
                    project_id=project_id,
                    error_type=type(error).__name__,
                )
                failures.append(URLBatchUploadFailure(
                    url=url,
                    message="Could not read YouTube playlist",
                ))
                continue
            truncated = truncated or playlist_truncated
            if not videos:
                failures.append(URLBatchUploadFailure(
                    url=url,
                    message="YouTube playlist contains no importable videos",
                ))
                continue
            source_items = videos
        else:
            source_items = [{"url": url, "title": None}]

        for item in source_items:
            if len(candidates) >= MAX_BATCH_INGESTION_SOURCES:
                truncated = True
                break
            item_url = item["url"]
            if item_url != url:
                try:
                    item_url = validate_public_http_url(item_url)
                except UnsafeURLError as error:
                    failures.append(URLBatchUploadFailure(
                        url=item_url,
                        message=str(error),
                    ))
                    continue
            candidates.append({
                "url": item_url,
                "title": item.get("title"),
                "youtube": is_youtube_url(item_url),
            })

    rate_limited_candidates = []
    for candidate in candidates:
        if rate_limit_enabled and not request_limiter.check(
            "ingest:%s" % user_id,
            10,
            60,
        ).allowed:
            failures.append(URLBatchUploadFailure(
                url=candidate["url"],
                message="Too many requests",
            ))
            continue
        rate_limited_candidates.append(candidate)

    if not rate_limited_candidates:
        return URLBatchUploadResponse(failures=failures, truncated=truncated)

    if rate_limit_enabled:
        try:
            account_lease = concurrency_limiter.acquire("ingest:%s" % user_id)
        except ConcurrencyLimitError as error:
            failures.extend(
                URLBatchUploadFailure(url=candidate["url"], message=str(error))
                for candidate in rate_limited_candidates
            )
            return URLBatchUploadResponse(failures=failures, truncated=truncated)
    else:
        account_lease = UnlimitedConcurrencyLease()
    batch_lease = OperationLeaseGroup(account_lease, len(rate_limited_candidates))

    documents = []
    for candidate in rate_limited_candidates:
        try:
            if candidate["youtube"]:
                document = await document_service.process_youtube(
                    db=db,
                    project_id=project_id,
                    user_id=user_id,
                    youtube_url=candidate["url"],
                    title=candidate["title"],
                    operation_lease=batch_lease,
                )
            else:
                document = await document_service.process_url(
                    db=db,
                    project_id=project_id,
                    user_id=user_id,
                    url=candidate["url"],
                    title=candidate["title"],
                    operation_lease=batch_lease,
                )
        except Exception as error:
            logger.warning(
                "Could not queue URL in batch",
                project_id=project_id,
                url=candidate["url"],
                error_type=type(error).__name__,
            )
            failures.append(URLBatchUploadFailure(
                url=candidate["url"],
                message="Could not queue source",
            ))
        else:
            documents.append(FileUploadResponse(
                doc_id=document.id,
                status=document.status,
                message="Source added successfully. Processing started.",
            ))

    return URLBatchUploadResponse(
        documents=documents,
        failures=failures,
        truncated=truncated,
    )
