#!/usr/bin/env python3
"""Fix known Feedly report link corruption after report merge."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def clean_title(title: str) -> str:
    return re.sub(r"^\[.+?\]\s*", "", title or "").strip()


def load_maps(data_path: Path) -> tuple[dict[str, str], set[str]]:
    articles = json.loads(data_path.read_text(encoding="utf-8"))
    title_to_link: dict[str, str] = {}
    link_set: set[str] = set()
    for item in articles:
        title = item.get("title", "")
        link = (item.get("link", "") or "").split("#")[0]
        if not title or not link:
            continue
        title_to_link[clean_title(title)] = link
        title_to_link[title.strip()] = link
        link_set.add(link)
    return title_to_link, link_set


def fix_tmtpost(report: str) -> str:
    report = re.sub(r"(\.html)\d+\.html", r"\1", report)
    return re.sub(
        r"(https://www\.tmtpost\.com/\d+)(?:\.html)?(?=[?#/)]|$)",
        r"\1.html",
        report,
    )


def find_link_for_title(title: str, title_to_link: dict[str, str], domain_hint: str = "") -> str | None:
    cleaned = clean_title(title)
    if cleaned in title_to_link:
        candidate = title_to_link[cleaned]
        if not domain_hint or domain_hint in candidate:
            return candidate

    for length in (20, 15, 10, 8, 5):
        prefix = cleaned[:length]
        if len(prefix) < 2:
            continue
        for known_title, link in title_to_link.items():
            if domain_hint and domain_hint not in link:
                continue
            if prefix in known_title or known_title[:length] in cleaned:
                return link
    return None


def rewrite_markdown_links(report: str, title_to_link: dict[str, str]) -> tuple[str, int]:
    pattern = re.compile(r"^(\s*[-*]\s+\[)(.+?)(\]\((https?://[^)]+)\))$", re.MULTILINE)
    counts = Counter(re.findall(r"\]\((https?://[^)]+)\)", report))
    fixes = 0

    def replace(match: re.Match) -> str:
        nonlocal fixes
        prefix, title, suffix, url = match.groups()
        base_url = url.split("#")[0]
        domain_hint = ""
        if "v2ex.com" in base_url:
            domain_hint = "v2ex.com"
        elif "xueqiu.com/today" in base_url:
            domain_hint = "xueqiu.com"

        needs_fix = (
            domain_hint
            or counts[url] > 1
            or counts[base_url] > 1
            or "xueqiu.com/today" in base_url
        )
        if not needs_fix:
            return match.group(0)

        correct = find_link_for_title(title, title_to_link, domain_hint)
        if not correct or correct == base_url:
            return match.group(0)
        if "v2ex.com" in correct:
            correct += "#reply0"
        fixes += 1
        return f"{prefix}{title}]({correct})"

    return pattern.sub(replace, report), fixes


def fix_broken_markdown(report: str) -> tuple[str, int]:
    fixes = 0
    lines = report.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*[-*]\s+\[)(.+?)(\(https?://[^)]+\))$", line)
        if match and "]" not in line[: line.index("(")]:
            prefix, title, paren_url = match.groups()
            lines[index] = f"{prefix}{title}]{paren_url}"
            fixes += 1
    return "\n".join(lines), fixes


def remove_duplicate_source_lines(report: str) -> tuple[str, int]:
    seen = set()
    lines = []
    removed = 0
    for line in report.splitlines():
        match = re.match(r"^\s*[-*]\s+\[来源\]\((https?://[^)]+)\)$", line)
        if match:
            url = match.group(1)
            if url in seen:
                removed += 1
                continue
            seen.add(url)
        lines.append(line)
    return "\n".join(lines), removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="/tmp/feedly_final_report.md")
    parser.add_argument("--data", default="/tmp/feedly_articles.json")
    args = parser.parse_args()

    report_path = Path(args.report)
    data_path = Path(args.data)
    report = report_path.read_text(encoding="utf-8")
    title_to_link, link_set = load_maps(data_path)

    report = fix_tmtpost(report)
    report, link_fixes = rewrite_markdown_links(report, title_to_link)
    report, duplicate_fixes = remove_duplicate_source_lines(report)
    report, markdown_fixes = fix_broken_markdown(report)
    if not report.endswith("\n"):
        report += "\n"
    report_path.write_text(report, encoding="utf-8")

    links = re.findall(r"\]\((https?://[^)]+)\)", report)
    repeated = {url: count for url, count in Counter(links).items() if count > 1}
    unknown = {url.split("#")[0] for url in links} - link_set
    print(f"Fixed link mappings: {link_fixes}")
    print(f"Removed duplicate [来源] lines: {duplicate_fixes}")
    print(f"Fixed broken markdown links: {markdown_fixes}")
    print(f"Remaining repeated URLs: {len(repeated)}")
    print(f"Links not found in packet data: {len(unknown)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
