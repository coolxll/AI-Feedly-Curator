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

# Feedly domain workflows are exposed through the compatibility facade
# (`feedly_workflows`), which re-exports `process_stream` from
# `readflow_workflows`. Import it from there rather than from
# `filter_workflows` (which never defined it) to avoid duplicating the
# function or creating a reverse dependency.
from rss_analyzer.feedly_workflows import process_stream
from rss_analyzer.filter_workflows import (
    FEED_ID_36KR,
    fetch_filter_articles as fetch_articles,
    low_score_filter,
    newsflash_filter,
    run_filter_pipeline as run_filters,
    run_filter_workflow,
)
from rss_analyzer.feedly_client import FeedlyAuthError
from rss_analyzer.config import PROJ_CONFIG, setup_logging

logger = logging.getLogger(__name__)


def _add_common_options(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """Add the shared CLI options to *parser*.

    When ``suppress`` is true, every option uses ``default=SUPPRESS`` so that
    parsing leaves the attribute untouched unless the flag is actually passed.
    """
    def default(value):
        return argparse.SUPPRESS if suppress else value

    parser.add_argument("--debug", action="store_true", default=default(False))
    parser.add_argument(
        "--limit", "-l", type=int, default=default(1000), help="Article limit"
    )
    parser.add_argument(
        "--threshold", "-t", type=float, default=default(3.0),
        help="Low-score threshold",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true", default=default(False),
        help="Dry-run mode",
    )
    parser.add_argument(
        "--stream-id", default=default(None), help="Target Feedly stream ID"
    )
    parser.add_argument(
        "--mark-read",
        action="store_true",
        default=default(PROJ_CONFIG["mark_read"]),
        help=f"Mark articles as read (default: {PROJ_CONFIG['mark_read']})",
    )
    parser.add_argument(
        "--days", type=int, default=default(3),
        help="Recent day window for process-stream",
    )
    parser.add_argument(
        "--stream-label", default=default(None),
        help="Optional display label for process-stream",
    )
    parser.add_argument(
        "--no-incremental-mark",
        dest="incremental_mark",
        action="store_false",
        default=default(PROJ_CONFIG.get("incremental_mark", True)),
        help="Disable progressive/incremental mark-as-read during scoring",
    )
    parser.add_argument(
        "--mark-batch-size",
        type=int,
        default=default(int(PROJ_CONFIG.get("filter_mark_batch_size", 20))),
        help="Batch size for progressive mark-as-read (default: 20)",
    )
    parser.add_argument(
        "--export-markdown",
        action="store_true",
        default=default(False),
        help="Persist process-stream overview markdown",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    Global options may be given either before or after the subcommand, e.g.
    both ``feedly_filter.py --limit 5 newsflash`` and
    ``feedly_filter.py newsflash --limit 5`` work.

    This uses two copies of the shared options: the top-level parser carries
    the real defaults, while each subparser gets a copy with
    ``default=SUPPRESS``. Without the suppression argparse would re-apply the
    subparser's defaults *after* parsing and silently clobber values supplied
    before the subcommand.
    """
    parser = argparse.ArgumentParser(description="Feedly article filter")
    _add_common_options(parser, suppress=False)

    sub = parser.add_subparsers(dest="cmd")
    for name, help_text in (
        ("newsflash", "Filter newsflashes"),
        ("low-score", "Filter low-score articles"),
        ("all", "Run all filters"),
        ("process-stream", "Run stream strategy overview"),
    ):
        sub_parser = sub.add_parser(name, help=help_text)
        _add_common_options(sub_parser, suppress=True)
    return parser


def main(argv: list[str] | None = None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.debug:
        setup_logging(True)
    else:
        env_level = os.environ.get("RSS_NATIVE_LOG_LEVEL", "INFO").upper()
        setup_logging(env_level == "DEBUG")

    if not args.cmd:
        args.cmd = "all"

    # Auth failures are a user-actionable condition, not a crash: report them
    # with a clear message and a non-zero exit code instead of a traceback.
    try:
        if args.cmd == "process-stream":
            result = process_stream(
                stream_id=args.stream_id,
                stream_label=args.stream_label,
                days=args.days,
                limit=args.limit,
                export_markdown=args.export_markdown,
            )
            logger.info("Strategy: %s", result["strategy"])
            logger.info(result["summary"])
            logger.info("Worth expanding: %s", len(result["worth_expanding_items"]))
            logger.info(
                "Quick clear candidates: %s", len(result["mark_read_candidates"])
            )
            if result.get("overview_file"):
                logger.info("Saved overview to %s", result["overview_file"])
            return 0

        result = run_filter_workflow(
            mode=args.cmd,
            limit=args.limit,
            threshold=args.threshold,
            dry_run=args.dry_run,
            mark_read=args.mark_read,
            stream_id=args.stream_id,
            incremental_mark=args.incremental_mark,
            mark_batch_size=args.mark_batch_size,
        )
    except FeedlyAuthError as exc:
        # The exception message is already complete and actionable.
        logger.error("%s", exc)
        return 1
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
