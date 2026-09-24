"""Message and SSE handlers for reports, digests, and exports."""

from __future__ import annotations

from typing import Callable

from rss_analyzer.config import LATEST_ANALYZED_FILE, PROJ_CONFIG
from rss_analyzer.report_service import (
    export_articles,
    generate_daily_digest,
    generate_summary_report,
    regenerate_summary,
)


ProgressCallback = Callable[[dict], None]
MessageHandler = Callable[[dict], dict]
StreamHandler = Callable[[dict, ProgressCallback], dict]


def handle_export_articles(msg: dict) -> dict:
    output_file = msg.get("output_file")
    if not output_file:
        return {"error": "no_output_file", "message": "Output file is required"}
    return export_articles(
        limit=int(msg.get("limit", PROJ_CONFIG["limit"])),
        output_file=output_file,
        stream_id=msg.get("stream_id"),
    )


def handle_generate_summary(msg: dict) -> dict:
    articles = msg.get("articles")
    if articles is not None:
        return generate_summary_report(articles)
    return regenerate_summary(
        input_file=msg.get("input_file", LATEST_ANALYZED_FILE)
    )


def handle_generate_daily_digest(msg: dict) -> dict:
    return generate_daily_digest(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        hours=int(msg.get("hours", 24)),
        top_n=int(msg.get("top_n", 10)),
    )


def stream_generate_daily_digest(
    msg: dict,
    progress_callback: ProgressCallback,
) -> dict:
    return generate_daily_digest(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        hours=int(msg.get("hours", 24)),
        top_n=int(msg.get("top_n", 10)),
        progress_callback=progress_callback,
    )


REPORT_MESSAGE_HANDLERS: dict[str, MessageHandler] = {
    "export_articles": handle_export_articles,
    "generate_summary": handle_generate_summary,
    "generate_daily_digest": handle_generate_daily_digest,
}

REPORT_STREAM_HANDLERS: dict[str, StreamHandler] = {
    "generate_daily_digest": stream_generate_daily_digest,
}
