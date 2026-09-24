"""Report generation, daily digest, and article export workflows."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from rss_analyzer.cache import iter_cached_scores
from rss_analyzer.config import LATEST_ANALYZED_FILE, LATEST_SUMMARY_FILE
from rss_analyzer.feedly_client import feedly_fetch_unread
from rss_analyzer.llm_analyzer import generate_overall_summary
from rss_analyzer.stream_strategy import save_stream_overview_markdown
from rss_analyzer.utils import load_articles, save_articles


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict], None]


def _emit_progress(
    callback: ProgressCallback | None,
    event: str,
    **payload,
) -> None:
    if callback:
        callback({"event": event, **payload})


def build_monthly_output_path(prefix: str, suffix: str) -> str:
    now = datetime.now()
    output_dir = Path("output") / now.strftime("%Y-%m")
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir / f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.{suffix}")


def generate_summary_report(articles: list[dict]) -> dict:
    logger.info("Generating overall summary for %s articles", len(articles))
    overall_summary = generate_overall_summary(articles)
    summary_file = build_monthly_output_path("summary", "md")

    with open(summary_file, "w", encoding="utf-8") as output:
        output.write(overall_summary)
    with open(LATEST_SUMMARY_FILE, "w", encoding="utf-8") as latest:
        latest.write(overall_summary)

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
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Generate a tiered digest from recently scored articles."""
    _emit_progress(progress_callback, "phase", phase="loading_cache")
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    for item in iter_cached_scores():
        updated = item.get("updated_at")
        if not updated:
            continue
        try:
            timestamp = (
                datetime.fromisoformat(updated) if isinstance(updated, str) else updated
            )
            if timestamp >= cutoff:
                recent.append(item)
        except (ValueError, TypeError):
            continue

    if not recent:
        result = {
            "success": True,
            "article_count": 0,
            "summary": f"最近 {hours} 小时内没有已评分的文章。",
            "markdown": "",
        }
        _emit_progress(progress_callback, "progress", phase="completed", current=0, total=0)
        return result

    recent.sort(key=lambda item: item.get("score", 0), reverse=True)
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
        lines.append(
            f"- [{title}]({url}) (score: {score:.1f})"
            if url
            else f"- {title} (score: {score:.1f})"
        )
        if summary:
            lines.append(f"  - {summary}")

    lines.extend(["", "## Skim"])
    for item in skim:
        data = item.get("data") or {}
        title = data.get("title", item.get("article_id", "Unknown"))
        url = data.get("url", "")
        score = item.get("score", 0)
        lines.append(
            f"- [{title}]({url}) (score: {score:.1f})"
            if url
            else f"- {title} (score: {score:.1f})"
        )

    markdown = "\n".join(lines) + "\n"
    output_file = save_stream_overview_markdown(
        markdown,
        stream_label=stream_label or "daily-digest",
        strategy="daily_digest",
    )
    result = {
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
    _emit_progress(
        progress_callback,
        "progress",
        phase="completed",
        current=len(recent),
        total=len(recent),
    )
    return result


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
