#!/usr/bin/env python3
"""
Arena entrypoint placeholder for scoring backtests.
"""

from pathlib import Path


def main() -> int:
    print(
        "Scoring arena is initialized. "
        "Next step: migrate or wrap scripts/backtest_scoring.py here."
    )
    print(f"Workspace: {Path.cwd()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
