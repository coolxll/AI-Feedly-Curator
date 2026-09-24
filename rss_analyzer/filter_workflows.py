"""Feedly unread-article filtering and mark-as-read workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from rss_analyzer.analysis_service import ArticleAnalysisService, PreparedArticle
from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.cache import get_cached_score, save_cached_score
from rss_analyzer.config import PROJ_CONFIG
from rss_analyzer.feedly_client import feedly_fetch_unread, feedly_mark_read
from rss_analyzer.llm_analyzer import (
    analyze_article_with_llm,
    analyze_articles_with_llm_batch,
)
from rss_analyzer.utils import is_newsflash


logger = logging.getLogger(__name__)
FEED_ID_36KR = "feed/http://www.36kr.com/feed"


@dataclass
class FilterResult:
    matched: list
    remaining: list
    label: str
    marked_ids: set[str] = field(default_factory=set)


def _get_analysis_service() -> ArticleAnalysisService:
    return ArticleAnalysisService(
        fetch_content=fetch_article_content,
        analyze_one=analyze_article_with_llm,
        analyze_batch=analyze_articles_with_llm_batch,
        cache_get=get_cached_score,
        cache_save=save_cached_score,
    )


def fetch_filter_articles(limit: int, stream_id: str | None = None) -> list:
    source_label = "36kr feed" if stream_id == FEED_ID_36KR else "all unread"
    logger.info("Fetching unread articles from %s (limit=%s)", source_label, limit)
    articles = feedly_fetch_unread(stream_id=stream_id, limit=limit) or []
    logger.info("Fetched %s unread articles", len(articles))
    return articles


def mark_filter_results_as_read(
    articles: list, label: str, dry_run: bool, mark_read: bool
) -> bool:
    if not articles:
        return True

    if not mark_read:
        logger.info(
            "Skipping mark-as-read for %s %s articles because mark_read is disabled",
            len(articles),
            label,
        )
        return True

    ids = [article["id"] for article in articles if article.get("id")]
    if dry_run:
        logger.info("[DRY RUN] Would mark %s %s articles as read", len(ids), label)
        for article in articles[:5]:
            score = article.get("_score")
            prefix = f"[{score:.1f}] " if score is not None else ""
            logger.info("  - %s%s", prefix, article.get("title", "")[:50])
        if len(articles) > 5:
            logger.info("  ... and %s more", len(articles) - 5)
        return True

    for idx in range(0, len(ids), 500):
        if not feedly_mark_read(ids[idx : idx + 500]):
            logger.error("Failed to mark %s articles as read", label)
            return False

    logger.info("Marked %s %s articles as read", len(ids), label)
    return True


def mark_article_ids_as_read(
    article_ids: list[str], label: str, dry_run: bool = False, mark_read: bool = True
) -> bool:
    if not article_ids:
        return True

    articles = [{"id": article_id} for article_id in article_ids if article_id]
    return mark_filter_results_as_read(articles, label, dry_run, mark_read)


def run_filter_pipeline(
    articles: list, filters: list, dry_run: bool, mark_read: bool
) -> dict:
    remaining = articles
    total_matched = 0
    steps: list[dict] = []

    for filter_func in filters:
        if not remaining:
            break

        result = filter_func(remaining)
        already_marked = getattr(result, "marked_ids", set())
        unmarked = [a for a in result.matched if a.get("id") not in already_marked]
        if unmarked:
            mark_filter_results_as_read(unmarked, result.label, dry_run, mark_read)
        elif result.matched and dry_run:
            mark_filter_results_as_read(result.matched, result.label, dry_run, mark_read)
        elif result.matched and mark_read:
            logger.info(
                "All %s %s articles were marked as read progressively",
                len(result.matched),
                result.label,
            )

        total_matched += len(result.matched)
        steps.append(
            {
                "label": result.label,
                "matched_count": len(result.matched),
                "remaining_count": len(result.remaining),
            }
        )
        remaining = result.remaining

    logger.info("Filtered %s/%s articles", total_matched, len(articles))
    return {
        "success": True,
        "article_count": len(articles),
        "filtered_count": total_matched,
        "remaining_count": len(remaining),
        "steps": steps,
    }

def newsflash_filter(articles: list) -> FilterResult:
    matched = [article for article in articles if is_newsflash(article)]
    remaining = [article for article in articles if not is_newsflash(article)]
    logger.info("Newsflash filter matched %s/%s", len(matched), len(articles))
    return FilterResult(matched, remaining, "newsflash")


def _prepare_article_scoring(article: dict) -> dict:
    prepared = _get_analysis_service().prepare(article)
    return {
        "article_id": prepared.article_id,
        "title": prepared.title,
        "url": prepared.url,
        "summary": prepared.summary,
        "content": prepared.content,
    }


def _score_article(article: dict) -> tuple[float | None, dict]:
    try:
        result = _get_analysis_service().analyze(article)
        if result.get("status", "success") != "success":
            return None, result
        return result.get("score"), result
    except Exception as exc:
        logger.debug("Scoring failed: %s", exc)
        return None, {
            "status": "error",
            "score": None,
            "error": {"code": "analysis_failed", "message": str(exc)},
        }


def _handle_scored_filter_article(
    article: dict,
    score: float | None,
    prefix: str,
    threshold: float,
    dry_run: bool,
    matched: list,
    remaining: list,
    mark_read: bool,
    unmarked_buffer: list[str] | None = None,
    on_matched: Callable[[], None] | None = None,
) -> None:
    title_str = article.get("title", "Unknown Title")
    if score is None:
        logger.info("%s Result: skipped (scoring failed)", prefix)
        remaining.append(article)
    elif score <= threshold:
        logger.info("%s Result: %s", prefix, title_str)
        if mark_read:
            action = "[DRY RUN] would mark as read" if dry_run else "will be marked as read"
            logger.info("%s Score %.1f <= %.1f, %s", prefix, score, threshold, action)
        else:
            logger.info("%s Score %.1f <= %.1f, mark_read disabled", prefix, score, threshold)
        matched.append({**article, "_score": score})
        if unmarked_buffer is not None and article.get("id"):
            unmarked_buffer.append(article["id"])
            if on_matched:
                on_matched()
    else:
        logger.info("%s Result: kept %s (%.1f)", prefix, title_str, score)
        remaining.append(article)


def low_score_filter(
    articles: list,
    threshold: float = 3.0,
    dry_run: bool = False,
    mark_read: bool = True,
    incremental_mark: bool = False,
    mark_batch_size: int = 20,
) -> FilterResult:
    matched = []
    remaining = []
    marked_ids: set[str] = set()
    unmarked_buffer: list[str] = []
    effective_batch_size = max(1, mark_batch_size)
    batch_scoring = PROJ_CONFIG.get("batch_scoring", False)
    batch_size = max(1, int(PROJ_CONFIG.get("batch_size", 1)))
    batch_queue = []

    def flush_incremental_mark() -> None:
        nonlocal unmarked_buffer
        if not unmarked_buffer or not mark_read or dry_run or not incremental_mark:
            return
        batch_to_mark = [aid for aid in unmarked_buffer if aid]
        if not batch_to_mark:
            unmarked_buffer = []
            return
        logger.info(
            "Progressively marking %s low-score articles as read on Feedly (%s already marked)...",
            len(batch_to_mark),
            len(marked_ids),
        )
        try:
            if feedly_mark_read(batch_to_mark):
                marked_ids.update(batch_to_mark)
                logger.info(
                    "Progressively marked %s low-score articles as read on Feedly (total marked: %s)",
                    len(batch_to_mark),
                    len(marked_ids),
                )
            else:
                logger.error(
                    "Feedly mark-as-read returned failure for %s articles; will retry at end of pipeline",
                    len(batch_to_mark),
                )
        except Exception as exc:
            logger.error("Exception during progressive mark-as-read: %s", exc)
        unmarked_buffer = []

    def check_and_flush_incremental() -> None:
        if len(unmarked_buffer) >= effective_batch_size:
            flush_incremental_mark()

    def flush_batch() -> None:
        nonlocal batch_queue
        if not batch_queue:
            return

        batch_payload = [
            PreparedArticle(**item["payload"])
            for item in batch_queue
        ]
        batch_results = _get_analysis_service().analyze_many_prepared(batch_payload)
        for item, analysis in zip(batch_queue, batch_results):
            score = analysis.get("score") if analysis.get("status", "success") == "success" else None
            _handle_scored_filter_article(
                item["article"],
                score,
                item["prefix"],
                threshold,
                dry_run,
                matched,
                remaining,
                mark_read,
                unmarked_buffer=unmarked_buffer if (incremental_mark and mark_read and not dry_run) else None,
                on_matched=check_and_flush_incremental,
            )
        batch_queue = []

    for idx, article in enumerate(articles, 1):
        title = article.get("title", "")[:50]
        prefix = f"[{idx}/{len(articles)}]"
        logger.info("%s Scoring %s...", prefix, title)
        if batch_scoring:
            batch_queue.append(
                {
                    "article": article,
                    "prefix": prefix,
                    "payload": _prepare_article_scoring(article),
                }
            )
            if len(batch_queue) >= batch_size:
                flush_batch()
        else:
            score, _analysis = _score_article(article)

            _handle_scored_filter_article(
                article,
                score,
                prefix,
                threshold,
                dry_run,
                matched,
                remaining,
                mark_read,
                unmarked_buffer=unmarked_buffer if (incremental_mark and mark_read and not dry_run) else None,
                on_matched=check_and_flush_incremental,
            )

    if batch_scoring and batch_queue:
        flush_batch()

    if incremental_mark and mark_read and not dry_run:
        flush_incremental_mark()

    logger.info(
        "Low-score filter matched %s articles (progressively marked: %s) and kept %s",
        len(matched),
        len(marked_ids),
        len(remaining),
    )
    return FilterResult(matched, remaining, "low-score", marked_ids=marked_ids)


def run_filter_workflow(
    *,
    mode: str,
    limit: int,
    threshold: float = 3.0,
    dry_run: bool = False,
    mark_read: bool = False,
    stream_id: str | None = None,
    incremental_mark: bool = True,
    mark_batch_size: int | None = None,
) -> dict:
    target_stream = stream_id
    batch_mark_size = (
        mark_batch_size
        if mark_batch_size is not None
        else int(PROJ_CONFIG.get("filter_mark_batch_size", 20))
    )

    if mode == "newsflash":
        if not target_stream:
            target_stream = FEED_ID_36KR
        articles = fetch_filter_articles(limit, stream_id=target_stream)
        filters = [newsflash_filter]
    elif mode == "low-score":
        articles = fetch_filter_articles(limit, stream_id=target_stream)
        filters = [
            lambda items: low_score_filter(
                items,
                threshold=threshold,
                dry_run=dry_run,
                mark_read=mark_read,
                incremental_mark=incremental_mark,
                mark_batch_size=batch_mark_size,
            )
        ]
    else:
        articles = fetch_filter_articles(limit, stream_id=target_stream)
        filters = [
            newsflash_filter,
            lambda items: low_score_filter(
                items,
                threshold=threshold,
                dry_run=dry_run,
                mark_read=mark_read,
                incremental_mark=incremental_mark,
                mark_batch_size=batch_mark_size,
            ),
        ]

    if not articles:
        return {
            "success": True,
            "mode": mode,
            "stream_id": target_stream,
            "article_count": 0,
            "filtered_count": 0,
            "remaining_count": 0,
            "steps": [],
            "message": "No unread articles found.",
        }

    result = run_filter_pipeline(articles, filters, dry_run, mark_read)
    return {
        **result,
        "mode": mode,
        "stream_id": target_stream,
        "threshold": threshold,
        "dry_run": dry_run,
        "mark_read": mark_read,
        "incremental_mark": incremental_mark,
    }
