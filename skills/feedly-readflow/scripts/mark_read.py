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


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_EXCLUDED_HEADING_RE = re.compile(
    r"(?:低质量|可清理|已过滤|预过滤|"
    r"^(?:clear|prefiltered?|low[\s_-]*quality|filtered|noise)"
    r"(?:\s*[/(\-–—:].*|\s+(?:items?|articles?|samples?|entries?|sections?|low[\s_-]*quality))?$)",
    re.IGNORECASE,
)


def _filter_selected_sections(text: str) -> str:
    kept_lines: list[str] = []
    excluded_level: int | None = None
    for line in text.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            if excluded_level is not None and level <= excluded_level:
                excluded_level = None
            if excluded_level is None and _EXCLUDED_HEADING_RE.search(heading_text):
                excluded_level = level
                continue
        if excluded_level is None:
            kept_lines.append(line)
    return "\n".join(kept_lines)


def extract_markdown_urls(text: str) -> list[str]:
    """Extract http(s) URLs from Markdown links, preserving balanced parentheses."""
    urls: list[str] = []
    pos = 0
    length = len(text)
    while True:
        start = text.find("](", pos)
        if start == -1:
            break
        url_start = start + 2
        if not (text.startswith("http://", url_start) or text.startswith("https://", url_start)):
            pos = url_start
            continue
        depth = 0
        i = url_start
        while i < length:
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            elif ch in " \t" and depth == 0:
                break
            elif ch in "\r\n":
                break
            i += 1
        if i < length and text[i] in (")", " ", "\t"):
            urls.append(text[url_start:i])
            pos = i + 1
        else:
            pos = i
    return urls


def report_urls(path: Path) -> set[str]:
    text = _filter_selected_sections(path.read_text(encoding="utf-8"))
    return {normalize_url(url) for url in extract_markdown_urls(text)}


def normalize_url(url: str) -> str:
    cleaned = (url or "").split("#")[0]
    cleaned = re.sub(r"(\.html)\d+\.html", r"\1", cleaned)
    cleaned = re.sub(r"(https://www\.tmtpost\.com/\d+)(?:\.html)?(?=[?#/]|$)", r"\1", cleaned)
    return cleaned


def normalize_decision(decision: str | None) -> str:
    value = (decision or "").strip().lower()
    return {
        "low_quality": "clear",
        "noise": "clear",
        "optional": "skim",
        "recommend": "must_read",
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

    from rss_analyzer.feedly_client import FeedlyAuthError, feedly_mark_read

    for batch in chunked(cleaned, batch_size):
        try:
            ok = feedly_mark_read(batch)
        except FeedlyAuthError as exc:
            print(f"Feedly 认证失败: {exc}", file=sys.stderr)
            print(
                "请运行以下命令重新授权: uv run python feedly_token.py init",
                file=sys.stderr,
            )
            return 1
        if not ok:
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


def _score(item: dict) -> float:
    value = item.get("score")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _load_report_by_id(pattern: str) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for path in sorted(glob.glob(pattern)):
        for item in load_articles(Path(path)):
            if not isinstance(item, dict):
                continue
            entry_id = item.get("id", "")
            if not entry_id:
                continue
            existing = by_id.get(entry_id)
            if existing is None or _score(item) > _score(existing):
                by_id[entry_id] = dict(item)
    return by_id


def cmd_clear(args: argparse.Namespace) -> int:
    by_id = _load_report_by_id(args.report_glob)
    deep_by_id = _load_report_by_id(args.deep_report_glob)
    for entry_id, item in deep_by_id.items():
        merged = dict(by_id.get(entry_id, {}))
        merged.update(item)
        by_id[entry_id] = merged

    ids: list[str] = [
        entry_id
        for entry_id, item in by_id.items()
        if normalize_decision(item.get("decision")) == "clear"
    ]
    if args.low_quality and Path(args.low_quality).exists():
        for item in load_articles(Path(args.low_quality)):
            entry_id = item.get("id", "")
            if entry_id and (
                entry_id not in by_id
                or normalize_decision(by_id[entry_id].get("decision")) == "clear"
            ):
                ids.append(entry_id)
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
