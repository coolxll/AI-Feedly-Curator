#!/usr/bin/env python3
"""
Regenerate the overall summary from analyzed articles.
"""

import logging

from rss_analyzer.backend_service import generate_summary_report, regenerate_summary
from rss_analyzer.config import setup_logging

logger = logging.getLogger(__name__)


def generate_summary_from_articles(articles):
    result = generate_summary_report(articles)
    return result["summary_file"], result["latest_summary_file"]


def main():
    setup_logging()
    result = regenerate_summary()
    if result.get("error"):
        logger.error(result["message"])
        return

    logger.info("Loaded analyzed articles from %s", result["input_file"])
    logger.info("Saved summary to %s", result["summary_file"])
    logger.info("Saved latest summary to %s", result["latest_summary_file"])


if __name__ == "__main__":
    main()
