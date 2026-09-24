"""Article-level scoring, analysis, and summary message handlers."""

from __future__ import annotations

import logging
from typing import Callable

from rss_analyzer.analysis_service import ArticleAnalysisService
from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.cache import get_cached_score, save_cached_score
from rss_analyzer.llm_analyzer import (
    analyze_article_with_llm,
    analyze_articles_with_llm_batch,
    summarize_single_article,
)


logger = logging.getLogger(__name__)
MessageHandler = Callable[[dict], dict]


def get_analysis_service() -> ArticleAnalysisService:
    """Build the stateless service with patchable infrastructure dependencies."""
    return ArticleAnalysisService(
        fetch_content=fetch_article_content,
        analyze_one=analyze_article_with_llm,
        analyze_batch=analyze_articles_with_llm_batch,
        cache_get=get_cached_score,
        cache_save=save_cached_score,
    )


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


def _normalize_analysis_error(article_id: str, analysis: dict) -> dict:
    return {
        "id": article_id,
        "score": None,
        "data": analysis,
        "updated_at": None,
        "found": False,
        "status": "error",
        "error": analysis.get(
            "error",
            {
                "code": "analysis_failed",
                "message": analysis.get("reason", "Analysis failed"),
            },
        ),
    }


def _perform_analysis(
    article_id: str,
    title: str,
    url: str | None,
    summary: str,
    content: str | None,
) -> dict | None:
    logger.info("Performing real-time analysis for %s: %s", article_id, title)
    try:
        analysis = get_analysis_service().analyze(
            {
                "id": article_id,
                "title": title,
                "url": url or "",
                "summary": summary,
                "content": content or "",
            }
        )
        if analysis.get("status", "success") != "success":
            logger.warning("Analysis failed for %s: %s", article_id, analysis.get("reason"))
            return analysis
        score = analysis.get("score")
        logger.info("Analysis complete. Score: %s", score)
        return {"score": score, "data": analysis, "updated_at": None}
    except Exception as exc:
        logger.error("Analysis failed: %s", exc)
        return None


def handle_get_score(msg: dict) -> dict:
    article_id = msg.get("id")
    if msg.get("title"):
        result = _perform_analysis(
            article_id,
            msg.get("title"),
            msg.get("url"),
            msg.get("summary", ""),
            msg.get("content"),
        )
    else:
        result = get_cached_score(article_id)

    if result and result.get("status") == "error":
        return _normalize_analysis_error(article_id, result)
    return _normalize_item(article_id, result)


def handle_get_scores(msg: dict) -> dict:
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
        if item.get("title"):
            missing_items.append(item)
        else:
            results[article_id] = _normalize_item(
                article_id, get_cached_score(article_id)
            )

    if not missing_items:
        return {"items": results}

    logger.info("Cache miss for %s articles. Threshold=10", len(missing_items))
    if len(missing_items) > 10:
        try:
            service = get_analysis_service()
            prepared_items = [service.prepare(item) for item in missing_items]
            analyzed_batch = service.analyze_many_prepared(prepared_items)
            if analyzed_batch and len(analyzed_batch) == len(missing_items):
                for item, analyzed in zip(missing_items, analyzed_batch):
                    article_id = item.get("id")
                    if analyzed.get("status", "success") != "success":
                        results[article_id] = _normalize_analysis_error(
                            article_id, analyzed
                        )
                        continue
                    results[article_id] = _normalize_item(
                        article_id,
                        {
                            "score": analyzed.get("score"),
                            "data": analyzed,
                            "updated_at": None,
                        },
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
            if analyzed and analyzed.get("status") == "error":
                results[article_id] = _normalize_analysis_error(article_id, analyzed)
            else:
                results[article_id] = _normalize_item(article_id, analyzed)

    return {"items": results}


def handle_analyze_article(msg: dict) -> dict:
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
        if result.get("status") == "error":
            return result
        return _normalize_item(article_id, result)
    return {"error": "analysis_failed"}


def handle_summarize_article(msg: dict) -> dict:
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


ANALYSIS_MESSAGE_HANDLERS: dict[str, MessageHandler] = {
    "get_score": handle_get_score,
    "get_scores": handle_get_scores,
    "analyze_article": handle_analyze_article,
    "summarize_article": handle_summarize_article,
}
