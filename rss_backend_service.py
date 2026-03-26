#!/usr/bin/env python3
"""
Run the local backend HTTP service used by the Chrome extension and local clients.
"""

from __future__ import annotations

import argparse
import logging

from rss_analyzer.backend_service import get_runtime_paths
from rss_analyzer.config import setup_logging
from rss_analyzer.http_service import create_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RSS backend HTTP service")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8765, help="Bind port")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.debug)

    runtime = get_runtime_paths()
    logging.info(
        "Starting RSS backend service on http://%s:%s (db=%s, vector=%s)",
        args.host,
        args.port,
        runtime["db_path"],
        runtime["vector_db_dir"],
    )
    server = create_server(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping RSS backend service")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
