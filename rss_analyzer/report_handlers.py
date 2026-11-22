"""Message and SSE handlers for reports, digests, and exports."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from rss_analyzer.config import LATEST_ANALYZED_FILE, OUTPUT_DIR, PROJ_CONFIG
from rss_analyzer.report_service import (
    export_articles,
    generate_daily_digest,
    generate_summary_report,
    regenerate_summary,
)


ProgressCallback = Callable[[dict], None]
MessageHandler = Callable[[dict], dict]
StreamHandler = Callable[[dict, ProgressCallback], dict]
EXPORT_OUTPUT_DIR: str | Path = OUTPUT_DIR


def _coerce_int(value, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_confined_output_file(output_file: object) -> Path | None:
    if not isinstance(output_file, str) or not output_file.strip():
        return None
    try:
        allowed_dir = Path(EXPORT_OUTPUT_DIR).resolve()
        candidate = Path(output_file).resolve()
    except (TypeError, ValueError, OSError):
        return None
    if candidate == allowed_dir or not candidate.is_relative_to(allowed_dir):
        return None
    return candidate


def handle_export_articles(msg: dict) -> dict:
    output_file = msg.get("output_file")
    if not output_file:
        return {"error": "no_output_file", "message": "Output file is required"}
    resolved_output = _resolve_confined_output_file(output_file)
    if resolved_output is None:
        return {
            "error": "invalid_output_file",
            "message": f"Output file must be inside {EXPORT_OUTPUT_DIR}",
        }
    return export_articles(
        limit=_coerce_int(msg.get("limit"), PROJ_CONFIG["limit"]),
        output_file=str(resolved_output),
        stream_id=msg.get("stream_id"),
    )


def handle_generate_summary(msg: dict) -> dict:
    articles = msg.get("articles")
    if articles is not None:
        return generate_summary_report(articles)
    return regenerate_summary(
        input_file=msg.get("input_file") or LATEST_ANALYZED_FILE
    )


def handle_generate_daily_digest(msg: dict) -> dict:
    return generate_daily_digest(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        hours=_coerce_int(msg.get("hours"), 24),
        top_n=_coerce_int(msg.get("top_n"), 10),
    )


def stream_generate_daily_digest(
    msg: dict,
    progress_callback: ProgressCallback,
) -> dict:
    return generate_daily_digest(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        hours=_coerce_int(msg.get("hours"), 24),
        top_n=_coerce_int(msg.get("top_n"), 10),
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
