#!/usr/bin/env python3
"""Prepare normalized Feedly article packets for multi-agent readflow."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rss_analyzer.utils import is_newsflash, strip_html_tags


PROMO_TITLE_PATTERNS = [
    r"\[推广\]",
    r"\[酷工作\]",
    r"\[拼车\]",
    r"优惠券",
    r"邀请码",
    r"兑换码",
    r"机场",
    r"首充",
    r"免费试用",
    r"Netflix.*拼车",
    r"Claude.*拼车",
]

NO_FETCH_DOMAINS = {"jisilu.cn", "www.jisilu.cn"}


def _domain(link: str) -> str:
    host = urlparse(link or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _source(article: dict) -> str:
    origin = article.get("origin", "")
    if isinstance(origin, dict):
        return origin.get("title", "") or origin.get("streamId", "")
    return str(origin or "")


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", strip_html_tags(title or "")).strip().lower()


def _article_text(article: dict) -> tuple[str, str]:
    summary = strip_html_tags(article.get("summary", "") or "")
    content = strip_html_tags(article.get("content", "") or "")
    if not content:
        content = summary
    return summary, content


def _looks_promotional(title: str) -> bool:
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in PROMO_TITLE_PATTERNS)


def _is_jisilu(domain: str) -> bool:
    return domain == "jisilu.cn" or domain.endswith(".jisilu.cn")


def _should_fetch(article: dict, domain: str, content: str, min_chars: int) -> bool:
    if not article.get("link"):
        return False
    if _is_jisilu(domain) or domain in NO_FETCH_DOMAINS:
        return False
    if is_newsflash(article):
        return False
    return len(content) < min_chars


def _content_source(article: dict, domain: str, fetched: bool, content: str) -> str:
    if fetched:
        return "fetched"
    if _is_jisilu(domain):
        return "feedly_summary_limited"
    if article.get("content"):
        return "feedly_content"
    if content:
        return "feedly_summary"
    return "missing"


def normalize_articles(
    articles: list[dict], *, fetch_content: bool, min_chars: int
) -> tuple[list[dict], list[dict]]:
    normalized: list[dict] = []
    low_quality: list[dict] = []
    seen_titles: set[str] = set()

    for index, article in enumerate(articles):
        title = strip_html_tags(article.get("title", "") or "Untitled")
        link = article.get("link", "") or ""
        domain = _domain(link)
        origin = _source(article)
        summary, content = _article_text(article)
        flags: list[str] = []
        title_key = _normalize_title(title)

        if not title_key or title_key == "untitled":
            flags.append("empty_title")
        if title_key in seen_titles:
            flags.append("duplicate_title")
        seen_titles.add(title_key)
        if not link:
            flags.append("missing_link")
        if _looks_promotional(title):
            flags.append("promotional_title")
        if is_newsflash({**article, "link": link}):
            flags.append("newsflash")
        if _is_jisilu(domain):
            flags.append("jisilu_summary_only")

        fetched = False
        if fetch_content and _should_fetch({**article, "link": link}, domain, content, min_chars):
            from rss_analyzer.article_fetcher import fetch_article_content

            fetched_text = fetch_article_content(link)
            if fetched_text and not fetched_text.startswith(("获取失败", "请求异常", "处理异常", "内容提取为空")):
                content = strip_html_tags(fetched_text)
                fetched = True
            else:
                flags.append("fetch_failed")

        if len(content) < 120:
            flags.append("very_short_content")
        elif len(content) < min_chars:
            flags.append("short_summary")

        item = {
            "packet_index": index,
            "id": article.get("id", ""),
            "title": title,
            "link": link,
            "origin": origin,
            "domain": domain,
            "published": article.get("published", 0),
            "summary": summary,
            "content": content[:10000],
            "content_source": _content_source(article, domain, fetched, content),
            "quality_flags": flags,
        }

        hard_low = {
            "duplicate_title",
            "empty_title",
            "missing_link",
            "promotional_title",
        }
        v2ex_short = "v2ex.com" in domain and len(content) < 100
        if hard_low.intersection(flags) or v2ex_short:
            item["prefilter_decision"] = "low_quality"
            if v2ex_short:
                item["quality_flags"].append("v2ex_short_post")
            low_quality.append(item)
        else:
            item["prefilter_decision"] = "candidate"
            normalized.append(item)

    return normalized, low_quality


def split_balanced_by_source(articles: list[dict], min_chunks: int, chunk_size: int) -> list[list[dict]]:
    if not articles:
        return []
    n_chunks = max(min_chunks, math.ceil(len(articles) / max(1, chunk_size)))
    by_source: dict[str, list[dict]] = defaultdict(list)
    for article in articles:
        by_source[article.get("origin") or article.get("domain") or "unknown"].append(article)

    chunks: list[list[dict]] = [[] for _ in range(n_chunks)]
    sizes = [0] * n_chunks
    for _source_name, source_articles in sorted(by_source.items(), key=lambda item: -len(item[1])):
        index = sizes.index(min(sizes))
        chunks[index].extend(source_articles)
        sizes[index] += len(source_articles)

    while len(articles) >= n_chunks and any(size == 0 for size in sizes):
        empty_index = sizes.index(0)
        donor_index = max(range(n_chunks), key=lambda idx: sizes[idx])
        if sizes[donor_index] <= 1:
            break
        chunks[empty_index].append(chunks[donor_index].pop())
        sizes[empty_index] += 1
        sizes[donor_index] -= 1
    return chunks


def worker_packet_item(item: dict, *, content_chars: int = 2000) -> dict:
    return {
        "packet_index": item.get("packet_index"),
        "id": item.get("id", ""),
        "title": item.get("title", ""),
        "link": item.get("link", ""),
        "origin": item.get("origin", ""),
        "domain": item.get("domain", ""),
        "published": item.get("published", 0),
        "summary": item.get("summary", ""),
        "content_excerpt": (item.get("content", "") or "")[:content_chars],
        "content_source": item.get("content_source", ""),
        "quality_flags": item.get("quality_flags", []),
        "prefilter_decision": item.get("prefilter_decision", "candidate"),
    }


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_articles(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="Existing unread article JSON file")
    parser.add_argument("--limit", type=int, default=9999)
    parser.add_argument("--stream-id")
    parser.add_argument("--output-dir", default="/tmp")
    parser.add_argument("--fetch-content", dest="fetch_content", action="store_true", default=True)
    parser.add_argument("--no-fetch-content", dest="fetch_content", action="store_false")
    parser.add_argument("--min-content-chars", type=int, default=500)
    parser.add_argument("--min-chunks", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--worker-content-chars", type=int, default=2000)
    args = parser.parse_args()

    if args.input:
        articles = load_articles(Path(args.input))
    else:
        from rss_analyzer.feedly_client import feedly_fetch_unread

        fetched = feedly_fetch_unread(stream_id=args.stream_id, limit=args.limit)
        if fetched is None:
            print("Failed to fetch unread articles from Feedly", file=sys.stderr)
            return 1
        articles = fetched

    candidates, low_quality = normalize_articles(
        articles, fetch_content=args.fetch_content, min_chars=args.min_content_chars
    )
    chunks = split_balanced_by_source(candidates, args.min_chunks, args.chunk_size)

    output_dir = Path(args.output_dir)
    articles_path = output_dir / "feedly_articles.json"
    low_path = output_dir / "feedly_prefiltered_low_quality.json"
    manifest_path = output_dir / "feedly_readflow_manifest.json"

    write_json(articles_path, candidates)
    write_json(low_path, low_quality)

    chunk_paths = []
    for index, chunk in enumerate(chunks):
        chunk_path = output_dir / f"fb_chunk_{index}.json"
        write_json(
            chunk_path,
            [
                worker_packet_item(item, content_chars=args.worker_content_chars)
                for item in chunk
            ],
        )
        chunk_paths.append(str(chunk_path))

    manifest = {
        "schema_version": 2,
        "input_count": len(articles),
        "candidate_count": len(candidates),
        "prefiltered_low_quality_count": len(low_quality),
        "chunk_count": len(chunks),
        "chunk_size": args.chunk_size,
        "chunk_paths": chunk_paths,
        "triage_chunk_paths": chunk_paths,
        "deep_chunk_paths": [],
        "articles_path": str(articles_path),
        "low_quality_path": str(low_path),
        "contains_secrets": False,
        "fetch_content": args.fetch_content,
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
