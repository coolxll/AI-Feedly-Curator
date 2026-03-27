#!/usr/bin/env python3
"""
Feedly article filter CLI.

This module keeps the legacy CLI surface while delegating the workflow to the
shared backend service layer.
"""

import argparse
import logging
import os
import sys

from rss_analyzer.backend_service import (
    FEED_ID_36KR,
    fetch_filter_articles as fetch_articles,
    low_score_filter,
    newsflash_filter,
    run_filter_pipeline as run_filters,
    run_filter_workflow,
)
from rss_analyzer.config import PROJ_CONFIG, setup_logging

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Feedly article filter")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--limit", "-l", type=int, default=1000, help="Article limit")
    parser.add_argument(
        "--threshold", "-t", type=float, default=3.0, help="Low-score threshold"
    )
    parser.add_argument("--dry-run", "-n", action="store_true", help="Dry-run mode")
    parser.add_argument("--stream-id", help="Target Feedly stream ID")
    parser.add_argument(
        "--mark-read",
        action="store_true",
        default=PROJ_CONFIG["mark_read"],
        help=f"Mark articles as read (default: {PROJ_CONFIG['mark_read']})",
    )

    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("newsflash", help="Filter newsflashes")
    sub.add_parser("low-score", help="Filter low-score articles")
    sub.add_parser("all", help="Run all filters")

    args = parser.parse_args()

    if args.debug:
        setup_logging(True)
    else:
        env_level = os.environ.get("RSS_NATIVE_LOG_LEVEL", "INFO").upper()
        setup_logging(env_level == "DEBUG")

    if not args.cmd:
        args.cmd = "all"

    result = run_filter_workflow(
        mode=args.cmd,
        limit=args.limit,
        threshold=args.threshold,
        dry_run=args.dry_run,
        mark_read=args.mark_read,
        stream_id=args.stream_id,
    )
    if result.get("error"):
        logger.error(result["message"])
        return 1

    if result["article_count"] == 0:
        logger.info("No unread articles found")
        return 0

    logger.info(
        "Filter run complete: filtered=%s remaining=%s",
        result["filtered_count"],
        result["remaining_count"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
