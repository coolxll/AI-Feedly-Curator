#!/usr/bin/env python3
"""Merge worker JSON reports into one deduplicated Feedly Markdown report.

Workers return JSON arrays (one object per article) per ``worker_packet.md``.
This script loads every ``fb_report_*.json``, clusters items by
``similarity_key``, and renders a single Markdown report following
``templates/final_report.md``. Links come only from each item's ``link``
field (the packet link); no URL is inferred or repaired except the known
tmtpost ``.html`` normalization.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


DECISION_MAP = {
    "strong_recommend": "must_read",
    "recommend": "must_read",
    "optional": "skim",
    "low_quality": "clear",
    "noise": "clear",
}

DOMAIN_MAP = {
    "tech": "Tech",
    "technology": "Tech",
    "技术": "Tech",
    "p1": "P1",
    "finance": "P1",
    "market": "P1",
    "投资": "P1",
    "p2": "P2",
    "geopolitics": "P2",
    "politics": "P2",
    "国际政治": "P2",
    "other": "Other",
}


def fix_tmtpost_link(link: str) -> str:
    """Normalize tmtpost URLs to the canonical ``.html`` form."""
    link = re.sub(r"(\.html)\d+\.html", r"\1", link)
    return re.sub(
        r"(https://www\.tmtpost\.com/\d+)(?:\.html)?(?=[?#/)]|$)",
        r"\1.html",
        link,
    )


def normalize_item(item: dict, *, stage: str) -> dict:
    normalized = dict(item)
    normalized["link"] = fix_tmtpost_link(normalized.get("link", "") or "")
    readflow_domain = normalize_readflow_domain(
        normalized.get("readflow_domain") or normalized.get("domain")
    )
    normalized["readflow_domain"] = readflow_domain
    decision = str(normalized.get("decision") or "").strip().lower()
    if decision in DECISION_MAP:
        decision = DECISION_MAP[decision]
    if decision not in {"must_read", "skim", "clear"}:
        decision = "must_read" if _score(normalized) >= 3.8 else "skim" if _score(normalized) >= 2.5 else "clear"
    normalized["decision"] = decision
    normalized["report_stage"] = stage
    if "core_facts" not in normalized and normalized.get("core_fact"):
        normalized["core_facts"] = [normalized["core_fact"]]
    if "reasoning" not in normalized:
        normalized["reasoning"] = (
            normalized.get("analysis_summary")
            or normalized.get("why_it_matters")
            or normalized.get("rec")
            or normalized.get("core_fact")
            or ""
        )
    if "similarity_key" not in normalized:
        normalized["similarity_key"] = normalized.get("event") or normalized.get("title") or "other"
    return normalized


def normalize_readflow_domain(value: str | None) -> str:
    normalized = DOMAIN_MAP.get(str(value or "").strip().lower())
    return normalized or "Other"


def load_reports(report_glob: str, *, stage: str = "triage", allow_empty: bool = False) -> list[dict]:
    """Load and deduplicate worker JSON reports by entry id (keep highest score)."""
    paths = sorted(Path(path) for path in glob.glob(report_glob))
    if not paths:
        if allow_empty:
            return []
        raise SystemExit(f"No worker reports matched: {report_glob}")

    by_id: dict[str, dict] = {}
    for path in paths:
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise SystemExit(f"{path}: expected a JSON array, got {type(items).__name__}")
        for item in items:
            if not isinstance(item, dict):
                continue
            item = normalize_item(item, stage=stage)
            entry_id = item.get("id", "")
            existing = by_id.get(entry_id)
            if existing is None or _score(item) > _score(existing):
                by_id[entry_id] = item
    return list(by_id.values())


def merge_report_items(triage_items: list[dict], deep_items: list[dict]) -> list[dict]:
    by_id = {item.get("id", ""): item for item in triage_items}
    for item in deep_items:
        entry_id = item.get("id", "")
        if not entry_id:
            continue
        merged = dict(by_id.get(entry_id, {}))
        merged.update(item)
        merged["report_stage"] = "deep"
        by_id[entry_id] = merged
    return list(by_id.values())


def _score(item: dict) -> float:
    value = item.get("score")
    return float(value) if isinstance(value, (int, float)) else 0.0


def load_json_list(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def cluster(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group items by similarity_key, sorted by max score descending."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[item.get("similarity_key") or "other"].append(item)
    return sorted(
        groups.items(),
        key=lambda kv: -max(_score(item) for item in kv[1]),
    )


def md_link(item: dict) -> str:
    title = (item.get("title") or "Untitled").replace("|", "\\|")
    link = item.get("link") or ""
    if not link:
        return f"{title}（无链接）"
    return f"[{title}]({link})"


def short_heading(key: str) -> str:
    """Turn a similarity_key into a short ### subheading."""
    return (key or "other").replace("_", " ").strip()


def render_section(key: str, items: list[dict]) -> list[str]:
    """Render one topic section: synthesis + representative + supporting links."""
    ordered = sorted(items, key=_score, reverse=True)
    lines = [f"### {short_heading(key)}", ""]

    facts: list[str] = []
    for item in ordered:
        for fact in item.get("core_facts") or []:
            if fact and fact not in facts:
                facts.append(fact)
        if item.get("why_it_matters") and item["why_it_matters"] not in facts:
            facts.append(item["why_it_matters"])
    if facts:
        lines.append("关键事实：" + "；".join(facts[:6]) + "。")
        lines.append("")

    representative = ordered[0]
    lines.append(
        f"- 代表文章：{md_link(representative)} - {_clip(representative.get('reasoning'))}"
    )
    for item in ordered[1:]:
        lines.append(
            f"- 补充链接：{md_link(item)} - {_clip(item.get('reasoning'))}"
        )
    return lines + [""]


def _clip(text: str | None, limit: int = 140) -> str:
    return (text or "").replace("\n", " ").strip()[:limit]


def render_recommendations(items: list[dict], decision: str, limit: int = 160) -> list[str]:
    ordered = sorted(
        (item for item in items if item.get("decision") == decision),
        key=_score,
        reverse=True,
    )
    lines = []
    for item in ordered:
        lines.append(
            f"- `{_score(item):.1f}` {md_link(item)}：{_clip(item.get('reasoning'), limit)}"
        )
    return lines


def render_clear(items: list[dict], prefiltered: list[dict]) -> list[str]:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        if item.get("decision") == "clear":
            by_domain[item.get("domain") or item.get("readflow_domain") or "?"].append(item)

    lines = []
    for domain, domain_items in sorted(by_domain.items(), key=lambda kv: -len(kv[1])):
        sample = sorted(domain_items, key=_score, reverse=True)[0]
        lines.append(
            f"- {md_link(sample)} 等 {len(domain_items)} 篇（{domain}）："
            f"{_clip(sample.get('reasoning'), 80)}"
        )

    if prefiltered:
        lines.append("")
        lines.append("预过滤阶段直接剔除的低质量（未进入分析）：")
        for item in prefiltered:
            title = (item.get("title") or "")[:50]
            link = item.get("link") or ""
            flags = ",".join(item.get("quality_flags") or [])
            link_str = f"[{title}]({link})" if link else f"{title}（无链接）"
            lines.append(f"- {link_str}：{flags}")
    return lines


def render_overview(items: list[dict], prefiltered: list[dict]) -> list[str]:
    must = sum(1 for item in items if item.get("decision") == "must_read")
    skim = sum(1 for item in items if item.get("decision") == "skim")
    clear = sum(1 for item in items if item.get("decision") == "clear")
    scores = [_score(item) for item in items]
    avg = sum(scores) / len(scores) if scores else 0.0
    top = max(scores) if scores else 0.0
    total = len(items) + len(prefiltered)

    return [
        "## 整体概况",
        "",
        f"共处理 {total} 篇未读，{len(items)} 篇进入正文分析，"
        f"{len(prefiltered)} 篇预过滤低质量。评分分布：Must Read {must} / "
        f"Skim {skim} / Clear {clear}；平均分 {avg:.2f}，最高 {top:.1f}。",
        "",
        "高价值主题见下方「主题聚合」与「Must Read」。Clear 项已归入「低质量/可清理」，"
        "确认后可用 ``mark_read.py`` 清理。",
        "",
    ]


def render_stats(items: list[dict], prefiltered: list[dict], report_paths: list[Path]) -> list[str]:
    origin_count = Counter(item.get("origin") or item.get("domain") or "?" for item in items)
    source_count = Counter(item.get("content_source") or "?" for item in items)
    clear = sum(1 for item in items if item.get("decision") == "clear")
    return [
        "## 统计与来源",
        "",
        f"- 总文章数：{len(items) + len(prefiltered)}",
        f"- 分析文章数：{len(items)}",
        f"- 低质量/可清理数：{clear}（分析判定）+ {len(prefiltered)}（预过滤）",
        f"- 合并 worker 报告数：{len(report_paths)}",
        "- 主要来源："
        + ", ".join(f"{origin}({count})" for origin, count in origin_count.most_common(6)),
        f"- 内容来源分布：{dict(source_count)}",
        "- 链接校验：待运行 ``post_merge_link_fix.py`` 复核",
        "",
    ]


def render_report(
    items: list[dict],
    prefiltered: list[dict],
    report_paths: list[Path],
) -> str:
    clusters = cluster(items)
    lines: list[str] = ["# Feedly RSS 阅读报告", ""]
    lines.append(f"> 合并 {len(report_paths)} 个 worker 报告，{len(items)} 篇分析文章")
    lines += ["", *render_overview(items, prefiltered)]

    lines.append("## 主题聚合")
    lines.append("")
    for key, group_items in clusters:
        lines += render_section(key, group_items)

    p2_items = sorted(
        [
            item
            for item in items
            if item.get("readflow_domain") == "P2" or item.get("domain") == "P2"
        ],
        key=_score,
        reverse=True,
    )
    if p2_items:
        lines.append("## P2 快速情报")
        lines.append("")
        for item in p2_items[:12]:
            lines.append(
                f"- `{_score(item):.1f}` {item.get('event') or item.get('title')}: "
                f"{_clip(item.get('core_fact') or item.get('reasoning'), 100)}"
            )
        lines.append("")

    lines.append("## Must Read")
    lines.append("")
    lines += render_recommendations(items, "must_read")
    lines += ["", "## Skim", ""]
    lines += render_recommendations(items, "skim")
    lines += ["", "## 低质量/可清理", ""]
    lines += render_clear(items, prefiltered)
    lines += ["", "## 今日行动建议", ""]
    lines += [
        "- 深读 Must Read 主题，按分数排序优先打开。",
        "- 观察跨文章主题的互相印证或矛盾之处。",
        "- 低质量项确认后可标记已读，减少后续噪音。",
        "",
    ]
    lines += render_stats(items, prefiltered, report_paths)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-glob",
        default="/tmp/fb_report_*.json",
        help="Glob matching triage worker JSON reports (default: /tmp/fb_report_*.json)",
    )
    parser.add_argument(
        "--deep-report-glob",
        default="/tmp/fb_deep_report_*.json",
        help="Optional glob matching deep worker JSON reports",
    )
    parser.add_argument(
        "--data",
        default="/tmp/feedly_articles.json",
        help="Normalized candidate articles JSON (for stats; optional)",
    )
    parser.add_argument(
        "--low-quality",
        default="/tmp/feedly_prefiltered_low_quality.json",
        help="Prefiltered low-quality articles JSON (optional)",
    )
    parser.add_argument(
        "--output",
        default="/tmp/feedly_final_report.md",
        help="Output Markdown report path",
    )
    args = parser.parse_args()

    report_paths = sorted(Path(path) for path in glob.glob(args.report_glob))
    deep_paths = sorted(Path(path) for path in glob.glob(args.deep_report_glob))
    triage_items = load_reports(args.report_glob, stage="triage")
    deep_items = load_reports(args.deep_report_glob, stage="deep", allow_empty=True)
    items = merge_report_items(triage_items, deep_items)
    prefiltered = load_json_list(Path(args.low_quality))

    # If --data was given but --low-quality was not, still try the default
    # prefiltered path next to the candidate file for convenience.
    if not args.low_quality:
        default_low = Path(args.data).parent / "feedly_prefiltered_low_quality.json"
        if default_low.exists():
            prefiltered = load_json_list(default_low)

    report = render_report(items, prefiltered, report_paths + deep_paths)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report + "\n", encoding="utf-8")

    decisions = Counter(item.get("decision") for item in items)
    print(f"Loaded {len(report_paths)} triage reports and {len(deep_paths)} deep reports, {len(items)} unique articles")
    print(f"Decisions: {dict(decisions)}")
    print(f"Prefiltered low-quality: {len(prefiltered)}")
    print(f"Wrote {output} ({len(report)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
