"""
Stream-oriented backlog reduction strategies.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import json
import logging

from openai import OpenAI

from rss_analyzer.config import build_openai_client_kwargs, get_openai_task_config
from rss_analyzer.utils import is_newsflash, strip_html_tags

logger = logging.getLogger(__name__)

STRATEGY_QUICK_CLEAR = "quick_clear"
STRATEGY_RADAR = "radar"
MUST_READ_RATIO = 0.2
MIN_MUST_READ_ITEMS = 3
MAX_MUST_READ_ITEMS = 12
MAX_THEME_SHARE_RATIO = 0.4
MAX_LLM_THEME_GROUPS = 6
MAX_LLM_REPRESENTATIVES = 3

LOW_PRIORITY_BUCKETS = {"推广", "酷工作"}
LOW_PRIORITY_TITLE_KEYWORDS = (
    "推广",
    "广告",
    "返现",
    "代充",
    "内测",
    "邀请码",
    "收徒",
    "陪练",
    "招募",
    "开户",
    "低佣",
    "免五",
)


def _get_radar_client():
    openai_config = get_openai_task_config("summary", default_model="gpt-4o-mini")
    client = OpenAI(**build_openai_client_kwargs(openai_config))
    return client, openai_config.model


def determine_stream_strategy(
    stream_id: str | None, stream_label: str | None = None
) -> str:
    label = (stream_label or "").lower()
    stream_id_norm = (stream_id or "").lower()

    if "36kr" in label or "36氪" in label or "36kr.com/feed" in stream_id_norm:
        return STRATEGY_QUICK_CLEAR

    return STRATEGY_RADAR


def filter_recent_articles(articles: list[dict], days: int) -> list[dict]:
    if days <= 0:
        return list(articles)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    return [article for article in articles if article.get("published", 0) >= cutoff_ms]


def _clean_summary(article: dict) -> str:
    return strip_html_tags(article.get("summary", ""))[:400]


def _title_bucket(title: str) -> str:
    match = re.match(r"^\[(.*?)\]", title or "")
    if match:
        return match.group(1).strip() or "未分类"
    return "未分类"


def _stream_source_kind(stream_label: str | None, article: dict) -> str:
    label = (stream_label or article.get("origin", "") or "").lower()
    if "v2ex" in label:
        return "v2ex"
    if "雪球" in label or "xueqiu" in label:
        return "xueqiu"
    if "集思录" in label or "jisilu" in label:
        return "jisilu"
    return "generic"


def _keyword_bucket(text: str, bucket_groups: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    for bucket, keywords in bucket_groups:
        if any(keyword in text for keyword in keywords):
            return bucket
    return "其他"


def _xueqiu_bucket(article: dict) -> str:
    title = article.get("title", "")
    summary = _clean_summary(article)
    text = f"{title} {summary}".lower()
    bucket_groups = (
        (
            "策略 / 组合",
            ("组合", "调仓", "仓位", "实盘", "定投", "回撤", "风控", "跟投", "跟仓", "轮动"),
        ),
        (
            "ETF / 基金",
            ("etf", "lof", "基金", "指数", "宽基", "纳指", "红利", "中概", "场内基金"),
        ),
        (
            "个股 / 财报",
            ("财报", "年报", "季报", "业绩", "估值", "分红", "回购", "股价", "公司", "个股"),
        ),
        (
            "宏观 / 市场",
            ("宏观", "经济", "市场", "关税", "降息", "通胀", "cpi", "pmi", "衰退", "美联储", "风险"),
        ),
        (
            "可转债 / 套利",
            ("转债", "套利", "折价", "溢价", "配售"),
        ),
    )
    return _keyword_bucket(text, bucket_groups)


def _jisilu_bucket(article: dict) -> str:
    title = article.get("title", "")
    summary = _clean_summary(article)
    text = f"{title} {summary}".lower()
    bucket_groups = (
        (
            "可转债",
            ("转债", "双低", "强赎", "下修", "回售", "正股", "到期", "申购转债", "可转债"),
        ),
        (
            "ETF / LOF / 套利",
            ("etf", "lof", "套利", "折价", "溢价", "封基", "申赎", "场内", "指数基金"),
        ),
        (
            "打新 / 现金管理",
            ("打新", "新股", "逆回购", "货基", "现金管理", "申购"),
        ),
        (
            "策略 / 仓位",
            ("仓位", "轮动", "网格", "定投", "组合", "资产配置", "回撤", "估值", "策略"),
        ),
        (
            "券商 / 账户 / 规则",
            ("券商", "开户", "佣金", "免五", "交易规则", "账户", "港卡", "低佣"),
        ),
    )
    return _keyword_bucket(text, bucket_groups)


def _generic_bucket(article: dict) -> str:
    title = article.get("title", "")
    summary = _clean_summary(article)
    text = f"{title} {summary}".lower()

    keyword_groups = (
        ("AI / LLM", ("ai", "gpt", "claude", "llm", "qwen", "deepseek", "glm")),
        ("Apple / macOS", ("mac", "macos", "apple", "iphone", "safari", "ios")),
        ("投资 / 市场", ("股票", "基金", "投资", "市场", "美股", "港股", "财报", "雪球")),
        ("开发 / 编程", ("编程", "程序", "开发", "代码", "go", "python", ".net", "前端")),
        ("运维 / 系统", ("linux", "docker", "nginx", "redis", "mysql", "ubuntu")),
    )

    for bucket, keywords in keyword_groups:
        if any(keyword in text for keyword in keywords):
            return bucket

    return "其他"


def _bucket_key(article: dict, stream_label: str | None = None) -> str:
    source_kind = _stream_source_kind(stream_label, article)
    if source_kind == "v2ex":
        return _title_bucket(article.get("title", ""))
    if source_kind == "xueqiu":
        return _xueqiu_bucket(article)
    if source_kind == "jisilu":
        return _jisilu_bucket(article)
    return _generic_bucket(article)


def _is_low_priority(article: dict, bucket: str) -> bool:
    if bucket in LOW_PRIORITY_BUCKETS:
        return True

    title = article.get("title", "")
    summary = _clean_summary(article)
    text = f"{title} {summary}".lower()
    return any(keyword.lower() in text for keyword in LOW_PRIORITY_TITLE_KEYWORDS)


def _article_preview(article: dict, bucket: str, low_priority: bool) -> dict:
    summary = _clean_summary(article)
    interpretation = _interpret_candidate(article.get("title", ""), summary, bucket)
    return {
        "id": article.get("id"),
        "title": article.get("title", "Untitled"),
        "link": article.get("link", ""),
        "origin": article.get("origin", ""),
        "published": article.get("published", 0),
        "bucket": bucket,
        "summary": summary,
        "interpretation": interpretation,
        "show_summary": _should_show_summary(summary, interpretation),
        "low_priority": low_priority,
    }


def _interpret_candidate(title: str, summary: str, bucket: str) -> str:
    if bucket in {"程序员", "开发 / 编程"}:
        return "优先看可复用经验、踩坑和工具取舍。"
    if bucket in {"问与答", "策略 / 组合"}:
        return "适合快速看观点分歧，再决定是否深入。"
    if bucket in {"分享创造", "个股 / 财报", "ETF / 基金"}:
        return "代表性较强，适合用来判断这一主题要不要继续追。"
    if bucket in {"宏观 / 市场", "可转债", "可转债 / 套利"}:
        return "更偏判断和盘感，适合建立全局认知，不必逐条细读。"
    if bucket in {"券商 / 账户 / 规则", "打新 / 现金管理", "ETF / LOF / 套利"}:
        return "偏规则和机会扫描，读代表项就够。"
    if bucket in {"Apple / macOS", "macOS", "Apple", "iPhone"}:
        return "适合判断是否与你当前设备和工作流直接相关。"
    if bucket in {"AI / LLM", "Claude Code"}:
        return "适合快速看新工具、新模型或实战经验有没有增量。"
    return "可作为这个主题的代表项，先抽样再决定是否继续展开。"


def _normalize_compare_text(text: str) -> str:
    lowered = (text or "").lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lowered)


def _should_show_summary(summary: str, interpretation: str) -> bool:
    if not summary:
        return False

    normalized_summary = _normalize_compare_text(summary)
    normalized_interpretation = _normalize_compare_text(interpretation)

    if not normalized_summary:
        return False
    if not normalized_interpretation:
        return True

    if normalized_summary in normalized_interpretation:
        return False
    if normalized_interpretation in normalized_summary and len(normalized_interpretation) >= 12:
        return False

    summary_terms = {term for term in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{3,}", summary.lower())}
    interpretation_terms = {
        term for term in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{3,}", interpretation.lower())
    }
    if summary_terms and interpretation_terms:
        overlap_ratio = len(summary_terms & interpretation_terms) / max(
            1, min(len(summary_terms), len(interpretation_terms))
        )
        if overlap_ratio >= 0.7:
            return False

    return True


def _summarize_bucket(bucket: str, items: list[dict]) -> str:
    if not items:
        return "No items."

    if bucket == "问与答":
        return "以问题求助和使用经验交流为主，适合快速抽样查看。"
    if bucket == "程序员":
        return "以开发实践、工具讨论和模型/产品对比为主。"
    if bucket == "分享创造":
        return "以新产品、个人项目和工具发布为主，值得看代表作。"
    if bucket in {"推广", "酷工作"}:
        return "商业推广或招聘信息占比高，适合快速清理。"
    if bucket in {"Claude Code", "AI / LLM"}:
        return "聚焦模型、订阅、AI 编程工具和实操体验。"
    if bucket in {"Apple / macOS", "macOS", "Apple", "iPhone"}:
        return "聚焦 Apple 设备、系统体验和软件使用问题。"
    if bucket == "策略 / 组合":
        return "聚焦仓位、调仓、组合收益和执行框架，适合抽样看方法论。"
    if bucket == "ETF / 基金":
        return "聚焦 ETF、指数基金和宽基配置，适合快速判断是否有新机会。"
    if bucket == "个股 / 财报":
        return "聚焦个股观点、业绩与估值变化，适合按代表标的抽样。"
    if bucket == "宏观 / 市场":
        return "聚焦宏观环境、市场风险和资产价格方向，适合做大盘判断。"
    if bucket in {"可转债", "可转债 / 套利"}:
        return "聚焦可转债、强赎/下修、折溢价和套利机会，适合集中速览。"
    if bucket == "ETF / LOF / 套利":
        return "聚焦场内基金、折溢价与套利讨论，信息密度较高。"
    if bucket == "打新 / 现金管理":
        return "聚焦打新、逆回购和闲钱管理，适合规则化浏览。"
    if bucket == "券商 / 账户 / 规则":
        return "聚焦券商费率、开户和交易规则，通常可快速判断去留。"

    titles = [item["title"] for item in items[:2]]
    joined = "；".join(titles)
    return f"该主题本批次共有 {len(items)} 条，代表内容包括：{joined}"


def _llm_summarize_theme_groups(theme_groups: list[dict]) -> dict[str, str]:
    if not theme_groups:
        return {}

    payload = []
    for group in theme_groups[:MAX_LLM_THEME_GROUPS]:
        payload.append(
            {
                "bucket": group["bucket"],
                "count": group["count"],
                "representatives": [
                    {
                        "title": item.get("title", ""),
                        "summary": item.get("summary", ""),
                    }
                    for item in group.get("representatives", [])[:MAX_LLM_REPRESENTATIVES]
                ],
            }
        )

    prompt = (
        "你是信息编辑。请根据每个主题桶的代表文章，"
        "为每个 bucket 生成一句 18-36 字的中文摘要，强调这个主题最近在讨论什么。"
        "不要重复 bucket 名，不要给建议，不要写序号。"
        "只输出 JSON 对象，格式如下："
        '{"bucket摘要映射":{"程序员":"...", "问与答":"..."}}'
        f"\n\n数据：\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        logger.info(
            "Process Stream: summarizing %s theme groups...",
            min(len(theme_groups), MAX_LLM_THEME_GROUPS),
        )
        client, model = _get_radar_client()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return {}
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or start >= end:
            return {}
        parsed = json.loads(content[start : end + 1])
        mapping = parsed.get("bucket摘要映射", {})
        logger.info("Process Stream: finished theme group summarization.")
        return {str(key): str(value) for key, value in mapping.items() if value}
    except Exception as exc:
        logger.debug("Theme group LLM summarization failed: %s", exc)
        return {}


def _llm_interpret_candidates(items: list[dict]) -> dict[str, str]:
    if not items:
        return {}

    payload = [
        {
            "id": item.get("id"),
            "bucket": item.get("bucket"),
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
        }
        for item in items[:MAX_MUST_READ_ITEMS]
    ]

    prompt = (
        "你是阅读助手。请为每条候选文章生成一句简短中文“解读”，"
        "重点回答这条内容为什么值得点开，语气务实，控制在 12-28 字。"
        "不要复述标题，不要复述摘要原句。"
        "只输出 JSON 对象，格式如下："
        '{"candidate解读映射":{"id1":"...", "id2":"..."}}'
        f"\n\n数据：\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        logger.info(
            "Process Stream: interpreting %s must-read candidates...",
            min(len(items), MAX_MUST_READ_ITEMS),
        )
        client, model = _get_radar_client()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            return {}
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or start >= end:
            return {}
        parsed = json.loads(content[start : end + 1])
        mapping = parsed.get("candidate解读映射", {})
        logger.info("Process Stream: finished candidate interpretation.")
        return {str(key): str(value) for key, value in mapping.items() if value}
    except Exception as exc:
        logger.debug("Candidate interpretation LLM call failed: %s", exc)
        return {}


def _rank_article(item: dict) -> tuple[int, int]:
    summary_len = len(item.get("summary", ""))
    title = item.get("title", "")
    quality_bonus = 0
    if "分享创造" in title:
        quality_bonus += 15
    if "程序员" in title or "问与答" in title:
        quality_bonus += 10
    if item.get("low_priority"):
        quality_bonus -= 100
    return (quality_bonus + summary_len, -item.get("published", 0))


def _target_must_read_count(candidate_count: int) -> int:
    if candidate_count <= 0:
        return 0
    proportional = round(candidate_count * MUST_READ_RATIO)
    return min(candidate_count, max(MIN_MUST_READ_ITEMS, min(MAX_MUST_READ_ITEMS, proportional)))


def _max_items_per_theme(target_count: int) -> int:
    if target_count <= 0:
        return 0
    return max(1, int(target_count * MAX_THEME_SHARE_RATIO))


def _select_must_read_items(candidate_items: list[dict]) -> tuple[list[dict], int]:
    if not candidate_items:
        return [], 0

    sorted_items = sorted(candidate_items, key=_rank_article, reverse=True)
    target_count = _target_must_read_count(len(sorted_items))
    per_theme_limit = _max_items_per_theme(target_count)

    selected: list[dict] = []
    bucket_counts: Counter[str] = Counter()

    for item in sorted_items:
        bucket = item.get("bucket", "其他")
        if bucket_counts[bucket] >= per_theme_limit:
            continue
        selected.append(item)
        bucket_counts[bucket] += 1
        if len(selected) >= target_count:
            break

    if len(selected) < target_count:
        selected_ids = {item.get("id") for item in selected}
        for item in sorted_items:
            if item.get("id") in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= target_count:
                break

    overflow_count = max(0, len(candidate_items) - len(selected))
    return selected, overflow_count


def _pick_skim_items(candidate_items: list[dict], must_read_items: list[dict]) -> list[dict]:
    if not candidate_items:
        return []

    selected_ids = {item.get("id") for item in must_read_items}
    remaining = [item for item in candidate_items if item.get("id") not in selected_ids]
    return sorted(remaining, key=_rank_article, reverse=True)[:10]


def _build_digest(
    *,
    stream_label: str,
    strategy: str,
    days: int,
    recent_articles: list[dict],
    candidate_items: list[dict],
    theme_groups: list[dict],
    must_read_items: list[dict],
    skim_items: list[dict],
    clear_items: list[dict],
) -> dict:
    bucket_counter = Counter(item["bucket"] for item in candidate_items)
    top_buckets = [f"{bucket}({count})" for bucket, count in bucket_counter.most_common(4)]
    top_bucket_text = "、".join(top_buckets) if top_buckets else "暂无高价值主题"
    clear_ratio = (len(clear_items) / len(recent_articles)) if recent_articles else 0.0

    headline = (
        f"{stream_label} 最近 {days} 天有 {len(recent_articles)} 条未读，"
        f"重点集中在 {top_bucket_text}。"
    )
    executive_summary = (
        f"这一批内容里，高价值信号主要分布在 {top_bucket_text}。"
        f"建议优先处理 {len(must_read_items)} 条重点候选，"
        f"其余 {len(skim_items)} 条可略读，约 {clear_ratio:.0%} 可直接清理。"
    )

    actions = []
    if must_read_items:
        actions.append(f"先看 must-read 的 {len(must_read_items)} 篇重点文章。")
    if skim_items:
        actions.append(f"若时间有限，只抽样 skim 区里的 {min(3, len(skim_items))} 篇代表项。")
    if clear_items:
        actions.append(f"可批量已读 {len(clear_items)} 条低优先级或重复噪音内容。")

    stats = {
        "fetched_count": len(recent_articles),
        "candidate_count": len(candidate_items),
        "must_read_count": len(must_read_items),
        "skim_count": len(skim_items),
        "clear_count": len(clear_items),
        "clear_ratio": clear_ratio,
    }

    return {
        "digest_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stream_key": stream_label,
        "time_window": {"days": days},
        "theme_fingerprint": [group["bucket"] for group in theme_groups],
        "article_ids_by_bucket": {
            group["bucket"]: [item.get("id") for item in group.get("representatives", []) if item.get("id")]
            for group in theme_groups
        },
        "headline": headline,
        "executive_summary": executive_summary,
        "top_themes": theme_groups,
        "must_read_candidates": must_read_items,
        "deep_analyzed_reads": [],
        "skim_items": skim_items,
        "clear_items": clear_items,
        "actions": actions,
        "stats": stats,
        "new_themes": [],
        "recurring_themes": [],
        "suppressed_as_repeat": [],
        "strategy": strategy,
    }


def generate_radar_overview(
    articles: list[dict],
    *,
    stream_id: str | None = None,
    stream_label: str | None = None,
    days: int = 3,
) -> dict:
    recent_articles = filter_recent_articles(articles, days)
    grouped: dict[str, list[dict]] = {}
    low_priority_items: list[dict] = []
    candidate_items: list[dict] = []

    for article in recent_articles:
        bucket = _bucket_key(article, stream_label)
        preview = _article_preview(article, bucket, _is_low_priority(article, bucket))
        grouped.setdefault(bucket, []).append(preview)
        if preview["low_priority"]:
            low_priority_items.append(preview)
        else:
            candidate_items.append(preview)

    theme_groups = []
    for bucket, items in sorted(
        grouped.items(), key=lambda entry: (-len(entry[1]), entry[0])
    ):
        low_count = sum(1 for item in items if item["low_priority"])
        representatives = sorted(items, key=_rank_article, reverse=True)[:3]
        theme_groups.append(
            {
                "bucket": bucket,
                "count": len(items),
                "low_priority_count": low_count,
                "summary": _summarize_bucket(bucket, items),
                "representatives": representatives,
            }
        )

    llm_bucket_summaries = _llm_summarize_theme_groups(theme_groups)
    for group in theme_groups:
        llm_summary = llm_bucket_summaries.get(group["bucket"])
        if llm_summary:
            group["summary"] = llm_summary

    must_read_items, overflow_count = _select_must_read_items(candidate_items)
    skim_items = _pick_skim_items(candidate_items, must_read_items)
    llm_candidate_interpretations = _llm_interpret_candidates(must_read_items)
    for item in must_read_items:
        llm_interpretation = llm_candidate_interpretations.get(str(item.get("id")))
        if llm_interpretation:
            item["interpretation"] = llm_interpretation
            item["show_summary"] = _should_show_summary(
                item.get("summary", ""), llm_interpretation
            )
    digest = _build_digest(
        stream_label=stream_label or stream_id or "Selected stream",
        strategy=STRATEGY_RADAR,
        days=days,
        recent_articles=recent_articles,
        candidate_items=candidate_items,
        theme_groups=theme_groups,
        must_read_items=must_read_items,
        skim_items=skim_items,
        clear_items=low_priority_items,
    )
    summary = digest["headline"]

    markdown = render_stream_overview_markdown(
        strategy=STRATEGY_RADAR,
        stream_label=stream_label or stream_id or "Selected stream",
        days=days,
        article_count=len(recent_articles),
        summary=summary,
        theme_groups=theme_groups,
        worth_expanding_items=must_read_items,
        worth_expanding_overflow_count=overflow_count,
        low_priority_items=low_priority_items,
        digest=digest,
    )

    return {
        "strategy": STRATEGY_RADAR,
        "stream_id": stream_id,
        "stream_label": stream_label,
        "days": days,
        "article_count": len(recent_articles),
        "summary": summary,
        "theme_groups": theme_groups,
        "worth_expanding_items": must_read_items,
        "worth_expanding_overflow_count": overflow_count,
        "low_priority_items": low_priority_items,
        "mark_read_candidates": [item["id"] for item in low_priority_items if item.get("id")],
        "markdown": markdown,
        "digest": digest,
    }


def generate_quick_clear_overview(
    articles: list[dict],
    *,
    stream_id: str | None = None,
    stream_label: str | None = None,
    days: int = 3,
) -> dict:
    recent_articles = filter_recent_articles(articles, days)
    matched = [article for article in recent_articles if is_newsflash(article)]
    remaining = [article for article in recent_articles if not is_newsflash(article)]
    low_priority_items = [
        _article_preview(article, "newsflash", True) for article in matched
    ]
    must_read_items = [
        _article_preview(article, "remaining", False) for article in remaining[:10]
    ]
    must_read_items, overflow_count = _select_must_read_items(must_read_items)
    skim_items = _pick_skim_items(
        [_article_preview(article, "remaining", False) for article in remaining],
        must_read_items,
    )
    llm_candidate_interpretations = _llm_interpret_candidates(must_read_items)
    for item in must_read_items:
        llm_interpretation = llm_candidate_interpretations.get(str(item.get("id")))
        if llm_interpretation:
            item["interpretation"] = llm_interpretation
            item["show_summary"] = _should_show_summary(
                item.get("summary", ""), llm_interpretation
            )
    digest = _build_digest(
        stream_label=stream_label or stream_id or "Selected stream",
        strategy=STRATEGY_QUICK_CLEAR,
        days=days,
        recent_articles=recent_articles,
        candidate_items=[_article_preview(article, "remaining", False) for article in remaining],
        theme_groups=[],
        must_read_items=must_read_items,
        skim_items=skim_items,
        clear_items=low_priority_items,
    )
    summary = (
        f"{stream_label or stream_id or 'Selected stream'} 最近 {days} 天共有 "
        f"{len(recent_articles)} 条未读，其中 {len(matched)} 条属于可快速清理的快讯。"
    )
    digest["headline"] = summary

    markdown = render_stream_overview_markdown(
        strategy=STRATEGY_QUICK_CLEAR,
        stream_label=stream_label or stream_id or "Selected stream",
        days=days,
        article_count=len(recent_articles),
        summary=summary,
        theme_groups=[],
        worth_expanding_items=must_read_items,
        worth_expanding_overflow_count=overflow_count,
        low_priority_items=low_priority_items,
        digest=digest,
    )

    return {
        "strategy": STRATEGY_QUICK_CLEAR,
        "stream_id": stream_id,
        "stream_label": stream_label,
        "days": days,
        "article_count": len(recent_articles),
        "summary": summary,
        "theme_groups": [],
        "worth_expanding_items": must_read_items,
        "worth_expanding_overflow_count": overflow_count,
        "low_priority_items": low_priority_items,
        "mark_read_candidates": [item["id"] for item in low_priority_items if item.get("id")],
        "markdown": markdown,
        "digest": digest,
    }


def generate_stream_overview(
    articles: list[dict],
    *,
    stream_id: str | None = None,
    stream_label: str | None = None,
    strategy: str | None = None,
    days: int = 3,
) -> dict:
    final_strategy = strategy or determine_stream_strategy(stream_id, stream_label)
    if final_strategy == STRATEGY_QUICK_CLEAR:
        return generate_quick_clear_overview(
            articles,
            stream_id=stream_id,
            stream_label=stream_label,
            days=days,
        )
    return generate_radar_overview(
        articles,
        stream_id=stream_id,
        stream_label=stream_label,
        days=days,
    )


def render_stream_overview_markdown(
    *,
    strategy: str,
    stream_label: str,
    days: int,
    article_count: int,
    summary: str,
    theme_groups: list[dict],
    worth_expanding_items: list[dict],
    worth_expanding_overflow_count: int,
    low_priority_items: list[dict],
    digest: dict | None = None,
) -> str:
    if digest:
        lines = [
            f"# Stream Daily Digest - {stream_label}",
            "",
            f"- 策略: `{strategy}`",
            f"- 时间窗口: 最近 {days} 天",
            f"- 文章数: {article_count}",
            "",
            "## Executive Summary",
            digest.get("headline", summary),
            "",
            digest.get("executive_summary", ""),
            "",
        ]

        top_themes = digest.get("top_themes", [])
        if top_themes:
            lines.append("## Topic Radar")
            for group in top_themes:
                lines.append(
                    f"- **{group['bucket']}** ({group['count']}) - {group['summary']}"
                )
            lines.append("")

        lines.append("## Must Read")
        deep_reads = digest.get("deep_analyzed_reads") or digest.get("must_read_candidates", [])
        if deep_reads:
            for item in deep_reads:
                title = item.get("title", "Untitled")
                link = item.get("link", "")
                if link:
                    lines.append(f"- [{title}]({link})")
                else:
                    lines.append(f"- {title}")
                if item.get("analysis_summary"):
                    lines.append(f"  - 分析: {item['analysis_summary']}")
                elif item.get("interpretation"):
                    lines.append(f"  - 解读: {item['interpretation']}")
                if item.get("score") is not None:
                    lines.append(f"  - 评分: {item['score']}/5.0")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Skim")
        skim_items = digest.get("skim_items", [])
        if skim_items:
            for item in skim_items:
                title = item.get("title", "Untitled")
                link = item.get("link", "")
                if link:
                    lines.append(f"- [{title}]({link})")
                else:
                    lines.append(f"- {title}")
                if item.get("interpretation"):
                    lines.append(f"  - 解读: {item['interpretation']}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Clear")
        clear_items = digest.get("clear_items", [])
        if clear_items:
            for item in clear_items[:20]:
                title = item.get("title", "Untitled")
                link = item.get("link", "")
                if link:
                    lines.append(f"- [{title}]({link})")
                else:
                    lines.append(f"- {title}")
            if len(clear_items) > 20:
                lines.append(f"- 其余 {len(clear_items) - 20} 条可继续批量清理")
        else:
            lines.append("- None")
        lines.append("")

        actions = digest.get("actions", [])
        if actions:
            lines.append("## Suggested Actions")
            for action in actions:
                lines.append(f"- {action}")
            lines.append("")

        return "\n".join(lines) + "\n"

    lines = [
        f"# Stream 总览 - {stream_label}",
        "",
        f"- 策略: `{strategy}`",
        f"- 时间窗口: 最近 {days} 天",
        f"- 文章数: {article_count}",
        "",
        "## 总体判断",
        summary,
        "",
    ]

    if theme_groups:
        lines.append("## 主题雷达")
        for group in theme_groups:
            lines.append(
                f"- **{group['bucket']}** ({group['count']}) - {group['summary']}"
            )
            for item in group["representatives"]:
                lines.append(f"  - {item['title']}")
        lines.append("")

    lines.append("## 值得展开看")
    if worth_expanding_items:
        for item in worth_expanding_items:
            title = item["title"]
            link = item.get("link", "")
            interpretation = item.get("interpretation", "")
            item_summary = item.get("summary", "")
            if link:
                lines.append(f"- [{title}]({link})")
            else:
                lines.append(f"- {title}")
            if interpretation:
                lines.append(f"  - 解读: {interpretation}")
            if item_summary and item.get("show_summary", True):
                lines.append(f"  - 摘要: {item_summary[:160]}")
        if worth_expanding_overflow_count:
            lines.append(
                f"- 其余 {worth_expanding_overflow_count} 条保留在主题雷达中，不再单独展开"
            )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def save_stream_overview_markdown(
    markdown: str,
    *,
    stream_label: str | None,
    strategy: str,
) -> str:
    now = datetime.now()
    output_dir = Path("output") / now.strftime("%Y-%m")
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_label = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "_", stream_label or "stream")
    safe_label = safe_label.strip("_") or "stream"
    filename = (
        f"stream_{strategy}_{safe_label}_{now.strftime('%Y%m%d_%H%M%S')}.md"
    )
    path = output_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return os.fspath(path)
