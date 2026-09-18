#!/usr/bin/env python3
"""Mark confirmed Feedly entry IDs as read through the canonical client."""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def load_articles(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def report_urls(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {normalize_url(url) for url in re.findall(r"\]\((https?://[^)]+)\)", text)}


def normalize_url(url: str) -> str:
    cleaned = (url or "").split("#")[0]
    cleaned = re.sub(r"(https://www\.tmtpost\.com/\d+)(?:\.html)?$", r"\1", cleaned)
    return cleaned


def normalize_decision(decision: str | None) -> str:
    value = (decision or "").strip().lower()
    return {
        "low_quality": "clear",
        "noise": "clear",
        "optional": "skim",
        "strong_recommend": "must_read",
    }.get(value, value)


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def require_confirmation(confirm: str | None, dry_run: bool) -> bool:
    if dry_run:
        return True
    if confirm == "MARK_READ":
        return True
    print("Refusing to mark read without --confirm MARK_READ. Use --dry-run to inspect.", file=sys.stderr)
    return False


def mark_ids(ids: list[str], *, batch_size: int, dry_run: bool) -> int:
    cleaned = [item for item in dict.fromkeys(ids) if item]
    print(f"Entry IDs selected: {len(cleaned)}")
    if dry_run:
        for item in cleaned[:20]:
            print(item)
        if len(cleaned) > 20:
            print(f"... {len(cleaned) - 20} more")
        return 0

    from rss_analyzer.feedly_client import feedly_mark_read

    for batch in chunked(cleaned, batch_size):
        if not feedly_mark_read(batch):
            print(f"Failed to mark batch of {len(batch)} entries", file=sys.stderr)
            return 1
    return 0


def cmd_ids(args: argparse.Namespace) -> int:
    ids = args.ids
    if args.ids_file:
        ids.extend(
            line.strip()
            for line in Path(args.ids_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return mark_ids(ids, batch_size=args.batch_size, dry_run=args.dry_run)


def cmd_sources(args: argparse.Namespace) -> int:
    articles = load_articles(Path(args.data))
    sources = [source.strip() for source in args.sources.split(",") if source.strip()]
    ids = [
        item.get("id", "")
        for item in articles
        if any(source in (item.get("origin", "") or "") for source in sources)
    ]
    return mark_ids(ids, batch_size=args.batch_size, dry_run=args.dry_run)


def cmd_unselected(args: argparse.Namespace) -> int:
    articles = load_articles(Path(args.data))
    selected_urls = report_urls(Path(args.report))
    ids = [
        item.get("id", "")
        for item in articles
        if normalize_url(item.get("link", "")) not in selected_urls
    ]
    return mark_ids(ids, batch_size=args.batch_size, dry_run=args.dry_run)


def cmd_clear(args: argparse.Namespace) -> int:
    ids: list[str] = []
    for pattern in [args.report_glob, args.deep_report_glob]:
        for path in sorted(glob.glob(pattern)):
            for item in load_articles(Path(path)):
                if normalize_decision(item.get("decision")) == "clear":
                    ids.append(item.get("id", ""))
    if args.low_quality and Path(args.low_quality).exists():
        ids.extend(item.get("id", "") for item in load_articles(Path(args.low_quality)))
    return mark_ids(ids, batch_size=args.batch_size, dry_run=args.dry_run)


def cmd_all_processed(args: argparse.Namespace) -> int:
    articles = load_articles(Path(args.data))
    ids = [item.get("id", "") for item in articles]
    return mark_ids(ids, batch_size=args.batch_size, dry_run=args.dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", help="Must equal MARK_READ for non-dry-run execution")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    sub = parser.add_subparsers(dest="command", required=True)

    ids_parser = sub.add_parser("ids", help="mark explicit entry IDs")
    ids_parser.add_argument("ids", nargs="*")
    ids_parser.add_argument("--ids-file")
    ids_parser.set_defaults(func=cmd_ids)

    source_parser = sub.add_parser("sources", help="mark entries from comma-separated source names")
    source_parser.add_argument("--data", default="/tmp/feedly_articles.json")
    source_parser.add_argument("--sources", required=True)
    source_parser.set_defaults(func=cmd_sources)

    unselected_parser = sub.add_parser("unselected", help="mark packet entries not linked in final report")
    unselected_parser.add_argument("--report", default="/tmp/feedly_final_report.md")
    unselected_parser.add_argument("--data", default="/tmp/feedly_articles.json")
    unselected_parser.set_defaults(func=cmd_unselected)

    clear_parser = sub.add_parser("clear", help="mark entries classified as clear")
    clear_parser.add_argument("--report-glob", default="/tmp/fb_report_*.json")
    clear_parser.add_argument("--deep-report-glob", default="/tmp/fb_deep_report_*.json")
    clear_parser.add_argument("--low-quality", default="/tmp/feedly_prefiltered_low_quality.json")
    clear_parser.set_defaults(func=cmd_clear)

    all_parser = sub.add_parser("all-processed", help="mark every entry in a normalized packet")
    all_parser.add_argument("--data", default="/tmp/feedly_articles.json")
    all_parser.set_defaults(func=cmd_all_processed)

    args = parser.parse_args()
    if not require_confirmation(args.confirm, args.dry_run):
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
