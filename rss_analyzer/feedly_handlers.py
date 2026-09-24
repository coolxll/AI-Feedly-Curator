"""Message and SSE adapters for Feedly workflow operations."""

from __future__ import annotations

from typing import Callable

from rss_analyzer.config import PROJ_CONFIG
from rss_analyzer.feedly_workflows import (
    analyze_articles,
)
from rss_analyzer.filter_workflows import run_filter_workflow
from rss_analyzer.readflow_workflows import (
    mark_stream_low_priority_read,
    process_stream,
)


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


def handle_run_analysis(msg: dict) -> dict:
    return analyze_articles(
        input_file=msg.get("input_file", PROJ_CONFIG["input_file"]),
        limit=int(msg.get("limit", PROJ_CONFIG["limit"])),
        mark_read=_coerce_bool(msg.get("mark_read"), PROJ_CONFIG["mark_read"]),
        refresh=_coerce_bool(msg.get("refresh"), PROJ_CONFIG["refresh"]),
        stream_id=msg.get("stream_id"),
        threads=msg.get("threads"),
    )


def handle_run_filters(msg: dict) -> dict:
    kwargs = {
        "mode": msg.get("mode", "all"),
        "limit": int(msg.get("limit", 1000)),
        "threshold": float(msg.get("threshold", 3.0)),
        "dry_run": _coerce_bool(msg.get("dry_run"), False),
        "mark_read": _coerce_bool(msg.get("mark_read"), PROJ_CONFIG["mark_read"]),
        "stream_id": msg.get("stream_id"),
    }
    if "incremental_mark" in msg:
        kwargs["incremental_mark"] = _coerce_bool(msg["incremental_mark"], True)
    if "mark_batch_size" in msg and msg["mark_batch_size"] is not None:
        kwargs["mark_batch_size"] = int(msg["mark_batch_size"])
    return run_filter_workflow(**kwargs)


def handle_process_stream(msg: dict) -> dict:
    return process_stream(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        days=int(msg.get("days", 3)),
        limit=int(msg.get("limit", 500)),
        strategy=msg.get("strategy"),
        export_markdown=_coerce_bool(msg.get("export_markdown"), False),
    )


def handle_mark_stream_low_priority_read(msg: dict) -> dict:
    return mark_stream_low_priority_read(
        msg.get("article_ids") or [],
        dry_run=_coerce_bool(msg.get("dry_run"), False),
    )


def stream_run_analysis(msg: dict, progress_callback: ProgressCallback) -> dict:
    return analyze_articles(
        input_file=msg.get("input_file", PROJ_CONFIG["input_file"]),
        limit=int(msg.get("limit", PROJ_CONFIG["limit"])),
        mark_read=_coerce_bool(msg.get("mark_read"), PROJ_CONFIG["mark_read"]),
        refresh=_coerce_bool(msg.get("refresh"), PROJ_CONFIG["refresh"]),
        stream_id=msg.get("stream_id"),
        threads=msg.get("threads"),
        progress_callback=progress_callback,
    )


def stream_process_stream(msg: dict, progress_callback: ProgressCallback) -> dict:
    return process_stream(
        stream_id=msg.get("stream_id"),
        stream_label=msg.get("stream_label"),
        days=int(msg.get("days", 3)),
        limit=int(msg.get("limit", 500)),
        strategy=msg.get("strategy"),
        export_markdown=_coerce_bool(msg.get("export_markdown"), False),
        progress_callback=progress_callback,
    )


FEEDLY_MESSAGE_HANDLERS: dict[str, MessageHandler] = {
    "run_analysis": handle_run_analysis,
    "run_filters": handle_run_filters,
    "process_stream": handle_process_stream,
    "mark_stream_low_priority_read": handle_mark_stream_low_priority_read,
}

FEEDLY_STREAM_HANDLERS: dict[str, StreamHandler] = {
    "run_analysis": stream_run_analysis,
    "process_stream": stream_process_stream,
}
