"""Shared readflow triage prompt and parsing helpers."""

from __future__ import annotations

import json

from rss_analyzer.utils import strip_html_tags


READFLOW_DOMAINS = {"Tech", "P1", "P2", "Other"}
READFLOW_DECISIONS = {"must_read", "skim", "clear"}


def article_summary_snippet(article: dict, limit: int = 800) -> str:
    return strip_html_tags(article.get("summary", "") or article.get("content", ""))[:limit]


def _content_excerpt(article: dict, limit: int) -> str:
    if limit <= 0:
        return ""
    content = strip_html_tags(article.get("content", "") or "")
    summary = article_summary_snippet(article, limit)
    if content and content != summary:
        return content[:limit]
    return ""


def normalize_readflow_domain(domain: str | None) -> str:
    value = (domain or "").strip().lower()
    if value in {"p2", "国际政治", "geopolitics", "politics"}:
        return "P2"
    if value in {"p1", "投资", "投资理财", "finance", "market"}:
        return "P1"
    if value in {"tech", "technology", "技术", "ai", "dev"}:
        return "Tech"
    return "Other"


def coerce_readflow_decision(decision: str | None, score: float) -> str:
    value = (decision or "").strip().lower()
    legacy = {
        "strong_recommend": "must_read",
        "recommend": "must_read",
        "optional": "skim",
        "low_quality": "clear",
        "noise": "clear",
    }
    if value in READFLOW_DECISIONS:
        return value
    if value in legacy:
        return legacy[value]
    if score >= 3.8:
        return "must_read"
    if score >= 2.5:
        return "skim"
    return "clear"


def coerce_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def build_readflow_triage_prompt(
    articles: list[dict],
    *,
    max_summary_chars: int = 800,
    max_content_chars: int = 1200,
) -> str:
    items = []
    for index, article in enumerate(articles, 1):
        items.append(
            {
                "n": index,
                "title": article.get("title", ""),
                "origin": article.get("origin", ""),
                "domain_hint": article.get("domain", ""),
                "summary": article_summary_snippet(article, max_summary_chars),
                "content_excerpt": _content_excerpt(article, max_content_chars),
                "content_source": article.get("content_source", ""),
                "quality_flags": article.get("quality_flags", []),
            }
        )

    return f"""你是一个批量阅读助手，目标是帮助用户快速阅读 RSS，尤其要提取 P2（国际政治/地缘政治/国际关系）里的有效信息。

请对每篇文章做轻量 triage。不要只按标题吸引力评分，要结合 summary、content_excerpt、content_source 和 quality_flags 判断事实增量。

domain 只能是：
- Tech：技术、AI、开发、工具
- P1：投资理财、市场、宏观、资产
- P2：国际政治、地缘政治、外交、安全、战争、制裁、国家关系
- Other：其他

decision 只能是：
- must_read：值得点开或需要正文确认
- skim：知道核心事实即可
- clear：重复、低增量、广告或无关

输出 JSON 数组，每篇必须一项：
[
  {{
    "n": 1,
    "domain": "P2",
    "domain_confidence": 0.0-1.0,
    "score": 1.0-5.0,
    "decision": "must_read/skim/clear",
    "event": "核心事件，20字内",
    "actors": "主要相关方，逗号分隔",
    "region": "地区/国家",
    "core_fact": "新增事实或最重要事实，35字内",
    "why_it_matters": "为什么值得关注，35字内",
    "novelty": "new/repeat/unclear",
    "needs_deep_read": true/false,
    "rec": "一句阅读建议，16字内",
    "similarity_key": "稳定主题键，不要只按来源"
  }}
]

文章数据：
{json.dumps(items, ensure_ascii=False)}"""


def parse_readflow_triage_results(articles: list[dict], raw_items: list) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        idx = int(entry.get("n", 0) or 0) - 1
        if not (0 <= idx < len(articles)):
            continue
        article = articles[idx]
        score = float(entry.get("score") or 0.0)
        event = str(entry.get("event") or article.get("title", ""))
        domain = normalize_readflow_domain(entry.get("domain"))
        triage = {
            "domain": domain,
            "readflow_domain": domain,
            "domain_confidence": float(entry.get("domain_confidence") or 0.0),
            "score": score,
            "decision": coerce_readflow_decision(entry.get("decision"), score),
            "event": event,
            "actors": str(entry.get("actors") or ""),
            "region": str(entry.get("region") or ""),
            "core_fact": str(
                entry.get("core_fact")
                or article_summary_snippet(article, 120)
                or article.get("title", "")
            ),
            "why_it_matters": str(entry.get("why_it_matters") or ""),
            "novelty": str(entry.get("novelty") or "unclear"),
            "needs_deep_read": coerce_bool(entry.get("needs_deep_read"), False),
            "rec": str(entry.get("rec") or ""),
            "similarity_key": str(entry.get("similarity_key") or event or "other"),
            "source": "llm",
        }
        result[article.get("id", "")] = triage
    return result
