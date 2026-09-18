"""
Shared backend message handlers for browser/native/local clients.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("RSS_SCORES_DB", str(PROJECT_ROOT / "rss_scores.db"))
os.environ.setdefault("RSS_VECTOR_DB_DIR", str(PROJECT_ROOT / "chroma_db"))

from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.cache import (
    build_vector_store_payload,
    get_app_cache,
    get_cached_score,
    iter_cached_scores,
    set_app_cache,
    save_cached_score,
)
from rss_analyzer.config import (
    LATEST_ANALYZED_FILE,
    LATEST_SUMMARY_FILE,
    LATEST_UNREAD_FILE,
    PROJ_CONFIG,
    get_vector_store_config,
    is_vector_store_enabled,
)
from rss_analyzer.feedly_client import feedly_fetch_unread, feedly_mark_read
from rss_analyzer.llm_analyzer import (
    analyze_article_with_llm,
    analyze_articles_with_llm_batch,
    generate_overall_summary,
    summarize_single_article,
)
from rss_analyzer.readflow_triage import (
    article_summary_snippet,
    build_readflow_triage_prompt,
    coerce_readflow_decision,
    normalize_readflow_domain,
    parse_readflow_triage_results,
)
from rss_analyzer.stream_strategy import (
    determine_stream_strategy,
    generate_stream_overview,
    render_stream_overview_markdown,
    save_stream_overview_markdown,
)
from rss_analyzer.utils import is_newsflash, load_articles, save_articles, strip_html_tags
logger = logging.getLogger(__name__)
_VECTOR_STORE = None
FEED_ID_36KR = "feed/http://www.36kr.com/feed"
BATCH_TRIAGE_CACHE_VERSION = 1
BATCH_READ_FETCH_LIMIT = 9999


@dataclass
class FilterResult:
    matched: list
    remaining: list
    label: str


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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


def get_vector_store():
    if not is_vector_store_enabled():
        return None

    global _VECTOR_STORE
    if _VECTOR_STORE is None:
        from rss_analyzer.vector_store import vector_store as shared_vector_store

        _VECTOR_STORE = shared_vector_store
    return _VECTOR_STORE


def _vector_store_disabled_error(operation: str) -> dict:
    return {
        "error": "vector_store_disabled",
        "message": f"Vector store is disabled; cannot {operation}.",
    }


def _vector_store_disabled_result(**payload) -> dict:
    return {
        **payload,
        "disabled": True,
        "message": "Vector store is disabled.",
    }


def _build_monthly_output_path(prefix: str, suffix: str) -> str:
    now = datetime.now()
    output_dir = Path("output") / now.strftime("%Y-%m")
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir / f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.{suffix}")


def generate_summary_report(articles: list[dict]) -> dict:
    logger.info("Generating overall summary for %s articles", len(articles))
    overall_summary = generate_overall_summary(articles)
    summary_file = _build_monthly_output_path("summary", "md")

    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(overall_summary)
    with open(LATEST_SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(overall_summary)

    return {
        "success": True,
        "article_count": len(articles),
        "summary": overall_summary,
        "summary_file": summary_file,
        "latest_summary_file": LATEST_SUMMARY_FILE,
    }


def generate_daily_digest(
    *,
    stream_id: str | None = None,
    stream_label: str | None = None,
    hours: int = 24,
    top_n: int = 10,
) -> dict:
    """Generate a daily digest from recently scored articles.

    Pulls articles from the score cache, filters by time window,
    and produces a structured Markdown report with must_read / skim tiers.
    """
    from datetime import timedelta, timezone

    cutoff = datetime.now() - timedelta(hours=hours)
    cached = iter_cached_scores()

    recent = []
    for item in cached:
        updated = item.get("updated_at")
        if not updated:
            continue
        try:
            ts = datetime.fromisoformat(updated) if isinstance(updated, str) else updated
            if ts >= cutoff:
                recent.append(item)
        except (ValueError, TypeError):
            continue

    if not recent:
        return {
            "success": True,
            "article_count": 0,
            "summary": f"最近 {hours} 小时内没有已评分的文章。",
            "markdown": "",
        }

    recent.sort(key=lambda x: x.get("score", 0), reverse=True)

    must_read = [item for item in recent if item.get("score", 0) >= 3.8][:top_n]
    skim = [item for item in recent if 2.5 <= item.get("score", 0) < 3.8][:top_n]
    low = [item for item in recent if item.get("score", 0) < 2.5]

    lines = [
        "# RSS Daily Digest",
        "",
        f"- 时间窗口: 最近 {hours} 小时",
        f"- 已评分文章: {len(recent)} 篇",
        f"- Must Read: {len(must_read)} 篇",
        f"- Skim: {len(skim)} 篇",
        f"- Low Priority: {len(low)} 篇",
        "",
        "## Must Read",
    ]

    for item in must_read:
        data = item.get("data") or {}
        title = data.get("title", item.get("article_id", "Unknown"))
        url = data.get("url", "")
        score = item.get("score", 0)
        summary = (data.get("summary") or data.get("comment", ""))[:200]
        if url:
            lines.append(f"- [{title}]({url}) (score: {score:.1f})")
        else:
            lines.append(f"- {title} (score: {score:.1f})")
        if summary:
            lines.append(f"  - {summary}")

    lines.extend(["", "## Skim"])
    for item in skim:
        data = item.get("data") or {}
        title = data.get("title", item.get("article_id", "Unknown"))
        url = data.get("url", "")
        score = item.get("score", 0)
        if url:
            lines.append(f"- [{title}]({url}) (score: {score:.1f})")
        else:
            lines.append(f"- {title} (score: {score:.1f})")

    markdown = "\n".join(lines) + "\n"

    output_file = save_stream_overview_markdown(
        markdown,
        stream_label=stream_label or "daily-digest",
        strategy="daily_digest",
    )

    return {
        "success": True,
        "article_count": len(recent),
        "must_read_count": len(must_read),
        "skim_count": len(skim),
        "low_count": len(low),
        "hours": hours,
        "summary": f"最近 {hours} 小时 {len(recent)} 篇文章，{len(must_read)} 篇必读",
        "markdown": markdown,
        "output_file": output_file,
    }


def regenerate_summary(input_file: str = LATEST_ANALYZED_FILE) -> dict:
    if not os.path.exists(input_file):
        return {
            "error": "input_not_found",
            "message": f"Could not find analyzed articles file: {input_file}",
        }

    articles = load_articles(input_file)
    result = generate_summary_report(articles)
    result["input_file"] = input_file
    return result


def export_articles(limit: int, output_file: str, stream_id: str | None = None) -> dict:
    logger.info("Exporting up to %s unread articles to %s", limit, output_file)
    articles = feedly_fetch_unread(limit=limit, stream_id=stream_id)
    if articles is None:
        return {
            "error": "fetch_failed",
            "message": "Failed to fetch unread articles from Feedly.",
        }

    save_articles(articles, output_file)
    return {
        "success": True,
        "stream_id": stream_id,
        "limit": limit,
        "article_count": len(articles),
        "output_file": output_file,
    }


def analyze_articles(
    *,
    input_file: str = LATEST_UNREAD_FILE,
    limit: int | None = None,
    mark_read: bool = False,
    refresh: bool = True,
    stream_id: str | None = None,
    threads: int | None = None,
) -> dict:
    effective_limit = limit or int(PROJ_CONFIG["limit"])

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

    analyzed_articles: list[dict] = []
    seen_titles: set[str] = set()
    batch_scoring = PROJ_CONFIG.get("batch_scoring", False)
    batch_size = max(1, int(PROJ_CONFIG.get("batch_size", 1)))
    batch_queue: list[dict] = []

    max_workers = threads or int(PROJ_CONFIG.get("max_workers", 3))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    pending_futures: list[tuple[concurrent.futures.Future, list[dict]]] = []

    def record_analysis_result(article_item: dict, analysis_result: dict) -> None:
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
            else:
                still_pending.append((future, batch_items))
        pending_futures = still_pending

    all_article_ids = [a["id"] for a in articles[:effective_limit] if a.get("id")]

    try:
        for idx, article in enumerate(articles[:effective_limit], 1):
            logger.info(
                "Processing article %s/%s: %s",
                idx,
                min(effective_limit, len(articles)),
                article["title"],
            )

            filter_keywords = PROJ_CONFIG.get("filter_keywords", [])
            if any(kw in article["title"] for kw in filter_keywords):
                logger.info("  Skipped: title matched filter keyword")
                continue

            filter_url_patterns = PROJ_CONFIG.get("filter_url_patterns", [])
            article_url = article.get("link", "") or article.get("originId", "")
            if any(pattern in article_url for pattern in filter_url_patterns):
                logger.info("  Skipped: URL matched filter pattern (%s)", article_url)
                continue

            norm_title = "".join(filter(str.isalnum, article["title"].lower()))
            if len(norm_title) > 5:
                if norm_title in seen_titles:
                    logger.info("  Skipped: duplicate title")
                    continue
                seen_titles.add(norm_title)

            if is_newsflash(article):
                logger.info("  Skipped: detected as newsflash")
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
                        {
                            "title": item["title"],
                            "summary": item["summary"],
                            "content": item["content"],
                        }
                        for item in batch_queue
                    ]
                    logger.info("  Submitting batch scoring task (size=%s)", len(batch_payload))
                    future = executor.submit(analyze_articles_with_llm_batch, batch_payload)
                    pending_futures.append((future, list(batch_queue)))
                    batch_queue = []

                process_completed_futures()
            else:
                analysis = analyze_article_with_llm(article["title"], summary, content)
                record_analysis_result(article, analysis)

        if batch_scoring and batch_queue:
            batch_payload = [
                {
                    "title": item["title"],
                    "summary": item["summary"],
                    "content": item["content"],
                }
                for item in batch_queue
            ]
            logger.info("  Submitting final batch scoring task (size=%s)", len(batch_payload))
            future = executor.submit(analyze_articles_with_llm_batch, batch_payload)
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
    finally:
        executor.shutdown(wait=True)

    analyzed_file = _build_monthly_output_path("analyzed_articles", "json")
    save_articles(analyzed_articles, analyzed_file)
    save_articles(analyzed_articles, LATEST_ANALYZED_FILE)

    marked_read_count = 0
    if mark_read and all_article_ids:
        logger.info("Marking %s articles as read...", len(all_article_ids))
        if feedly_mark_read(all_article_ids):
            marked_read_count = len(all_article_ids)

    summary_result = generate_summary_report(analyzed_articles)
    return {
        "success": True,
        "input_file": input_file,
        "stream_id": stream_id,
        "refreshed": refresh,
        "loaded_count": len(articles),
        "processed_count": len(analyzed_articles),
        "marked_read_count": marked_read_count,
        "analyzed_file": analyzed_file,
        "latest_analyzed_file": LATEST_ANALYZED_FILE,
        "articles": analyzed_articles,
        **summary_result,
    }


def _prepare_article_analysis_inputs(article: dict) -> tuple[str, str]:
    content = article.get("content", "") or ""
    summary = article.get("summary", "") or ""
    link = article.get("link")

    if content and len(content) > 200:
        return summary, content

    if summary and len(summary) > 500:
        return summary, summary

    if link:
        fetched_content = fetch_article_content(link)
        if fetched_content:
            return summary, fetched_content

    return summary, content or summary


def _truncate_title(title: str | None, limit: int = 72) -> str:
    text = (title or "").strip() or "Untitled"
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _deep_analysis_log_step(total: int) -> int:
    if total <= 5:
        return 1
    if total <= 12:
        return 2
    return 5


def _deep_analyze_digest_candidate(item: dict) -> tuple[str, dict]:
    summary, content = _prepare_article_analysis_inputs(item)
    enriched = dict(item)
    enriched["openable"] = bool(item.get("link"))

    if not content and not summary:
        return "skipped", enriched

    analysis = analyze_article_with_llm(item.get("title", ""), summary, content)
    enriched["score"] = analysis.get("score")
    enriched["verdict"] = analysis.get("verdict")
    enriched["analysis_summary"] = analysis.get("summary")
    enriched["reason"] = analysis.get("reason")
    enriched["analysis"] = analysis
    return "analyzed", enriched


def _deep_analyze_digest_candidates(items: list[dict]) -> list[dict]:
    if not items:
        return []

    total = len(items)
    max_workers = max(1, int(PROJ_CONFIG.get("max_workers", 3)))
    log_step = _deep_analysis_log_step(total)
    logger.info(
        "Process Stream: deep analyzing %s must-read candidates with %s workers...",
        total,
        max_workers,
    )

    analyzed_items: list[dict | None] = [None] * total
    completed = 0
    analyzed_count = 0
    skipped_count = 0
    failed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(_deep_analyze_digest_candidate, item): index
            for index, item in enumerate(items)
        }

        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            original_item = items[index]
            title = _truncate_title(original_item.get("title"))
            completed += 1

            try:
                status, enriched = future.result()
                analyzed_items[index] = enriched
                if status == "analyzed":
                    analyzed_count += 1
                else:
                    skipped_count += 1

                should_log_progress = (
                    log_step == 1
                    or completed == 1
                    or completed == total
                    or completed % log_step == 0
                )
                if status == "analyzed" and should_log_progress:
                    logger.info(
                        "Process Stream: [%s/%s] deep analyzed %s (score: %.1f)",
                        completed,
                        total,
                        title,
                        enriched.get("score", 0.0),
                    )
                elif status != "analyzed" and should_log_progress:
                    logger.info(
                        "Process Stream: [%s/%s] progress checkpoint at %s (%s)",
                        completed,
                        total,
                        title,
                        "content too short",
                    )
            except Exception as exc:
                logger.warning("Digest deep analysis failed for %s: %s", original_item.get("title"), exc)
                fallback_item = dict(original_item)
                fallback_item["openable"] = bool(original_item.get("link"))
                analyzed_items[index] = fallback_item
                failed_count += 1
                should_log_progress = (
                    log_step == 1
                    or completed == 1
                    or completed == total
                    or completed % log_step == 0
                )
                if should_log_progress:
                    logger.info(
                        "Process Stream: [%s/%s] progress checkpoint at %s (%s)",
                        completed,
                        total,
                        title,
                        "analysis failed",
                    )

    logger.info(
        "Process Stream: finished deep analysis for %s candidates (%s analyzed, %s skipped, %s failed).",
        total,
        analyzed_count,
        skipped_count,
        failed_count,
    )
    return [item for item in analyzed_items if item is not None]


def _mark_digest_openable(items: list[dict]) -> list[dict]:
    marked_items = []
    for item in items:
        enriched = dict(item)
        enriched["openable"] = bool(item.get("link"))
        marked_items.append(enriched)
    return marked_items


def _refresh_digest_metadata(digest: dict) -> dict:
    must_read_items = digest.get("deep_analyzed_reads", [])
    skim_items = digest.get("skim_items", [])
    clear_items = digest.get("clear_items", [])
    fetched_count = digest.get("stats", {}).get("fetched_count", 0)
    candidate_count = digest.get("stats", {}).get("candidate_count", 0)
    clear_ratio = (len(clear_items) / fetched_count) if fetched_count else 0.0

    actions = []
    if must_read_items:
        actions.append(f"先看 must-read 的 {len(must_read_items)} 篇重点文章。")
    if skim_items:
        actions.append(f"若时间有限，只抽样 skim 区里的 {min(3, len(skim_items))} 篇代表项。")
    if clear_items:
        actions.append(f"可批量已读 {len(clear_items)} 条低优先级或重复噪音内容。")

    digest["actions"] = actions
    digest["stats"] = {
        "fetched_count": fetched_count,
        "candidate_count": candidate_count,
        "must_read_count": len(must_read_items),
        "skim_count": len(skim_items),
        "clear_count": len(clear_items),
        "clear_ratio": clear_ratio,
    }
    return digest


def _rerank_digest_after_analysis(digest: dict) -> dict:
    retained_must_read: list[dict] = []
    demoted_to_skim: list[dict] = []
    demoted_to_clear: list[dict] = []

    for item in digest.get("deep_analyzed_reads", []):
        score = item.get("score")
        verdict = item.get("verdict", "")
        relevance = (
            item.get("analysis", {})
            .get("detailed_scores", {})
            .get("relevance", 0)
        )

        if score is None:
            retained_must_read.append(item)
            continue

        if score < 2.5 or relevance <= 1 or "不太值得" in verdict:
            demoted_to_clear.append(item)
            continue

        if score < 3.6:
            demoted_to_skim.append(item)
            continue

        retained_must_read.append(item)

    existing_skim = digest.get("skim_items", [])
    existing_clear = digest.get("clear_items", [])

    digest["deep_analyzed_reads"] = retained_must_read
    digest["must_read_candidates"] = retained_must_read
    digest["skim_items"] = _mark_digest_openable(demoted_to_skim + existing_skim)
    digest["clear_items"] = _mark_digest_openable(demoted_to_clear + existing_clear)
    return _refresh_digest_metadata(digest)


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
        mark_filter_results_as_read(result.matched, result.label, dry_run, mark_read)
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


def _fetch_content(article: dict) -> str:
    link = article.get("canonicalUrl") or article.get("alternate", [{}])[0].get(
        "href", ""
    )
    return fetch_article_content(link) if link else ""


def _prepare_article_scoring(article: dict) -> dict:
    title = article.get("title", "")
    summary = article.get("summary", "")
    content = article.get("content", "")

    if not (content and len(content) > 200):
        content = summary if len(summary) > 500 else _fetch_content(article) or summary

    return {"title": title, "summary": summary, "content": content}


def _score_article(article: dict) -> tuple[float, dict]:
    payload = _prepare_article_scoring(article)
    try:
        result = analyze_article_with_llm(
            payload.get("title", ""),
            payload.get("summary", ""),
            payload.get("content", ""),
        )
        return result.get("score", 0.0), result
    except Exception as exc:
        logger.debug("Scoring failed: %s", exc)
        return -1.0, {}


def _handle_scored_filter_article(
    article: dict,
    score: float,
    prefix: str,
    threshold: float,
    dry_run: bool,
    matched: list,
    remaining: list,
    mark_read: bool,
) -> None:
    title_str = article.get("title", "Unknown Title")
    if score < 0:
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
    else:
        logger.info("%s Result: kept %s (%.1f)", prefix, title_str, score)
        remaining.append(article)


def low_score_filter(
    articles: list,
    threshold: float = 3.0,
    dry_run: bool = False,
    mark_read: bool = True,
) -> FilterResult:
    matched = []
    remaining = []
    batch_scoring = PROJ_CONFIG.get("batch_scoring", False)
    batch_size = max(1, int(PROJ_CONFIG.get("batch_size", 1)))
    batch_queue = []

    def flush_batch() -> None:
        nonlocal batch_queue
        if not batch_queue:
            return

        batch_payload = [item["payload"] for item in batch_queue]
        batch_results = analyze_articles_with_llm_batch(batch_payload)
        for item, analysis in zip(batch_queue, batch_results):
            score = analysis.get("score", 0.0)
            save_cached_score(item["article"].get("id"), score, analysis)
            _handle_scored_filter_article(
                item["article"],
                score,
                item["prefix"],
                threshold,
                dry_run,
                matched,
                remaining,
                mark_read,
            )
        batch_queue = []

    for idx, article in enumerate(articles, 1):
        title = article.get("title", "")[:50]
        prefix = f"[{idx}/{len(articles)}]"
        article_id = article.get("id")

        cached = get_cached_score(article_id)
        if cached:
            if batch_scoring and batch_queue:
                flush_batch()

            score = cached["score"]
            logger.info("%s Using cached score for %s", prefix, title)
            _handle_scored_filter_article(
                article,
                score,
                prefix,
                threshold,
                dry_run,
                matched,
                remaining,
                mark_read,
            )
            continue

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
            score, analysis = _score_article(article)
            if score >= 0:
                save_cached_score(article_id, score, analysis)

            _handle_scored_filter_article(
                article,
                score,
                prefix,
                threshold,
                dry_run,
                matched,
                remaining,
                mark_read,
            )

    if batch_scoring and batch_queue:
        flush_batch()

    logger.info(
        "Low-score filter matched %s articles and kept %s",
        len(matched),
        len(remaining),
    )
    return FilterResult(matched, remaining, "low-score")


def run_filter_workflow(
    *,
    mode: str,
    limit: int,
    threshold: float = 3.0,
    dry_run: bool = False,
    mark_read: bool = False,
    stream_id: str | None = None,
) -> dict:
    target_stream = stream_id

    if mode == "newsflash":
        if not target_stream:
            target_stream = FEED_ID_36KR
        articles = fetch_filter_articles(limit, stream_id=target_stream)
        filters = [newsflash_filter]
    elif mode == "low-score":
        articles = fetch_filter_articles(limit, stream_id=target_stream)
        filters = [
            lambda items: low_score_filter(items, threshold, dry_run, mark_read)
        ]
    else:
        articles = fetch_filter_articles(limit, stream_id=target_stream)
        filters = [
            newsflash_filter,
            lambda items: low_score_filter(items, threshold, dry_run, mark_read),
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
    }


def process_stream(
    *,
    stream_id: str | None,
    stream_label: str | None = None,
    days: int = 3,
    limit: int = 500,
    strategy: str | None = None,
    export_markdown: bool = False,
) -> dict:
    articles = fetch_filter_articles(limit, stream_id=stream_id)
    resolved_strategy = strategy or determine_stream_strategy(stream_id, stream_label)
    result = generate_stream_overview(
        articles,
        stream_id=stream_id,
        stream_label=stream_label,
        strategy=resolved_strategy,
        days=days,
    )
    result["fetched_count"] = len(articles)

    digest = dict(result.get("digest") or {})
    digest["must_read_candidates"] = _mark_digest_openable(
        digest.get("must_read_candidates", [])
    )
    digest["skim_items"] = _mark_digest_openable(digest.get("skim_items", []))
    digest["clear_items"] = _mark_digest_openable(digest.get("clear_items", []))
    digest["deep_analyzed_reads"] = _deep_analyze_digest_candidates(
        digest.get("must_read_candidates", [])
    )
    digest = _rerank_digest_after_analysis(digest)
    result["digest"] = digest
    result["worth_expanding_items"] = digest.get("deep_analyzed_reads", [])
    result["low_priority_items"] = digest.get("clear_items", result.get("low_priority_items", []))
    result["mark_read_candidates"] = [
        item["id"] for item in digest.get("clear_items", []) if item.get("id")
    ]
    result["summary"] = digest.get("headline", result.get("summary", ""))
    result["markdown"] = render_stream_overview_markdown(
        strategy=result["strategy"],
        stream_label=stream_label or stream_id or "Selected stream",
        days=days,
        article_count=result["article_count"],
        summary=result["summary"],
        theme_groups=result.get("theme_groups", []),
        worth_expanding_items=result.get("worth_expanding_items", []),
        worth_expanding_overflow_count=result.get("worth_expanding_overflow_count", 0),
        low_priority_items=result.get("low_priority_items", []),
        digest=digest,
    )

    if export_markdown:
        result["overview_file"] = save_stream_overview_markdown(
            result["markdown"],
            stream_label=stream_label or stream_id,
            strategy=result["strategy"],
        )

    return result


def _article_summary_snippet(article: dict, limit: int = 800) -> str:
    return article_summary_snippet(article, limit)


def _extract_json_array(raw: str) -> list:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or start >= end:
        raise ValueError("no JSON array found")
    json_str = text[start : end + 1]
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as exc:
        # Attempt to fix common LLM JSON errors
        logger.debug("Initial JSON parse failed: %s, attempting recovery", exc)
        import re

        # Fix Chinese colons (：) to regular colons (:)
        fixed = json_str.replace("：", ":")
        # Fix double colons pattern: "key":": "value" → "key": "value"
        fixed = re.sub(r'":\s*"\s*:\s*"', '": "', fixed)
        # Fix missing commas between } and { (most common LLM error)
        fixed = re.sub(r"\}\s*\n\s*\{", "},\n{", fixed)
        # Fix trailing commas before ] or }
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        try:
            parsed = json.loads(fixed)
        except json.JSONDecodeError:
            # Log the problematic region for debugging
            pos = getattr(exc, "pos", None)
            if pos is not None:
                snippet = json_str[max(0, pos - 100) : pos + 100]
                logger.warning("JSON parse error near position %d: ...%s...", pos, snippet)
            raise
    if not isinstance(parsed, list):
        raise ValueError("triage response is not a JSON array")
    return parsed


def _normalize_batch_domain(domain: str | None) -> str:
    return normalize_readflow_domain(domain)


def _coerce_batch_decision(decision: str | None, score: float) -> str:
    return coerce_readflow_decision(decision, score)


def _p2_keyword_hit(article: dict) -> bool:
    text = f"{article.get('title', '')} {_article_summary_snippet(article, 400)}".lower()
    keywords = (
        "地缘",
        "国际政治",
        "外交",
        "制裁",
        "关税",
        "战争",
        "停火",
        "冲突",
        "军援",
        "北约",
        "欧盟",
        "联合国",
        "白宫",
        "五角大楼",
        "国务院",
        "中东",
        "台海",
        "台湾",
        "乌克兰",
        "俄罗斯",
        "以色列",
        "伊朗",
        "哈马斯",
        "美国",
        "中国",
        "拜登",
        "特朗普",
        "普京",
    )
    return any(keyword in text for keyword in keywords)


def _fallback_batch_triage(article: dict, bucket: str | None = None) -> dict:
    is_p2 = bucket == "国际政治 / P2" or _p2_keyword_hit(article)
    summary = _article_summary_snippet(article, 400)
    domain = "P2" if is_p2 else "Other"
    score = 3.4 if is_p2 else 2.6
    decision = "skim" if is_p2 else "skim"
    return {
        "domain": domain,
        "domain_confidence": 0.65 if is_p2 else 0.35,
        "score": score,
        "decision": decision,
        "event": article.get("title", "Untitled"),
        "actors": "",
        "region": "",
        "core_fact": summary or article.get("title", "Untitled"),
        "why_it_matters": "需要快速判断是否有新增事实。" if is_p2 else "",
        "novelty": "unknown",
        "needs_deep_read": bool(is_p2 and len(summary) < 240 and article.get("link")),
        "rec": "P2 候选，需看事实增量" if is_p2 else "常规候选",
        "source": "fallback",
    }


def _cached_batch_triage(article: dict) -> dict | None:
    article_id = article.get("id", "")
    if not article_id:
        return None
    cached = get_app_cache(f"batch_triage:v{BATCH_TRIAGE_CACHE_VERSION}:{article_id}")
    if not cached:
        return None
    return dict(cached)


def _save_batch_triage(article: dict, triage: dict) -> None:
    article_id = article.get("id", "")
    if not article_id:
        return
    set_app_cache(
        f"batch_triage:v{BATCH_TRIAGE_CACHE_VERSION}:{article_id}",
        triage,
        ttl_seconds=14 * 24 * 60 * 60,
    )


def _build_batch_triage_prompt(articles: list[dict]) -> str:
    return build_readflow_triage_prompt(articles, max_summary_chars=800, max_content_chars=0)


def _parse_batch_triage_results(articles: list[dict], raw_items: list) -> dict[str, dict]:
    return parse_readflow_triage_results(articles, raw_items)


def _batch_triage_articles(
    articles: list[dict],
    chunk_size: int = 50,
    stats: dict | None = None,
) -> dict[str, dict]:
    """Triage all articles with title + origin + summary, chunked for latency."""
    from openai import OpenAI

    from rss_analyzer.config import build_openai_client_kwargs, get_openai_task_config

    if not articles:
        return {}

    cfg = get_openai_task_config("summary", "gpt-4o-mini")
    client = OpenAI(**build_openai_client_kwargs(cfg))
    final: dict[str, dict] = {}
    uncached: list[dict] = []

    for article in articles:
        cached = _cached_batch_triage(article)
        if cached:
            final[article.get("id", "")] = cached
        else:
            uncached.append(article)

    size = max(1, int(chunk_size or 50))
    llm_chunk_count = 0
    fallback_chunk_count = 0
    for chunk in _chunked(uncached, size):
        try:
            llm_chunk_count += 1
            resp = client.chat.completions.create(
                model=cfg.model,
                messages=[{"role": "user", "content": _build_batch_triage_prompt(chunk)}],
                temperature=0.2,
                max_tokens=8192,
            )
            raw = resp.choices[0].message.content if resp.choices else ""
            parsed = _parse_batch_triage_results(chunk, _extract_json_array(raw))
            for article in chunk:
                aid = article.get("id", "")
                triage = parsed.get(aid) or _fallback_batch_triage(article)
                final[aid] = triage
                _save_batch_triage(article, triage)
        except Exception:
            fallback_chunk_count += 1
            logger.warning("Batch triage chunk failed; using fallback triage", exc_info=True)
            for article in chunk:
                aid = article.get("id", "")
                triage = _fallback_batch_triage(article)
                final[aid] = triage
                _save_batch_triage(article, triage)

    if stats is not None:
        stats.update(
            {
                "triage_cached_count": len(articles) - len(uncached),
                "triage_uncached_count": len(uncached),
                "llm_chunk_count": llm_chunk_count,
                "fallback_chunk_count": fallback_chunk_count,
                "llm_chunk_size": size,
            }
        )

    logger.info(
        "Batch triaged %s/%s articles (%s cached, %s LLM chunks)",
        len(final),
        len(articles),
        len(articles) - len(uncached),
        llm_chunk_count,
    )
    return final


def process_batch(
    *,
    stream_id: str | None,
    stream_label: str | None = None,
    batch_size: int = 100,
    days: int = 3,
) -> dict:
    """Process a single batch of unread articles for batch reading mode.

    Fetches the unread backlog, then triages every recent article in
    chunked LLM calls using title, source, and Feedly summary.  ``batch_size``
    controls LLM chunk size, not the number of articles fetched.
    """
    from rss_analyzer.stream_strategy import (
        _bucket_key,
        _is_low_priority,
        _prefilter_articles,
        _rank_article,
        filter_recent_articles,
    )

    articles = fetch_filter_articles(BATCH_READ_FETCH_LIMIT, stream_id=stream_id)
    if not articles:
        return {
            "success": True,
            "strategy": "batch",
            "article_count": 0,
            "fetched_count": 0,
            "summary": "No unread articles found.",
            "digest": None,
            "markdown": "",
        }

    recent = filter_recent_articles(articles, days)
    prefiltered_out, recent = _prefilter_articles(recent)

    logger.info("Batch triaging %s articles in chunks of %s...", len(recent), batch_size)
    triage_stats: dict = {}
    triage_map = _batch_triage_articles(recent, batch_size, stats=triage_stats)

    original_by_id = {a.get("id", ""): a for a in recent}
    grouped: dict[str, list[dict]] = {}
    clear_items: list[dict] = []
    all_candidates: list[dict] = []

    # Pre-filtered articles (keyword/URL/short) go directly to clear
    for article in prefiltered_out:
        clear_items.append({
            "id": article.get("id", ""),
            "title": article.get("title", "No Title"),
            "link": article.get("link", ""),
            "origin": article.get("origin", ""),
            "published": article.get("published", 0),
            "bucket": "prefiltered",
            "summary": _article_summary_snippet(article, 400),
            "low_priority": True,
            "score": 0.0,
            "interpretation": "关键词/URL/长度预筛命中",
            "domain": "Other",
            "domain_confidence": 1.0,
            "decision": "clear",
            "event": "",
            "actors": "",
            "region": "",
            "core_fact": "",
            "why_it_matters": "",
            "novelty": "repeat",
            "needs_deep_read": False,
        })

    for article in recent:
        bucket = _bucket_key(article, stream_label)
        aid = article.get("id", "")
        triage = triage_map.get(aid) or _fallback_batch_triage(article, bucket)
        if triage.get("domain") == "P2":
            bucket = "国际政治 / P2"
        is_low = _is_low_priority(article, bucket)
        preview = {
            "id": aid,
            "title": article.get("title", "No Title"),
            "link": article.get("link", ""),
            "origin": article.get("origin", ""),
            "published": article.get("published", 0),
            "bucket": bucket,
            "summary": _article_summary_snippet(article, 400),
            "low_priority": is_low,
            "score": triage.get("score"),
            "interpretation": triage.get("rec", ""),
            "domain": triage.get("domain", "Other"),
            "domain_confidence": triage.get("domain_confidence", 0.0),
            "decision": triage.get("decision", "skim"),
            "event": triage.get("event", ""),
            "actors": triage.get("actors", ""),
            "region": triage.get("region", ""),
            "core_fact": triage.get("core_fact", ""),
            "why_it_matters": triage.get("why_it_matters", ""),
            "novelty": triage.get("novelty", "unclear"),
            "needs_deep_read": triage.get("needs_deep_read", False),
        }
        if preview["decision"] == "clear" or (is_low and preview["domain"] != "P2"):
            clear_items.append(preview)
        else:
            grouped.setdefault(bucket, []).append(preview)
            all_candidates.append(preview)

    theme_groups = []
    for bucket, items in sorted(
        grouped.items(), key=lambda e: (-len(e[1]), e[0])
    ):
        sorted_items = sorted(
            items,
            key=lambda item: (float(item.get("score") or 0), _rank_article(item)),
            reverse=True,
        )
        theme_groups.append(
            {
                "bucket": bucket,
                "count": len(items),
                "low_priority_count": sum(1 for item in items if item.get("low_priority")),
                "summary": f"{len(items)} articles",
                "representatives": sorted_items[:3],
            }
        )

    p2_candidates = [item for item in all_candidates if item.get("domain") == "P2"]
    deep_inputs = []
    for preview in p2_candidates:
        if not preview.get("needs_deep_read"):
            continue
        original = original_by_id.get(preview.get("id", ""))
        if original:
            merged = dict(original)
            merged.update(preview)
            deep_inputs.append(merged)
        else:
            deep_inputs.append(preview)

    logger.info("Deep analyzing %s P2 candidates that need full text...", len(deep_inputs))
    deep_results = _deep_analyze_digest_candidates(deep_inputs)
    deep_by_id = {item.get("id", ""): item for item in deep_results}

    must_read: list[dict] = []
    skim: list[dict] = []
    demoted_clear: list[dict] = []

    for item in all_candidates:
        enriched = deep_by_id.get(item.get("id", ""), item)
        score = enriched.get("score")
        decision = enriched.get("decision", item.get("decision", "skim"))
        if item.get("id") in deep_by_id:
            if score is not None and score < 2.5:
                decision = "clear"
            elif score is not None and score < 3.6:
                decision = "skim"
            elif score is not None:
                decision = "must_read"
            enriched["decision"] = decision

        if decision == "clear":
            demoted_clear.append(enriched)
        elif decision == "must_read":
            must_read.append(enriched)
        else:
            skim.append(enriched)

    def _priority_key(item: dict) -> tuple:
        is_p2 = 1 if item.get("domain") == "P2" else 0
        needs_deep = 1 if item.get("needs_deep_read") else 0
        return (
            is_p2,
            float(item.get("score") or 0),
            needs_deep,
            _rank_article(item),
        )

    must_read.sort(key=_priority_key, reverse=True)
    skim.sort(key=_priority_key, reverse=True)

    clear_items = demoted_clear + clear_items

    p2_items = sorted(
        [deep_by_id.get(item.get("id", ""), item) for item in p2_candidates],
        key=_priority_key,
        reverse=True,
    )
    p2_must = [item for item in p2_items if item.get("decision") == "must_read"]
    p2_skim = [item for item in p2_items if item.get("decision") == "skim"]
    p2_clear = [item for item in clear_items if item.get("domain") == "P2"]
    p2_briefing = {
        "headline": (
            f"P2 命中 {len(p2_items) + len(p2_clear)} 条，"
            f"{len(p2_must)} 条建议优先点开，{len(deep_results)} 条已做正文复核。"
        ),
        "must_read": _mark_digest_openable(p2_must),
        "skim": _mark_digest_openable(p2_skim),
        "clear": _mark_digest_openable(p2_clear),
        "items": _mark_digest_openable(p2_items),
    }

    digest = {
        "headline": (
            f"{len(articles)} articles fetched, {len(recent)} in window, "
            f"{len(triage_map)} triaged, {len(deep_results)} P2 deep-analyzed"
        ),
        "executive_summary": p2_briefing["headline"],
        "top_themes": theme_groups,
        "must_read_candidates": _mark_digest_openable(must_read),
        "deep_analyzed_reads": _mark_digest_openable(must_read),
        "skim_items": _mark_digest_openable(skim),
        "clear_items": _mark_digest_openable(clear_items),
        "triage_items": _mark_digest_openable(all_candidates + clear_items),
        "p2_items": _mark_digest_openable(p2_items),
        "p2_briefing": p2_briefing,
        "actions": [],
        "stats": {
            "fetched_count": len(articles),
            "article_count": len(recent),
            "candidate_count": len(all_candidates),
            "must_read_count": len(must_read),
            "skim_count": len(skim),
            "clear_count": len(clear_items),
            "ai_scored_count": len(triage_map),
            "triage_count": len(triage_map),
            "p2_count": len(p2_items) + len(p2_clear),
            "p2_deep_analyzed_count": len(deep_results),
            **triage_stats,
        },
    }

    mark_read_candidates = [item["id"] for item in clear_items if item.get("id")]

    # Auto mark-read for low-score articles when threshold is configured
    auto_mark_threshold = PROJ_CONFIG.get("auto_mark_read_threshold", 0)
    auto_marked_result = None
    if auto_mark_threshold and mark_read_candidates:
        auto_marked_result = mark_articles_read(mark_read_candidates, dry_run=False)
        digest["auto_marked_read"] = auto_marked_result
        logger.info(
            "Auto marked %s clear articles as read (threshold=%.1f)",
            auto_marked_result.get("marked_count", 0),
            auto_mark_threshold,
        )

    return {
        "success": True,
        "strategy": "batch",
        "article_count": len(recent),
        "fetched_count": len(articles),
        "summary": digest["headline"],
        "digest": digest,
        "mark_read_candidates": mark_read_candidates,
        "auto_marked_read": auto_marked_result,
        "markdown": "",
    }


def mark_articles_read(article_ids: list[str], *, dry_run: bool = False) -> dict:
    """Mark a list of article IDs as read in Feedly.

    Returns a dict with success status and counts.
    """
    cleaned_ids = [aid for aid in article_ids if aid]
    if not cleaned_ids:
        return {"success": True, "marked_count": 0, "candidate_count": 0, "dry_run": dry_run}
    success = mark_article_ids_as_read(
        cleaned_ids, label="batch-read", dry_run=dry_run, mark_read=True
    )
    return {
        "success": success,
        "marked_count": len(cleaned_ids) if success and not dry_run else 0,
        "candidate_count": len(cleaned_ids),
        "dry_run": dry_run,
    }


def mark_stream_low_priority_read(article_ids: list[str], *, dry_run: bool = False) -> dict:
    cleaned_ids = [article_id for article_id in article_ids if article_id]
    success = mark_article_ids_as_read(
        cleaned_ids,
        label="low-priority",
        dry_run=dry_run,
        mark_read=True,
    )
    return {
        "success": success,
        "marked_count": len(cleaned_ids) if success and not dry_run else 0,
        "candidate_count": len(cleaned_ids),
        "dry_run": dry_run,
    }


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
    if not is_vector_store_enabled():
        return _vector_store_disabled_result(query=query, results=[])
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {"error": "vector_store_unavailable", "message": "Vector store is not available."}
        results = vector_store.search_similar(query, limit, min_score)
        return {"query": query, "results": results}
    except Exception as exc:
        logger.error("Semantic search error: %s", exc)
        return {"error": "search_failed", "message": str(exc)}


def _handle_get_article_tags(msg: dict) -> dict:
    article_id = msg.get("article_id")
    if not article_id:
        return {"error": "no_article_id", "message": "Article ID is required"}

    logger.info("Handling get_article_tags: article_id=%r", article_id)
    if not is_vector_store_enabled():
        return _vector_store_disabled_result(article_id=article_id, tags=[])
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {"error": "vector_store_unavailable", "message": "Vector store is not available."}
        tags = vector_store.get_article_tags(article_id)
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
    if not is_vector_store_enabled():
        return _vector_store_disabled_result(
            topics=[],
            limit=limit,
            sample_size=sample_size,
            hours=hours,
        )
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {"error": "vector_store_unavailable", "message": "Vector store is not available."}
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


def _handle_delete_article(msg: dict) -> dict:
    article_id = msg.get("article_id")
    if not article_id:
        return {"error": "no_article_id", "message": "Article ID is required"}

    logger.info("Handling delete_article: article_id=%r", article_id)
    if not is_vector_store_enabled():
        return _vector_store_disabled_error("delete article embeddings")
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {"error": "vector_store_unavailable", "message": "Vector store is not available."}
        success = vector_store.delete_article(article_id)
        return {"article_id": article_id, "success": success}
    except Exception as exc:
        logger.error("Delete article error: %s", exc)
        return {"error": "delete_failed", "message": str(exc)}


def _handle_clear_vector_store(_: dict) -> dict:
    logger.info("Handling clear_vector_store")
    if not is_vector_store_enabled():
        return _vector_store_disabled_error("clear the vector store")
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {"error": "vector_store_unavailable", "message": "Vector store is not available."}
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


def _handle_export_articles(msg: dict) -> dict:
    output_file = msg.get("output_file")
    if not output_file:
        return {"error": "no_output_file", "message": "Output file is required"}

    return export_articles(
        limit=int(msg.get("limit", PROJ_CONFIG["limit"])),
        output_file=output_file,
        stream_id=msg.get("stream_id"),
    )


def _handle_run_analysis(msg: dict) -> dict:
    return analyze_articles(
        input_file=msg.get("input_file", PROJ_CONFIG["input_file"]),
        limit=int(msg.get("limit", PROJ_CONFIG["limit"])),
        mark_read=_coerce_bool(msg.get("mark_read"), PROJ_CONFIG["mark_read"]),
        refresh=_coerce_bool(msg.get("refresh"), PROJ_CONFIG["refresh"]),
        stream_id=msg.get("stream_id"),
        threads=msg.get("threads"),
    )


def _handle_generate_summary(msg: dict) -> dict:
    articles = msg.get("articles")
    if articles is not None:
        return generate_summary_report(articles)

    input_file = msg.get("input_file", LATEST_ANALYZED_FILE)
    return regenerate_summary(input_file=input_file)


def _handle_generate_daily_digest(msg: dict) -> dict:
    return generate_daily_digest(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        hours=int(msg.get("hours", 24)),
        top_n=int(msg.get("top_n", 10)),
    )


def _handle_run_filters(msg: dict) -> dict:
    return run_filter_workflow(
        mode=msg.get("mode", "all"),
        limit=int(msg.get("limit", 1000)),
        threshold=float(msg.get("threshold", 3.0)),
        dry_run=_coerce_bool(msg.get("dry_run"), False),
        mark_read=_coerce_bool(msg.get("mark_read"), PROJ_CONFIG["mark_read"]),
        stream_id=msg.get("stream_id"),
    )


def _handle_process_stream(msg: dict) -> dict:
    return process_stream(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        days=int(msg.get("days", 3)),
        limit=int(msg.get("limit", 500)),
        strategy=msg.get("strategy"),
        export_markdown=_coerce_bool(msg.get("export_markdown"), False),
    )


def _handle_mark_stream_low_priority_read(msg: dict) -> dict:
    return mark_stream_low_priority_read(
        msg.get("article_ids") or [],
        dry_run=_coerce_bool(msg.get("dry_run"), False),
    )


def rebuild_vector_store() -> dict:
    if not is_vector_store_enabled():
        return _vector_store_disabled_error("rebuild the vector store")

    vector_store = get_vector_store()
    if not vector_store or not vector_store.collection:
        return {
            "error": "vector_store_unavailable",
            "message": "Vector store is not available in the current runtime.",
        }

    cached_items = iter_cached_scores()
    resume_enabled = os.getenv("RSS_VECTOR_REBUILD_RESUME", "").lower() in (
        "1",
        "true",
        "yes",
    )
    existing_ids: set[str] = set()

    if resume_enabled:
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
    default_concurrency = "100" if getattr(vector_store, "backend", "embedded") == "http" else "4"
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(vector_store.add_articles, batch) for batch in batches]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            rebuilt_count += result.get("success_count", 0)
            failed_ids.extend(result.get("failed_ids", []))

    remaining_count = vector_store.get_article_count()
    return {
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
            f"Rebuilt={rebuilt_count}, skipped={skipped_count}, failed={len(failed_ids)}. "
            f"batch_size={batch_size}, concurrency={concurrency}, resume={resume_enabled}."
        ),
    }


def _handle_get_vector_store_stats(_: dict) -> dict:
    logger.info("Handling get_vector_store_stats")
    if not is_vector_store_enabled():
        return _vector_store_disabled_result(
            article_count=0,
            sample_ids=[],
            has_data=False,
        )
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {"error": "vector_store_unavailable", "message": "Vector store is not available."}
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


def _handle_rebuild_vector_store(_: dict) -> dict:
    logger.info("Handling rebuild_vector_store")
    try:
        return rebuild_vector_store()
    except Exception as exc:
        logger.error("Rebuild vector store error: %s", exc)
        return {"error": "rebuild_failed", "message": str(exc)}


def _handle_cleanup_invalid_entries(_: dict) -> dict:
    logger.info("Handling cleanup_invalid_entries")
    if not is_vector_store_enabled():
        return _vector_store_disabled_error("clean up invalid vector entries")
    try:
        vector_store = get_vector_store()
        if not vector_store:
            return {"error": "vector_store_unavailable", "message": "Vector store is not available."}
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
    if msg_type == "export_articles":
        return _handle_export_articles(msg)
    if msg_type == "run_analysis":
        return _handle_run_analysis(msg)
    if msg_type == "generate_summary":
        return _handle_generate_summary(msg)
    if msg_type == "generate_daily_digest":
        return _handle_generate_daily_digest(msg)
    if msg_type == "run_filters":
        return _handle_run_filters(msg)
    if msg_type == "process_stream":
        return _handle_process_stream(msg)
    if msg_type == "analyze_article":
        return _handle_analyze_article(msg)
    if msg_type == "summarize_article":
        return _handle_summarize_article(msg)
    if msg_type == "mark_stream_low_priority_read":
        return _handle_mark_stream_low_priority_read(msg)
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
    if msg_type == "rebuild_vector_store":
        return _handle_rebuild_vector_store(msg)
    if msg_type == "cleanup_invalid_entries":
        return _handle_cleanup_invalid_entries(msg)
    if msg_type == "health":
        return _handle_health(msg)
    return {"error": "unknown_type"}
