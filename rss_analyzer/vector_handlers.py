"""Message handlers for vector search, maintenance, and indexing recovery."""

from __future__ import annotations

import logging
from typing import Callable

from rss_analyzer.cache import (
    get_vector_index_queue_stats,
    process_vector_index_queue,
    retry_vector_index_queue,
)
from rss_analyzer.config import is_vector_store_enabled
from rss_analyzer.vector_service import (
    get_vector_store,
    rebuild_vector_store,
    vector_store_disabled_error,
    vector_store_disabled_result,
)


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict], None]
MessageHandler = Callable[[dict], dict]
StreamHandler = Callable[[dict, ProgressCallback], dict]


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def handle_semantic_search(msg: dict) -> dict:
    query = msg.get("query")
    limit = msg.get("limit", 5)
    min_score = msg.get("min_score")

    if not query:
        return {"error": "no_query", "message": "Query string is required"}

    logger.info(
        "Handling semantic_search: query=%r, limit=%s, min_score=%s",
        query,
        limit,
        min_score,
    )
    if not is_vector_store_enabled():
        return vector_store_disabled_result(query=query, results=[])
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available.",
            }
        results = vector_store.search_similar(query, limit, min_score)
        return {"query": query, "results": results}
    except Exception as exc:
        logger.error("Semantic search error: %s", exc)
        return {"error": "search_failed", "message": str(exc)}


def handle_get_article_tags(msg: dict) -> dict:
    article_id = msg.get("article_id")
    if not article_id:
        return {"error": "no_article_id", "message": "Article ID is required"}

    logger.info("Handling get_article_tags: article_id=%r", article_id)
    if not is_vector_store_enabled():
        return vector_store_disabled_result(article_id=article_id, tags=[])
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available.",
            }
        tags = vector_store.get_article_tags(article_id)
        return {"article_id": article_id, "tags": tags}
    except Exception as exc:
        logger.error("Get article tags error: %s", exc)
        return {"error": "tags_failed", "message": str(exc)}


def handle_discover_trending_topics(msg: dict) -> dict:
    limit = msg.get("limit", 5)
    sample_size = msg.get("sample_size", 100)
    hours = msg.get("hours", 24)

    logger.info(
        "Handling discover_trending_topics: limit=%s, sample_size=%s, hours=%s",
        limit,
        sample_size,
        hours,
    )
    if not is_vector_store_enabled():
        return vector_store_disabled_result(
            topics=[], limit=limit, sample_size=sample_size, hours=hours
        )
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available.",
            }
        trending_topics = vector_store.discover_trending_topics(limit, sample_size, hours)
        return {
            "topics": trending_topics,
            "limit": limit,
            "sample_size": sample_size,
            "hours": hours,
        }
    except Exception as exc:
        logger.error("Discover trending topics error: %s", exc)
        return {"error": "trending_failed", "message": str(exc)}


def handle_delete_article(msg: dict) -> dict:
    article_id = msg.get("article_id")
    if not article_id:
        return {"error": "no_article_id", "message": "Article ID is required"}

    logger.info("Handling delete_article: article_id=%r", article_id)
    if not is_vector_store_enabled():
        return vector_store_disabled_error("delete article embeddings")
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available.",
            }
        success = vector_store.delete_article(article_id)
        return {"article_id": article_id, "success": success}
    except Exception as exc:
        logger.error("Delete article error: %s", exc)
        return {"error": "delete_failed", "message": str(exc)}


def handle_clear_vector_store(_: dict) -> dict:
    logger.info("Handling clear_vector_store")
    if not is_vector_store_enabled():
        return vector_store_disabled_error("clear the vector store")
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available.",
            }
        success = vector_store.clear_collection()
        count = vector_store.get_article_count()
        return {
            "success": success,
            "remaining_count": count,
            "message": f"Cleared vector store. {count} items remain.",
        }
    except Exception as exc:
        logger.error("Clear vector store error: %s", exc)
        return {"error": "clear_failed", "message": str(exc)}


def handle_get_vector_store_stats(_: dict) -> dict:
    logger.info("Handling get_vector_store_stats")
    if not is_vector_store_enabled():
        return vector_store_disabled_result(
            article_count=0, sample_ids=[], has_data=False
        )
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available.",
            }
        count = vector_store.get_article_count()
        all_ids = vector_store.get_all_article_ids()
        return {
            "article_count": count,
            "sample_ids": all_ids[:10],
            "has_data": count > 0,
            "disabled": False,
        }
    except Exception as exc:
        logger.error("Get vector store stats error: %s", exc)
        return {"error": "stats_failed", "message": str(exc)}


def handle_rebuild_vector_store(_: dict) -> dict:
    logger.info("Handling rebuild_vector_store")
    try:
        return rebuild_vector_store()
    except Exception as exc:
        logger.error("Rebuild vector store error: %s", exc)
        return {"error": "rebuild_failed", "message": str(exc)}


def handle_cleanup_invalid_entries(_: dict) -> dict:
    logger.info("Handling cleanup_invalid_entries")
    if not is_vector_store_enabled():
        return vector_store_disabled_error("clean up invalid vector entries")
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {
                "error": "vector_store_unavailable",
                "message": "Vector store is not available.",
            }
        removed_count = vector_store.cleanup_invalid_entries()
        count_after = vector_store.get_article_count()
        return {
            "removed_count": removed_count,
            "remaining_count": count_after,
            "message": (
                f"Cleaned up {removed_count} invalid entries. "
                f"{count_after} items remain."
            ),
        }
    except Exception as exc:
        logger.error("Cleanup invalid entries error: %s", exc)
        return {"error": "cleanup_failed", "message": str(exc)}


def handle_retry_vector_indexing(msg: dict) -> dict:
    wait = _coerce_bool(msg.get("wait"), False)
    retry_result = retry_vector_index_queue(wake_worker=not wait)
    if wait:
        processed = process_vector_index_queue(limit=int(msg.get("limit", 100)))
        return {**retry_result, **processed}
    return retry_result


def handle_get_vector_index_queue(_: dict) -> dict:
    return get_vector_index_queue_stats()


def stream_rebuild_vector_store(
    _: dict,
    progress_callback: ProgressCallback,
) -> dict:
    return rebuild_vector_store(progress_callback=progress_callback)


VECTOR_MESSAGE_HANDLERS: dict[str, MessageHandler] = {
    "get_vector_index_queue": handle_get_vector_index_queue,
    "retry_vector_indexing": handle_retry_vector_indexing,
    "semantic_search": handle_semantic_search,
    "get_article_tags": handle_get_article_tags,
    "discover_trending_topics": handle_discover_trending_topics,
    "delete_article": handle_delete_article,
    "clear_vector_store": handle_clear_vector_store,
    "get_vector_store_stats": handle_get_vector_store_stats,
    "rebuild_vector_store": handle_rebuild_vector_store,
    "cleanup_invalid_entries": handle_cleanup_invalid_entries,
}

VECTOR_STREAM_HANDLERS: dict[str, StreamHandler] = {
    "rebuild_vector_store": stream_rebuild_vector_store,
}
