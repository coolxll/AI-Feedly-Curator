"""
Shared backend message handlers for browser/native/local clients.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("RSS_SCORES_DB", str(PROJECT_ROOT / "rss_scores.db"))
os.environ.setdefault("RSS_VECTOR_DB_DIR", str(PROJECT_ROOT / "chroma_db"))

from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.cache import get_cached_score, save_cached_score
from rss_analyzer.llm_analyzer import (
    analyze_article_with_llm,
    analyze_articles_with_llm_batch,
    summarize_single_article,
)
logger = logging.getLogger(__name__)
_VECTOR_STORE = None


def get_runtime_paths() -> dict[str, str]:
    return {
        "project_root": str(PROJECT_ROOT),
        "db_path": os.environ["RSS_SCORES_DB"],
        "vector_db_dir": os.environ["RSS_VECTOR_DB_DIR"],
    }


def get_vector_store():
    global _VECTOR_STORE
    if _VECTOR_STORE is None:
        from rss_analyzer.vector_store import vector_store as shared_vector_store

        _VECTOR_STORE = shared_vector_store
    return _VECTOR_STORE


def _normalize_item(article_id: str, cached: dict | None) -> dict:
    if not cached:
        return {
            "id": article_id,
            "score": None,
            "data": {},
            "updated_at": None,
            "found": False,
        }
    return {
        "id": article_id,
        "score": cached.get("score"),
        "data": cached.get("data") or {},
        "updated_at": cached.get("updated_at"),
        "found": True,
    }


def _perform_analysis(
    article_id: str, title: str, url: str | None, summary: str, content: str | None
) -> dict | None:
    logger.info("Performing real-time analysis for %s: %s", article_id, title)

    final_content = content or summary
    if url and (not final_content or len(final_content) < 200):
        logger.info("Fetching content from %s", url)
        fetched = fetch_article_content(url)
        if fetched and len(fetched) > 100:
            final_content = fetched
            logger.info("Fetched %s chars", len(fetched))
        else:
            logger.warning("Fetch failed or too short, using summary fallback")

    try:
        analysis = analyze_article_with_llm(title, summary, final_content)
        score = analysis.get("score", 0)

        if url:
            analysis["url"] = url
        if title and not analysis.get("title"):
            analysis["title"] = title

        save_cached_score(article_id, score, analysis)
        logger.info("Analysis complete. Score: %s", score)
        return {"score": score, "data": analysis, "updated_at": None}
    except Exception as exc:
        logger.error("Analysis failed: %s", exc)
        return None


def _handle_get_score(msg: dict) -> dict:
    article_id = msg.get("id")
    cached = get_cached_score(article_id)

    if not cached and msg.get("title"):
        cached = _perform_analysis(
            article_id,
            msg.get("title"),
            msg.get("url"),
            msg.get("summary", ""),
            msg.get("content"),
        )

    return _normalize_item(article_id, cached)


def _handle_get_scores(msg: dict) -> dict:
    input_items = msg.get("items")
    ids = msg.get("ids")

    if input_items:
        items_to_process = input_items
    elif ids:
        items_to_process = [{"id": article_id} for article_id in ids]
    else:
        items_to_process = []

    logger.info("Handling get_scores for %s items", len(items_to_process))

    results: dict[str, dict] = {}
    missing_items: list[dict] = []

    for item in items_to_process:
        if isinstance(item, str):
            item = {"id": item}

        article_id = item.get("id")
        if not article_id:
            continue

        cached = get_cached_score(article_id)
        if not cached and item.get("title"):
            missing_items.append(item)
        else:
            results[article_id] = _normalize_item(article_id, cached)

    if not missing_items:
        return {"items": results}

    logger.info("Cache miss for %s articles. Threshold=10", len(missing_items))

    if len(missing_items) > 10:
        try:
            analyzed_batch = analyze_articles_with_llm_batch(missing_items)
            if analyzed_batch and len(analyzed_batch) == len(missing_items):
                for idx, analyzed in enumerate(analyzed_batch):
                    item = missing_items[idx]
                    article_id = item.get("id")
                    score = analyzed.get("score", 0)

                    if item.get("url") and not analyzed.get("url"):
                        analyzed["url"] = item["url"]
                    if item.get("title") and not analyzed.get("title"):
                        analyzed["title"] = item["title"]

                    save_cached_score(article_id, score, analyzed)
                    results[article_id] = _normalize_item(
                        article_id,
                        {"score": score, "data": analyzed, "updated_at": None},
                    )
            else:
                logger.error("Batch analysis returned mismatching results")
                for item in missing_items:
                    results[item["id"]] = _normalize_item(item["id"], None)
        except Exception as exc:
            logger.error("Batch analysis exception: %s", exc)
            for item in missing_items:
                article_id = item["id"]
                if article_id not in results:
                    results[article_id] = _normalize_item(article_id, None)
    else:
        for item in missing_items:
            article_id = item.get("id")
            analyzed = _perform_analysis(
                article_id,
                item.get("title"),
                item.get("url"),
                item.get("summary", ""),
                item.get("content"),
            )
            results[article_id] = _normalize_item(article_id, analyzed)

    return {"items": results}


def _handle_analyze_article(msg: dict) -> dict:
    article_id = msg.get("id")
    if not article_id:
        return {"error": "no_id"}

    result = _perform_analysis(
        article_id,
        msg.get("title", "Unknown"),
        msg.get("url"),
        msg.get("summary", ""),
        msg.get("content"),
    )
    if result:
        return _normalize_item(article_id, result)
    return {"error": "analysis_failed"}


def _handle_summarize_article(msg: dict) -> dict:
    article_id = msg.get("id")
    title = msg.get("title", "")
    content = msg.get("content", "")
    url = msg.get("url")

    logger.info("Handling summarize_article for %s: %s", article_id, title)

    final_content = content
    if url and (not content or len(content) < 200):
        logger.info("Fetching content for summary from %s", url)
        fetched = fetch_article_content(url)
        if fetched and len(fetched) > 100:
            final_content = fetched
            logger.info("Fetched %s chars for summary", len(fetched))

    if not final_content:
        return {"error": "no_content", "message": "Could not retrieve article content"}

    summary = summarize_single_article(final_content, task="summary")

    if not summary or summary.startswith("Summarization failed:"):
        return {
            "error": "summary_failed",
            "message": summary or "Summarization failed",
        }

    cached = get_cached_score(article_id)
    if cached:
        score = cached.get("score")
        data = cached.get("data") or {}
        data["summary"] = summary
        if url and not data.get("url"):
            data["url"] = url
        if title and not data.get("title"):
            data["title"] = title
        save_cached_score(article_id, score, data)
        logger.info("Updated cache for %s with new summary", article_id)

    return {"id": article_id, "summary": summary}


def _handle_semantic_search(msg: dict) -> dict:
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
    try:
        results = get_vector_store().search_similar(query, limit, min_score)
        return {"query": query, "results": results}
    except Exception as exc:
        logger.error("Semantic search error: %s", exc)
        return {"error": "search_failed", "message": str(exc)}


def _handle_get_article_tags(msg: dict) -> dict:
    article_id = msg.get("article_id")
    if not article_id:
        return {"error": "no_article_id", "message": "Article ID is required"}

    logger.info("Handling get_article_tags: article_id=%r", article_id)
    try:
        tags = get_vector_store().get_article_tags(article_id)
        return {"article_id": article_id, "tags": tags}
    except Exception as exc:
        logger.error("Get article tags error: %s", exc)
        return {"error": "tags_failed", "message": str(exc)}


def _handle_discover_trending_topics(msg: dict) -> dict:
    limit = msg.get("limit", 5)
    sample_size = msg.get("sample_size", 100)
    hours = msg.get("hours", 24)

    logger.info(
        "Handling discover_trending_topics: limit=%s, sample_size=%s, hours=%s",
        limit,
        sample_size,
        hours,
    )
    try:
        trending_topics = get_vector_store().discover_trending_topics(limit, sample_size, hours)
        return {
            "topics": trending_topics,
            "limit": limit,
            "sample_size": sample_size,
            "hours": hours,
        }
    except Exception as exc:
        logger.error("Discover trending topics error: %s", exc)
        return {"error": "trending_failed", "message": str(exc)}


def _handle_delete_article(msg: dict) -> dict:
    article_id = msg.get("article_id")
    if not article_id:
        return {"error": "no_article_id", "message": "Article ID is required"}

    logger.info("Handling delete_article: article_id=%r", article_id)
    try:
        success = get_vector_store().delete_article(article_id)
        return {"article_id": article_id, "success": success}
    except Exception as exc:
        logger.error("Delete article error: %s", exc)
        return {"error": "delete_failed", "message": str(exc)}


def _handle_clear_vector_store(_: dict) -> dict:
    logger.info("Handling clear_vector_store")
    try:
        vector_store = get_vector_store()
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


def _handle_get_vector_store_stats(_: dict) -> dict:
    logger.info("Handling get_vector_store_stats")
    try:
        vector_store = get_vector_store()
        count = vector_store.get_article_count()
        all_ids = vector_store.get_all_article_ids()
        return {
            "article_count": count,
            "sample_ids": all_ids[:10],
            "has_data": count > 0,
        }
    except Exception as exc:
        logger.error("Get vector store stats error: %s", exc)
        return {"error": "stats_failed", "message": str(exc)}


def _handle_cleanup_invalid_entries(_: dict) -> dict:
    logger.info("Handling cleanup_invalid_entries")
    try:
        vector_store = get_vector_store()
        removed_count = vector_store.cleanup_invalid_entries()
        count_after = vector_store.get_article_count()
        return {
            "removed_count": removed_count,
            "remaining_count": count_after,
            "message": f"Cleaned up {removed_count} invalid entries. {count_after} items remain.",
        }
    except Exception as exc:
        logger.error("Cleanup invalid entries error: %s", exc)
        return {"error": "cleanup_failed", "message": str(exc)}


def _handle_health(_: dict) -> dict:
    return {
        "ok": True,
        "transport": "http",
        "service": "rss-backend",
        **get_runtime_paths(),
    }


def handle_message(msg: dict) -> dict:
    msg_type = msg.get("type")
    if msg_type == "get_score":
        return _handle_get_score(msg)
    if msg_type == "get_scores":
        return _handle_get_scores(msg)
    if msg_type == "analyze_article":
        return _handle_analyze_article(msg)
    if msg_type == "summarize_article":
        return _handle_summarize_article(msg)
    if msg_type == "semantic_search":
        return _handle_semantic_search(msg)
    if msg_type == "get_article_tags":
        return _handle_get_article_tags(msg)
    if msg_type == "discover_trending_topics":
        return _handle_discover_trending_topics(msg)
    if msg_type == "delete_article":
        return _handle_delete_article(msg)
    if msg_type == "clear_vector_store":
        return _handle_clear_vector_store(msg)
    if msg_type == "get_vector_store_stats":
        return _handle_get_vector_store_stats(msg)
    if msg_type == "cleanup_invalid_entries":
        return _handle_cleanup_invalid_entries(msg)
    if msg_type == "health":
        return _handle_health(msg)
    return {"error": "unknown_type"}
