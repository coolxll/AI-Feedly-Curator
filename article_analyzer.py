#!/usr/bin/env python3
"""
AI-Feedly-Curator
Use AI to analyze RSS articles, score them, and generate a summary report.
"""

import argparse
import logging
import os

from rss_analyzer.backend_service import analyze_articles, export_articles
from rss_analyzer.config import PROJ_CONFIG, setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Article Analyzer")

    parser.add_argument(
        "--input",
        default=PROJ_CONFIG["input_file"],
        help=f"Input JSON file (default: {PROJ_CONFIG['input_file']})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=PROJ_CONFIG["limit"],
        help=f"Number of articles to process (default: {PROJ_CONFIG['limit']})",
    )
    parser.add_argument(
        "--mark-read",
        action="store_true",
        default=PROJ_CONFIG["mark_read"],
        help=f"Mark processed articles as read (default: {PROJ_CONFIG['mark_read']})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=PROJ_CONFIG["debug"],
        help=f"Enable debug mode (default: {PROJ_CONFIG['debug']})",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        default=PROJ_CONFIG["refresh"],
        help=f"Refresh from Feedly before processing (default: {PROJ_CONFIG['refresh']})",
    )
    parser.add_argument(
        "--stream-id", help="Feedly Stream ID to fetch from (Category/Feed)"
    )
    parser.add_argument(
        "--export", help="Export fetched articles to JSON file without analysis"
    )
    parser.add_argument(
        "--threads", type=int, help="Number of threads for concurrent batch scoring"
    )

    args = parser.parse_args()

    debug_mode = (
        args.debug
        or os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
        or os.getenv("RSS_NATIVE_LOG_LEVEL", "").upper() == "DEBUG"
    )
    setup_logging(debug_mode)

    if args.export:
        result = export_articles(
            limit=args.limit,
            output_file=args.export,
            stream_id=args.stream_id,
        )
        if result.get("error"):
            logger.error(result["message"])
            return

        logger.info("Exported %s articles to %s", result["article_count"], result["output_file"])
        return

    result = analyze_articles(
        input_file=args.input,
        limit=args.limit,
        mark_read=args.mark_read,
        refresh=args.refresh,
        stream_id=args.stream_id,
        threads=args.threads,
    )
    if result.get("error"):
        logger.error(result["message"])
        return

    logger.info("Analyzed %s articles", result["processed_count"])
    logger.info("Saved analysis to %s", result["analyzed_file"])
    logger.info("Saved summary to %s", result["summary_file"])


if __name__ == "__main__":
    main()
