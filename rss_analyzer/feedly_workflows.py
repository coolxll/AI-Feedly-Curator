"""Feedly fetch-and-analyze workflow with compatibility exports."""

from __future__ import annotations

import concurrent.futures
import logging
import os
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("RSS_SCORES_DB", str(PROJECT_ROOT / "rss_scores.db"))
os.environ.setdefault("RSS_VECTOR_DB_DIR", str(PROJECT_ROOT / "chroma_db"))

from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.analysis_service import ArticleAnalysisService, PreparedArticle
from rss_analyzer.cache import (
    get_cached_score,
    save_cached_score,
)
from rss_analyzer.config import (
    LATEST_ANALYZED_FILE,
    LATEST_UNREAD_FILE,
    PROJ_CONFIG,
    get_vector_store_config,
    is_vector_store_enabled,
)
from rss_analyzer.feedly_client import feedly_fetch_unread, feedly_mark_read
from rss_analyzer.filter_workflows import (
    FEED_ID_36KR,
    FilterResult,
    fetch_filter_articles,
    low_score_filter,
    mark_article_ids_as_read,
    mark_filter_results_as_read,
    newsflash_filter,
    run_filter_pipeline,
    run_filter_workflow,
)
from rss_analyzer.llm_analyzer import (
    analyze_article_with_llm,
    analyze_articles_with_llm_batch,
)
from rss_analyzer.report_service import (
    build_monthly_output_path as _build_monthly_output_path,
    generate_summary_report,
)
from rss_analyzer.readflow_workflows import (
    BATCH_READ_FETCH_LIMIT,
    BATCH_TRIAGE_CACHE_VERSION,
    _build_batch_triage_prompt,
    _deep_analysis_log_step,
    _deep_analyze_digest_candidates,
    _parse_batch_triage_results,
    mark_articles_read,
    mark_stream_low_priority_read,
    process_batch,
    process_stream,
)
from rss_analyzer.utils import is_newsflash, load_articles, save_articles
logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict], None]


def _emit_progress(
    callback: ProgressCallback | None,
    event: str,
    **payload,
) -> None:
    if callback:
        callback({"event": event, **payload})


def get_analysis_service() -> ArticleAnalysisService:
    """Compatibility factory for backend workflows and dependency injection."""
    return ArticleAnalysisService(
        fetch_content=fetch_article_content,
        analyze_one=analyze_article_with_llm,
        analyze_batch=analyze_articles_with_llm_batch,
        cache_get=get_cached_score,
        cache_save=save_cached_score,
    )


def get_runtime_paths() -> dict[str, str | bool]:
    vector_config = get_vector_store_config()
    return {
        "project_root": str(PROJECT_ROOT),
        "db_path": os.environ["RSS_SCORES_DB"],
        "vector_enabled": is_vector_store_enabled(),
        "vector_backend": vector_config.backend,
        "vector_db_dir": vector_config.persist_dir,
        "vector_state_dir": vector_config.state_dir,
        "vector_http_url": vector_config.http_url,
    }


def analyze_articles(
    *,
    input_file: str = LATEST_UNREAD_FILE,
    limit: int | None = None,
    mark_read: bool = False,
    refresh: bool = True,
    stream_id: str | None = None,
    threads: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    effective_limit = limit or int(PROJ_CONFIG["limit"])
    _emit_progress(progress_callback, "phase", phase="fetching")

    if refresh:
        logger.info("=" * 60)
        logger.info("Refreshing articles from Feedly")
        if stream_id:
            logger.info("Target Stream: %s", stream_id)
        logger.info("=" * 60)
        logger.info("Fetching latest %s unread articles...", effective_limit)
        articles = feedly_fetch_unread(limit=effective_limit, stream_id=stream_id)
        if articles is None:
            return {
                "error": "fetch_failed",
                "message": "Failed to fetch unread articles from Feedly.",
            }

        save_articles(articles, LATEST_UNREAD_FILE)
        logger.info("Saved %s unread articles to %s", len(articles), LATEST_UNREAD_FILE)

        if input_file == PROJ_CONFIG["input_file"]:
            input_file = LATEST_UNREAD_FILE
    else:
        logger.info("=" * 60)
        logger.info("Using local article data without refresh")
        logger.info("=" * 60)

    if not os.path.exists(input_file):
        return {
            "error": "input_not_found",
            "message": f"Could not find input file: {input_file}",
        }

    articles = load_articles(input_file)
    logger.info("Loaded %s articles from %s", len(articles), input_file)
    total_articles = min(effective_limit, len(articles))
    _emit_progress(
        progress_callback,
        "progress",
        phase="analyzing",
        current=0,
        total=total_articles,
    )

    analyzed_articles: list[dict] = []
    successful_article_ids: list[str] = []
    successful_count = 0
    completed_count = 0
    seen_titles: set[str] = set()
    batch_scoring = PROJ_CONFIG.get("batch_scoring", False)
    batch_size = max(1, int(PROJ_CONFIG.get("batch_size", 1)))
    batch_queue: list[dict] = []

    max_workers = threads or int(PROJ_CONFIG.get("max_workers", 3))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    pending_futures: list[tuple[concurrent.futures.Future, list[dict]]] = []

    def record_analysis_result(article_item: dict, analysis_result: dict) -> None:
        nonlocal completed_count, successful_count
        completed_count += 1
        if analysis_result.get("status", "success") != "success":
            title_str = article_item.get("title", "Unknown Title")
            logger.warning(
                "  Analysis failed for %s: %s",
                title_str,
                analysis_result.get("reason", "unknown error"),
            )
            analyzed_articles.append({**article_item, "analysis": analysis_result})
            _emit_progress(
                progress_callback,
                "article_failed",
                id=article_item.get("id"),
                title=title_str,
                current=completed_count,
                total=total_articles,
                error=analysis_result.get("error") or analysis_result.get("reason"),
            )
            return

        verdict = analysis_result.get("verdict", "Unknown")
        score = analysis_result["score"]
        if (
            "red_flags" in analysis_result.get("detailed_scores", {})
            and analysis_result["detailed_scores"]["red_flags"]
        ):
            red_flags = analysis_result["detailed_scores"]["red_flags"]
            logger.info("  Red Flags: %s", red_flags)
            verdict = f"Blocked: {verdict}"

        title_str = article_item.get("title", "Unknown Title")
        logger.info("  Title: %s", title_str)
        logger.info("  Score: %.1f/5.0 - %s", score, verdict)
        logger.info("  Reason: %s", analysis_result.get("reason", ""))
        if "detailed_scores" in analysis_result:
            scores = analysis_result["detailed_scores"]
            logger.info(
                "  Detail: relevance=%s informativeness=%s depth=%s readability=%s originality=%s",
                scores["relevance"],
                scores["informativeness"],
                scores["depth"],
                scores["readability"],
                scores["originality"],
            )

        analyzed_articles.append({**article_item, "analysis": analysis_result})
        successful_count += 1
        if article_item.get("id"):
            successful_article_ids.append(article_item["id"])
        _emit_progress(
            progress_callback,
            "article_completed",
            id=article_item.get("id"),
            title=title_str,
            score=score,
            current=completed_count,
            total=total_articles,
        )

    def process_completed_futures() -> None:
        nonlocal pending_futures
        still_pending = []
        for future, batch_items in pending_futures:
            if future.done():
                try:
                    batch_results = future.result()
                    for item, analysis in zip(batch_items, batch_results):
                        record_analysis_result(item["article"], analysis)
                except Exception as exc:
                    logger.error("Batch processing failed: %s", exc)
                    for item in batch_items:
                        record_analysis_result(
                            item["article"],
                            {
                                "status": "error",
                                "score": None,
                                "reason": str(exc),
                                "error": {
                                    "code": "batch_analysis_failed",
                                    "message": str(exc),
                                },
                            },
                        )
            else:
                still_pending.append((future, batch_items))
        pending_futures = still_pending

    try:
        for idx, article in enumerate(articles[:effective_limit], 1):
            logger.info(
                "Processing article %s/%s: %s",
                idx,
                min(effective_limit, len(articles)),
                article["title"],
            )
            _emit_progress(
                progress_callback,
                "article_started",
                id=article.get("id"),
                title=article.get("title", "Unknown Title"),
                current=idx,
                total=total_articles,
            )

            filter_keywords = PROJ_CONFIG.get("filter_keywords", [])
            if any(kw in article["title"] for kw in filter_keywords):
                logger.info("  Skipped: title matched filter keyword")
                _emit_progress(
                    progress_callback,
                    "article_skipped",
                    id=article.get("id"),
                    title=article.get("title"),
                    reason="filter_keyword",
                    current=idx,
                    total=total_articles,
                )
                continue

            filter_url_patterns = PROJ_CONFIG.get("filter_url_patterns", [])
            article_url = article.get("link", "") or article.get("originId", "")
            if any(pattern in article_url for pattern in filter_url_patterns):
                logger.info("  Skipped: URL matched filter pattern (%s)", article_url)
                _emit_progress(
                    progress_callback,
                    "article_skipped",
                    id=article.get("id"),
                    title=article.get("title"),
                    reason="filter_url",
                    current=idx,
                    total=total_articles,
                )
                continue

            norm_title = "".join(filter(str.isalnum, article["title"].lower()))
            if len(norm_title) > 5:
                if norm_title in seen_titles:
                    logger.info("  Skipped: duplicate title")
                    _emit_progress(
                        progress_callback,
                        "article_skipped",
                        id=article.get("id"),
                        title=article.get("title"),
                        reason="duplicate_title",
                        current=idx,
                        total=total_articles,
                    )
                    continue
                seen_titles.add(norm_title)

            if is_newsflash(article):
                logger.info("  Skipped: detected as newsflash")
                _emit_progress(
                    progress_callback,
                    "article_skipped",
                    id=article.get("id"),
                    title=article.get("title"),
                    reason="newsflash",
                    current=idx,
                    total=total_articles,
                )
                continue

            content = article.get("content", "")
            summary = article.get("summary", "")

            if content and len(content) > 200:
                logger.info("  Using existing content (%s chars)", len(content))
            elif summary and len(summary) > 500:
                logger.info("  Summary is long enough (%s chars); skipping fetch", len(summary))
                content = summary
            else:
                logger.info("  Fetching article content...")
                fetched_content = fetch_article_content(article["link"])
                if fetched_content:
                    content = fetched_content
                logger.info("  Fetch complete: %s chars", len(content))

            min_length = PROJ_CONFIG.get("filter_min_length", 100)
            if len(content) < min_length:
                logger.info("  Skipped: content too short (%s < %s)", len(content), min_length)
                _emit_progress(
                    progress_callback,
                    "article_skipped",
                    id=article.get("id"),
                    title=article.get("title"),
                    reason="content_too_short",
                    current=idx,
                    total=total_articles,
                )
                continue

            if batch_scoring:
                batch_queue.append(
                    {
                        "article": article,
                        "title": article.get("title", ""),
                        "summary": summary,
                        "content": content,
                    }
                )
                if len(batch_queue) >= batch_size:
                    batch_payload = [
                        PreparedArticle(
                            article_id=str(item["article"].get("id") or ""),
                            title=item["title"],
                            url=item["article"].get("link", ""),
                            summary=item["summary"],
                            content=item["content"],
                        )
                        for item in batch_queue
                    ]
                    logger.info("  Submitting batch scoring task (size=%s)", len(batch_payload))
                    future = executor.submit(
                        get_analysis_service().analyze_many_prepared,
                        batch_payload,
                    )
                    pending_futures.append((future, list(batch_queue)))
                    batch_queue = []

                process_completed_futures()
            else:
                analysis = get_analysis_service().analyze_prepared(
                    PreparedArticle(
                        article_id=str(article.get("id") or ""),
                        title=article["title"],
                        url=article.get("link", ""),
                        summary=summary,
                        content=content,
                    )
                )
                record_analysis_result(article, analysis)

        if batch_scoring and batch_queue:
            batch_payload = [
                PreparedArticle(
                    article_id=str(item["article"].get("id") or ""),
                    title=item["title"],
                    url=item["article"].get("link", ""),
                    summary=item["summary"],
                    content=item["content"],
                )
                for item in batch_queue
            ]
            logger.info("  Submitting final batch scoring task (size=%s)", len(batch_payload))
            future = executor.submit(
                get_analysis_service().analyze_many_prepared,
                batch_payload,
            )
            pending_futures.append((future, list(batch_queue)))

        if batch_scoring:
            logger.info("Waiting for all scoring tasks to finish...")
            for future, batch_items in pending_futures:
                try:
                    batch_results = future.result()
                    for item, analysis in zip(batch_items, batch_results):
                        record_analysis_result(item["article"], analysis)
                except Exception as exc:
                    logger.error("Batch processing failed: %s", exc)
                    for item in batch_items:
                        record_analysis_result(
                            item["article"],
                            {
                                "status": "error",
                                "score": None,
                                "reason": str(exc),
                                "error": {
                                    "code": "batch_analysis_failed",
                                    "message": str(exc),
                                },
                            },
                        )
    finally:
        executor.shutdown(wait=True)

    analyzed_file = _build_monthly_output_path("analyzed_articles", "json")
    save_articles(analyzed_articles, analyzed_file)
    save_articles(analyzed_articles, LATEST_ANALYZED_FILE)

    marked_read_count = 0
    if mark_read and successful_article_ids:
        logger.info("Marking %s successfully analyzed articles as read...", len(successful_article_ids))
        if feedly_mark_read(successful_article_ids):
            marked_read_count = len(successful_article_ids)

    _emit_progress(progress_callback, "phase", phase="summarizing")
    summary_result = generate_summary_report(analyzed_articles)
    result = {
        "success": True,
        "input_file": input_file,
        "stream_id": stream_id,
        "refreshed": refresh,
        "loaded_count": len(articles),
        "processed_count": len(analyzed_articles),
        "successful_count": successful_count,
        "failed_count": len(analyzed_articles) - successful_count,
        "marked_read_count": marked_read_count,
        "analyzed_file": analyzed_file,
        "latest_analyzed_file": LATEST_ANALYZED_FILE,
        "articles": analyzed_articles,
        **summary_result,
    }
    _emit_progress(
        progress_callback,
        "progress",
        phase="completed",
        current=total_articles,
        total=total_articles,
    )
    return result
