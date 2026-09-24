"""Configuration parsing and data helpers for the Feedly TUI."""

from __future__ import annotations

import os
from pathlib import Path

from rss_analyzer.feedly_client import (
    feedly_get_categories,
    feedly_get_subscriptions,
)


def resolve_export_path(filename: str) -> str:
    path = Path(filename)
    if not path.parent or str(path.parent) == ".":
        path = Path("output") / path.name
    return str(path)


def format_limit_display(limit: int | None) -> str:
    if limit is None or limit <= 0:
        return "All (全量)"
    return str(limit)


def get_cleanup_defaults() -> tuple[int, float, bool]:
    limit_str = os.getenv("CLEANUP_DEFAULT_LIMIT")
    if limit_str is not None and limit_str != "":
        value = limit_str.strip().lower()
        if value in ("all", "0", "full", "none", "inf"):
            default_limit = 0
        else:
            try:
                default_limit = int(value)
            except ValueError:
                default_limit = 0
    else:
        default_limit = 0

    threshold_str = os.getenv("CLEANUP_DEFAULT_THRESHOLD")
    if threshold_str:
        try:
            default_threshold = float(threshold_str)
        except ValueError:
            default_threshold = 3.0
    else:
        default_threshold = 3.0

    mark_read_value = os.getenv("CLEANUP_DEFAULT_MARK_READ")
    if mark_read_value is not None:
        default_mark_read = mark_read_value.strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    else:
        default_mark_read = True

    return default_limit, default_threshold, default_mark_read


def get_review_defaults() -> tuple[int, int, int]:
    """Return review limit, recent-day window, and batch chunk size."""
    limit_str = os.getenv("REVIEW_DEFAULT_LIMIT")
    if limit_str is not None and limit_str != "":
        value = limit_str.strip().lower()
        if value in ("all", "0", "full", "none", "inf"):
            default_limit = 0
        else:
            try:
                default_limit = int(value)
            except ValueError:
                default_limit = 500
    else:
        default_limit = 500

    days_str = os.getenv("REVIEW_DEFAULT_DAYS")
    if days_str is not None and days_str != "":
        try:
            default_days = int(days_str)
        except ValueError:
            default_days = 3
    else:
        default_days = 3

    chunk_str = os.getenv("REVIEW_DEFAULT_CHUNK_SIZE")
    if chunk_str is not None and chunk_str != "":
        try:
            default_chunk = int(chunk_str)
        except ValueError:
            default_chunk = 50
    else:
        default_chunk = 50

    return default_limit, default_days, default_chunk


def resolve_stream_feed_titles(
    stream_id,
    categories=None,
    subscriptions=None,
):
    if not stream_id:
        return None

    if categories is None:
        categories = feedly_get_categories()
    if subscriptions is None:
        subscriptions = feedly_get_subscriptions()

    if not categories or not subscriptions:
        return None

    category_ids = {category.get("id") for category in categories}
    if stream_id in category_ids:
        matched_titles = []
        for subscription in subscriptions:
            subscription_categories = subscription.get("categories", [])
            if any(
                category.get("id") == stream_id
                for category in subscription_categories
            ):
                title = subscription.get("title")
                if title:
                    matched_titles.append(title)
        return matched_titles

    for subscription in subscriptions:
        if subscription.get("id") == stream_id:
            title = subscription.get("title")
            return [title] if title else []

    return None


def filter_articles_by_titles(articles, titles):
    if titles is None:
        return articles
    if not titles:
        return []

    title_set = set(titles)
    return [article for article in articles if article.get("origin") in title_set]


def import_error_hint(modname: str, err: Exception) -> str:
    return (
        f"Failed to import '{modname}': {err}\n\n"
        "Common causes:\n"
        "- You upgraded Python (e.g. 3.13 → 3.14) and binary wheels "
        "(pydantic-core / jiter) no longer match.\n"
        "- Your environment has dependency conflicts (e.g. langchain-openai "
        "requires openai<2.0.0 but openai 2.x is installed).\n\n"
        "Recommended fix (clean venv):\n"
        "  python -m venv .venv\n"
        "  .venv\\Scripts\\activate\n"
        "  python -m pip install -U pip\n"
        "  python -m pip install -r requirements.txt\n\n"
        "If you use langchain-openai, pin OpenAI SDK to 1.x:\n"
        '  python -m pip install "openai>=1.86.0,<2.0.0"\n\n'
        "Diagnostics to paste:\n"
        "  python -V\n"
        '  python -c "import platform; print(platform.architecture()); '
        'print(platform.python_version())"\n'
        '  python -c "import sys; print(sys.executable)"\n'
        "  python -m pip -V\n"
        "  python -m pip show pydantic-core pydantic openai jiter "
        "langchain-openai\n"
    )
