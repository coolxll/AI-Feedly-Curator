#!/usr/bin/env python3
"""Prepare deep-read packets from triage reports and normalized articles."""

from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path


def load_json_list(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"{path}: expected a JSON array")
    return data


def load_triage_reports(report_glob: str) -> list[dict]:
    items: list[dict] = []
    for path in sorted(glob.glob(report_glob)):
        items.extend(load_json_list(Path(path)))
    if not items:
        raise SystemExit(f"No triage reports matched: {report_glob}")
    return items


def should_deep_read(item: dict) -> bool:
    decision = str(item.get("decision") or "").strip().lower()
    if decision in {"strong_recommend", "must_read"}:
        return True
    return bool(item.get("needs_deep_read"))


def deep_packet_item(article: dict, triage: dict, *, content_chars: int) -> dict:
    return {
        "id": article.get("id", ""),
        "title": article.get("title", ""),
        "link": article.get("link", ""),
        "origin": article.get("origin", ""),
        "domain": article.get("domain", ""),
        "summary": article.get("summary", ""),
        "content": (article.get("content", "") or "")[:content_chars],
        "content_source": article.get("content_source", ""),
        "quality_flags": article.get("quality_flags", []),
        "triage": {
            "score": triage.get("score"),
            "decision": triage.get("decision"),
            "readflow_domain": triage.get("readflow_domain") or triage.get("domain"),
            "event": triage.get("event"),
            "actors": triage.get("actors"),
            "region": triage.get("region"),
            "core_fact": triage.get("core_fact"),
            "why_it_matters": triage.get("why_it_matters"),
            "needs_deep_read": triage.get("needs_deep_read"),
            "similarity_key": triage.get("similarity_key"),
        },
    }


def chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-glob", default="/tmp/fb_report_*.json")
    parser.add_argument("--data", default="/tmp/feedly_articles.json")
    parser.add_argument("--output-dir", default="/tmp")
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--content-chars", type=int, default=10000)
    args = parser.parse_args()

    articles = load_json_list(Path(args.data))
    article_by_id = {item.get("id", ""): item for item in articles}
    selected = []
    seen: set[str] = set()
    for triage in load_triage_reports(args.report_glob):
        entry_id = triage.get("id", "")
        if not entry_id or entry_id in seen or not should_deep_read(triage):
            continue
        article = article_by_id.get(entry_id)
        if not article:
            continue
        selected.append(deep_packet_item(article, triage, content_chars=args.content_chars))
        seen.add(entry_id)

    output_dir = Path(args.output_dir)
    chunks = chunked(selected, max(1, args.chunk_size))
    paths = []
    for index, chunk in enumerate(chunks):
        path = output_dir / f"fb_deep_chunk_{index}.json"
        write_json(path, chunk)
        paths.append(str(path))

    manifest = {
        "schema_version": 2,
        "deep_candidate_count": len(selected),
        "deep_chunk_count": len(chunks),
        "deep_chunk_paths": paths,
        "contains_secrets": False,
    }
    manifest_path = output_dir / "feedly_deep_read_manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
