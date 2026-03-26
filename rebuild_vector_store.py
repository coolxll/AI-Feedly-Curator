#!/usr/bin/env python3
"""
Rebuild the local Chroma vector store from cached article scores in SQLite.
"""

from __future__ import annotations

import sys

from rss_analyzer.backend_service import get_runtime_paths, rebuild_vector_store
from rss_analyzer.config import setup_logging


def main() -> int:
    setup_logging()

    runtime = get_runtime_paths()
    print("Rebuilding vector store...")
    print(f"  db: {runtime['db_path']}")
    print(f"  vector: {runtime['vector_db_dir']}")

    result = rebuild_vector_store()
    print(result.get("message", "No message returned."))

    if result.get("failed_count"):
        print(f"Failed IDs (sample): {result.get('failed_ids', [])}")

    if result.get("error"):
        return 1

    if result.get("failed_count", 0) > 0:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
