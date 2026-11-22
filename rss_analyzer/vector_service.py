"""Vector-store lifecycle and rebuild workflows."""

from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
from typing import Callable

from rss_analyzer.cache import build_vector_store_payload, iter_cached_scores
from rss_analyzer.config import is_vector_store_enabled


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict], None]
_VECTOR_STORE = None
_REBUILD_LOCK = threading.Lock()


def _has_embedding_fingerprint_mismatch(vector_store) -> bool:
    checker = getattr(vector_store, "is_embedding_fingerprint_mismatch", None)
    if callable(checker):
        result = checker()
        if isinstance(result, bool):
            return result
    return False


def _emit_progress(
    callback: ProgressCallback | None,
    event: str,
    **payload,
) -> None:
    if callback:
        callback({"event": event, **payload})


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def get_vector_store():
    if not is_vector_store_enabled():
        return None

    global _VECTOR_STORE
    if _VECTOR_STORE is None:
        from rss_analyzer.vector_store import vector_store as shared_vector_store

        _VECTOR_STORE = shared_vector_store
    return _VECTOR_STORE


def vector_store_disabled_error(operation: str) -> dict:
    return {
        "error": "vector_store_disabled",
        "message": f"Vector store is disabled; cannot {operation}.",
    }


def vector_store_disabled_result(**payload) -> dict:
    return {
        **payload,
        "disabled": True,
        "message": "Vector store is disabled.",
    }


def rebuild_vector_store(
    progress_callback: ProgressCallback | None = None,
    *,
    allow_empty: bool = False,
) -> dict:
    if not _REBUILD_LOCK.acquire(blocking=False):
        return {
            "error": "rebuild_in_progress",
            "success": False,
            "message": "A vector store rebuild is already in progress.",
        }

    try:
        _emit_progress(progress_callback, "phase", phase="preparing")
        if not is_vector_store_enabled():
            return vector_store_disabled_error("rebuild the vector store")

        vector_store = get_vector_store()
        if not vector_store or not vector_store.collection:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available in the current runtime.",
            }

        cached_items = iter_cached_scores()
        if not cached_items and not allow_empty:
            return {
                "error": "empty_cache",
                "success": False,
                "cached_count": 0,
                "rebuilt_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "cleared": False,
                "message": (
                    "Refusing to clear and rebuild vector store because 0 cached articles "
                    "were found in SQLite. Pass allow_empty=True to explicitly clear an empty cache."
                ),
            }
        resume_enabled = os.getenv("RSS_VECTOR_REBUILD_RESUME", "").lower() in (
            "1",
            "true",
            "yes",
        )
        existing_ids: set[str] = set()

        if resume_enabled:
            if _has_embedding_fingerprint_mismatch(vector_store):
                return {
                    "error": "embedding_fingerprint_mismatch",
                    "success": False,
                    "message": (
                        "Refusing to resume vector store rebuild because the stored "
                        "embedding fingerprint does not match the current embedding "
                        "configuration. Unset RSS_VECTOR_REBUILD_RESUME to perform a full rebuild."
                    ),
                }
            existing_ids = set(vector_store.get_all_article_ids())
            logger.info("Resume mode enabled; found %s existing vectors", len(existing_ids))
        else:
            cleared = vector_store.clear_collection()
            if not cleared:
                return {
                    "error": "clear_failed",
                    "message": "Failed to clear vector store before rebuild.",
                }

        vector_store.refresh_embedding_fingerprint()

        batch_size = max(1, int(os.getenv("RSS_VECTOR_REBUILD_BATCH_SIZE", "8")))
        default_concurrency = (
            "100" if getattr(vector_store, "backend", "embedded") == "http" else "1"
        )
        concurrency = max(
            1, int(os.getenv("RSS_VECTOR_REBUILD_CONCURRENCY", default_concurrency))
        )

        rebuild_payloads: list[dict] = []
        skipped_count = 0
        failed_ids: list[str] = []

        for item in cached_items:
            payload = build_vector_store_payload(
                item["article_id"],
                item["score"],
                item["data"],
                item.get("updated_at"),
            )
            if not payload:
                skipped_count += 1
                continue
            if resume_enabled and payload["article_id"] in existing_ids:
                skipped_count += 1
                continue
            rebuild_payloads.append(payload)

        rebuilt_count = 0
        batches = _chunked(rebuild_payloads, batch_size)
        logger.info(
            "Rebuilding vector store with batch_size=%s concurrency=%s payloads=%s",
            batch_size,
            concurrency,
            len(rebuild_payloads),
        )

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
        try:
            futures = [executor.submit(vector_store.add_articles, batch) for batch in batches]
            for completed_batches, future in enumerate(
                concurrent.futures.as_completed(futures),
                1,
            ):
                result = future.result()
                rebuilt_count += result.get("success_count", 0)
                failed_ids.extend(result.get("failed_ids", []))
                _emit_progress(
                    progress_callback,
                    "progress",
                    phase="indexing",
                    current=completed_batches,
                    total=len(batches),
                    rebuilt_count=rebuilt_count,
                    failed_count=len(failed_ids),
                )
        except Exception:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

        remaining_count = vector_store.get_article_count()
        result = {
            "success": len(failed_ids) == 0,
            "cached_count": len(cached_items),
            "rebuilt_count": rebuilt_count,
            "skipped_count": skipped_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids[:10],
            "remaining_count": remaining_count,
            "batch_size": batch_size,
            "concurrency": concurrency,
            "message": (
                f"Rebuilt vector store from {len(cached_items)} cached articles. "
                f"Rebuilt={rebuilt_count}, skipped={skipped_count}, "
                f"failed={len(failed_ids)}. batch_size={batch_size}, "
                f"concurrency={concurrency}, resume={resume_enabled}."
            ),
        }
        _emit_progress(
            progress_callback,
            "progress",
            phase="completed",
            current=len(batches),
            total=len(batches),
        )
        return result
    finally:
        _REBUILD_LOCK.release()
