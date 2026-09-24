"""Stable backend dispatcher and compatibility facade for local clients."""

from __future__ import annotations

from typing import Callable

from rss_analyzer.analysis_handlers import ANALYSIS_MESSAGE_HANDLERS
from rss_analyzer.cache import get_vector_index_queue_stats
from rss_analyzer.feedly_handlers import FEEDLY_MESSAGE_HANDLERS, FEEDLY_STREAM_HANDLERS
from rss_analyzer.feedly_workflows import *  # noqa: F403
from rss_analyzer.feedly_workflows import (
    _build_batch_triage_prompt,
    _deep_analysis_log_step,
    _deep_analyze_digest_candidates,
    _parse_batch_triage_results,
    get_runtime_paths,
)
from rss_analyzer.report_handlers import REPORT_MESSAGE_HANDLERS, REPORT_STREAM_HANDLERS
from rss_analyzer.report_service import (
    export_articles,
    generate_daily_digest,
    generate_summary_report,
    regenerate_summary,
)
from rss_analyzer.vector_handlers import VECTOR_MESSAGE_HANDLERS, VECTOR_STREAM_HANDLERS
from rss_analyzer.vector_service import get_vector_store, rebuild_vector_store


ProgressCallback = Callable[[dict], None]
MessageHandler = Callable[[dict], dict]
StreamHandler = Callable[[dict, ProgressCallback], dict]


def _emit_progress(
    callback: ProgressCallback | None,
    event: str,
    **payload,
) -> None:
    if callback:
        callback({"event": event, **payload})


def _handle_health(_: dict) -> dict:
    return {
        "ok": True,
        "transport": "http",
        "service": "rss-backend",
        "vector_index_queue": get_vector_index_queue_stats(),
        **get_runtime_paths(),
    }


MESSAGE_HANDLERS: dict[str, MessageHandler] = {
    **ANALYSIS_MESSAGE_HANDLERS,
    **REPORT_MESSAGE_HANDLERS,
    **VECTOR_MESSAGE_HANDLERS,
    **FEEDLY_MESSAGE_HANDLERS,
    "health": _handle_health,
}

STREAM_HANDLERS: dict[str, StreamHandler] = {
    **REPORT_STREAM_HANDLERS,
    **VECTOR_STREAM_HANDLERS,
    **FEEDLY_STREAM_HANDLERS,
}


def handle_stream_message(msg: dict, progress_callback: ProgressCallback) -> dict:
    """Run a request in the current connection while emitting progress events."""
    msg_type = msg.get("type")
    handler = STREAM_HANDLERS.get(msg_type) if isinstance(msg_type, str) else None
    if handler:
        return handler(msg, progress_callback)

    _emit_progress(progress_callback, "phase", phase="executing")
    return handle_message(msg)


def handle_message(msg: dict) -> dict:
    msg_type = msg.get("type")
    handler = MESSAGE_HANDLERS.get(msg_type) if isinstance(msg_type, str) else None
    return handler(msg) if handler else {"error": "unknown_type"}
