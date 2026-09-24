"""Feedly stream overview and batch-reading workflows."""

from __future__ import annotations

import concurrent.futures
import json
import logging
from typing import Callable

from rss_analyzer.analysis_service import ArticleAnalysisService, PreparedArticle
from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.cache import (
    get_app_cache,
    get_cached_score,
    save_cached_score,
    set_app_cache,
)
from rss_analyzer.config import PROJ_CONFIG
from rss_analyzer.filter_workflows import (
    fetch_filter_articles,
    mark_article_ids_as_read,
)
from rss_analyzer.llm_analyzer import (
    analyze_article_with_llm,
    analyze_articles_with_llm_batch,
)
from rss_analyzer.readflow_triage import (
    article_summary_snippet,
    build_readflow_triage_prompt,
    coerce_readflow_decision,
    normalize_readflow_domain,
    parse_readflow_triage_results,
)
from rss_analyzer.stream_strategy import (
    determine_stream_strategy,
    generate_stream_overview,
    render_stream_overview_markdown,
    save_stream_overview_markdown,
)


logger = logging.getLogger(__name__)
BATCH_TRIAGE_CACHE_VERSION = 1
BATCH_READ_FETCH_LIMIT = 9999
ProgressCallback = Callable[[dict], None]


def _emit_progress(
    callback: ProgressCallback | None,
    event: str,
    **payload,
) -> None:
    if callback:
        callback({"event": event, **payload})


def _get_analysis_service() -> ArticleAnalysisService:
    return ArticleAnalysisService(
        fetch_content=fetch_article_content,
        analyze_one=analyze_article_with_llm,
        analyze_batch=analyze_articles_with_llm_batch,
        cache_get=get_cached_score,
        cache_save=save_cached_score,
    )


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _prepare_article_analysis_inputs(article: dict) -> tuple[str, str]:
    content = article.get("content", "") or ""
    summary = article.get("summary", "") or ""
    link = article.get("link")

    if content and len(content) > 200:
        return summary, content

    if summary and len(summary) > 500:
        return summary, summary

    if link:
        fetched_content = fetch_article_content(link)
        if fetched_content:
            return summary, fetched_content

    return summary, content or summary


def _truncate_title(title: str | None, limit: int = 72) -> str:
    text = (title or "").strip() or "Untitled"
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _deep_analysis_log_step(total: int) -> int:
    if total <= 5:
        return 1
    if total <= 12:
        return 2
    return 5


def _deep_analyze_digest_candidate(item: dict) -> tuple[str, dict]:
    summary, content = _prepare_article_analysis_inputs(item)
    enriched = dict(item)
    enriched["openable"] = bool(item.get("link"))

    if not content and not summary:
        return "skipped", enriched

    analysis = _get_analysis_service().analyze_prepared(
        PreparedArticle(
            article_id=str(item.get("id") or ""),
            title=item.get("title", ""),
            url=item.get("link", ""),
            summary=summary,
            content=content,
        )
    )
    if analysis.get("status", "success") != "success":
        enriched["analysis"] = analysis
        enriched["analysis_error"] = analysis.get("error")
        return "failed", enriched
    enriched["score"] = analysis.get("score")
    enriched["verdict"] = analysis.get("verdict")
    enriched["analysis_summary"] = analysis.get("summary")
    enriched["reason"] = analysis.get("reason")
    enriched["analysis"] = analysis
    return "analyzed", enriched


def _deep_analyze_digest_candidates(items: list[dict]) -> list[dict]:
    if not items:
        return []

    total = len(items)
    max_workers = max(1, int(PROJ_CONFIG.get("max_workers", 3)))
    log_step = _deep_analysis_log_step(total)
    logger.info(
        "Process Stream: deep analyzing %s must-read candidates with %s workers...",
        total,
        max_workers,
    )

    analyzed_items: list[dict | None] = [None] * total
    completed = 0
    analyzed_count = 0
    skipped_count = 0
    failed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(_deep_analyze_digest_candidate, item): index
            for index, item in enumerate(items)
        }

        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            original_item = items[index]
            title = _truncate_title(original_item.get("title"))
            completed += 1

            try:
                status, enriched = future.result()
                analyzed_items[index] = enriched
                if status == "analyzed":
                    analyzed_count += 1
                elif status == "failed":
                    failed_count += 1
                else:
                    skipped_count += 1

                should_log_progress = (
                    log_step == 1
                    or completed == 1
                    or completed == total
                    or completed % log_step == 0
                )
                if status == "analyzed" and should_log_progress:
                    logger.info(
                        "Process Stream: [%s/%s] deep analyzed %s (score: %.1f)",
                        completed,
                        total,
                        title,
                        enriched.get("score", 0.0),
                    )
                elif status != "analyzed" and should_log_progress:
                    logger.info(
                        "Process Stream: [%s/%s] progress checkpoint at %s (%s)",
                        completed,
                        total,
                        title,
                        "content too short",
                    )
            except Exception as exc:
                logger.warning("Digest deep analysis failed for %s: %s", original_item.get("title"), exc)
                fallback_item = dict(original_item)
                fallback_item["openable"] = bool(original_item.get("link"))
                analyzed_items[index] = fallback_item
                failed_count += 1
                should_log_progress = (
                    log_step == 1
                    or completed == 1
                    or completed == total
                    or completed % log_step == 0
                )
                if should_log_progress:
                    logger.info(
                        "Process Stream: [%s/%s] progress checkpoint at %s (%s)",
                        completed,
                        total,
                        title,
                        "analysis failed",
                    )

    logger.info(
        "Process Stream: finished deep analysis for %s candidates (%s analyzed, %s skipped, %s failed).",
        total,
        analyzed_count,
        skipped_count,
        failed_count,
    )
    return [item for item in analyzed_items if item is not None]


def _mark_digest_openable(items: list[dict]) -> list[dict]:
    marked_items = []
    for item in items:
        enriched = dict(item)
        enriched["openable"] = bool(item.get("link"))
        marked_items.append(enriched)
    return marked_items


def _refresh_digest_metadata(digest: dict) -> dict:
    must_read_items = digest.get("deep_analyzed_reads", [])
    skim_items = digest.get("skim_items", [])
    clear_items = digest.get("clear_items", [])
    fetched_count = digest.get("stats", {}).get("fetched_count", 0)
    candidate_count = digest.get("stats", {}).get("candidate_count", 0)
    clear_ratio = (len(clear_items) / fetched_count) if fetched_count else 0.0

    actions = []
    if must_read_items:
        actions.append(f"先看 must-read 的 {len(must_read_items)} 篇重点文章。")
    if skim_items:
        actions.append(f"若时间有限，只抽样 skim 区里的 {min(3, len(skim_items))} 篇代表项。")
    if clear_items:
        actions.append(f"可批量已读 {len(clear_items)} 条低优先级或重复噪音内容。")

    digest["actions"] = actions
    digest["stats"] = {
        "fetched_count": fetched_count,
        "candidate_count": candidate_count,
        "must_read_count": len(must_read_items),
        "skim_count": len(skim_items),
        "clear_count": len(clear_items),
        "clear_ratio": clear_ratio,
    }
    return digest


def _rerank_digest_after_analysis(digest: dict) -> dict:
    retained_must_read: list[dict] = []
    demoted_to_skim: list[dict] = []
    demoted_to_clear: list[dict] = []

    for item in digest.get("deep_analyzed_reads", []):
        score = item.get("score")
        verdict = item.get("verdict", "")
        relevance = (
            item.get("analysis", {})
            .get("detailed_scores", {})
            .get("relevance", 0)
        )

        if score is None:
            retained_must_read.append(item)
            continue

        if score < 2.5 or relevance <= 1 or "不太值得" in verdict:
            demoted_to_clear.append(item)
            continue

        if score < 3.6:
            demoted_to_skim.append(item)
            continue

        retained_must_read.append(item)

    existing_skim = digest.get("skim_items", [])
    existing_clear = digest.get("clear_items", [])

    digest["deep_analyzed_reads"] = retained_must_read
    digest["must_read_candidates"] = retained_must_read
    digest["skim_items"] = _mark_digest_openable(demoted_to_skim + existing_skim)
    digest["clear_items"] = _mark_digest_openable(demoted_to_clear + existing_clear)
    return _refresh_digest_metadata(digest)



def process_stream(
    *,
    stream_id: str | None,
    stream_label: str | None = None,
    days: int = 3,
    limit: int = 500,
    strategy: str | None = None,
    export_markdown: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    _emit_progress(progress_callback, "phase", phase="fetching")
    articles = fetch_filter_articles(limit, stream_id=stream_id)
    resolved_strategy = strategy or determine_stream_strategy(stream_id, stream_label)
    _emit_progress(
        progress_callback,
        "progress",
        phase="building_overview",
        current=0,
        total=len(articles),
    )
    result = generate_stream_overview(
        articles,
        stream_id=stream_id,
        stream_label=stream_label,
        strategy=resolved_strategy,
        days=days,
    )
    result["fetched_count"] = len(articles)

    digest = dict(result.get("digest") or {})
    digest["must_read_candidates"] = _mark_digest_openable(
        digest.get("must_read_candidates", [])
    )
    digest["skim_items"] = _mark_digest_openable(digest.get("skim_items", []))
    digest["clear_items"] = _mark_digest_openable(digest.get("clear_items", []))
    deep_candidates = digest.get("must_read_candidates", [])
    _emit_progress(
        progress_callback,
        "progress",
        phase="deep_analysis",
        current=0,
        total=len(deep_candidates),
    )
    digest["deep_analyzed_reads"] = _deep_analyze_digest_candidates(
        deep_candidates
    )
    digest = _rerank_digest_after_analysis(digest)
    result["digest"] = digest
    result["worth_expanding_items"] = digest.get("deep_analyzed_reads", [])
    result["low_priority_items"] = digest.get("clear_items", result.get("low_priority_items", []))
    result["mark_read_candidates"] = [
        item["id"] for item in digest.get("clear_items", []) if item.get("id")
    ]
    result["summary"] = digest.get("headline", result.get("summary", ""))
    result["markdown"] = render_stream_overview_markdown(
        strategy=result["strategy"],
        stream_label=stream_label or stream_id or "Selected stream",
        days=days,
        article_count=result["article_count"],
        summary=result["summary"],
        theme_groups=result.get("theme_groups", []),
        worth_expanding_items=result.get("worth_expanding_items", []),
        worth_expanding_overflow_count=result.get("worth_expanding_overflow_count", 0),
        low_priority_items=result.get("low_priority_items", []),
        digest=digest,
    )

    if export_markdown:
        result["overview_file"] = save_stream_overview_markdown(
            result["markdown"],
            stream_label=stream_label or stream_id,
            strategy=result["strategy"],
        )

    _emit_progress(
        progress_callback,
        "progress",
        phase="completed",
        current=len(articles),
        total=len(articles),
    )
    return result


def _article_summary_snippet(article: dict, limit: int = 800) -> str:
    return article_summary_snippet(article, limit)


def _extract_json_array(raw: str) -> list:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or start >= end:
        raise ValueError("no JSON array found")
    json_str = text[start : end + 1]
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as exc:
        # Attempt to fix common LLM JSON errors
        logger.debug("Initial JSON parse failed: %s, attempting recovery", exc)
        import re

        # Fix Chinese colons (：) to regular colons (:)
        fixed = json_str.replace("：", ":")
        # Fix double colons pattern: "key":": "value" → "key": "value"
        fixed = re.sub(r'":\s*"\s*:\s*"', '": "', fixed)
        # Fix missing commas between } and { (most common LLM error)
        fixed = re.sub(r"\}\s*\n\s*\{", "},\n{", fixed)
        # Fix trailing commas before ] or }
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        try:
            parsed = json.loads(fixed)
        except json.JSONDecodeError:
            # Log the problematic region for debugging
            pos = getattr(exc, "pos", None)
            if pos is not None:
                snippet = json_str[max(0, pos - 100) : pos + 100]
                logger.warning("JSON parse error near position %d: ...%s...", pos, snippet)
            raise
    if not isinstance(parsed, list):
        raise ValueError("triage response is not a JSON array")
    return parsed


def _normalize_batch_domain(domain: str | None) -> str:
    return normalize_readflow_domain(domain)


def _coerce_batch_decision(decision: str | None, score: float) -> str:
    return coerce_readflow_decision(decision, score)


def _p2_keyword_hit(article: dict) -> bool:
    text = f"{article.get('title', '')} {_article_summary_snippet(article, 400)}".lower()
    keywords = (
        "地缘",
        "国际政治",
        "外交",
        "制裁",
        "关税",
        "战争",
        "停火",
        "冲突",
        "军援",
        "北约",
        "欧盟",
        "联合国",
        "白宫",
        "五角大楼",
        "国务院",
        "中东",
        "台海",
        "台湾",
        "乌克兰",
        "俄罗斯",
        "以色列",
        "伊朗",
        "哈马斯",
        "美国",
        "中国",
        "拜登",
        "特朗普",
        "普京",
    )
    return any(keyword in text for keyword in keywords)


def _fallback_batch_triage(article: dict, bucket: str | None = None) -> dict:
    is_p2 = bucket == "国际政治 / P2" or _p2_keyword_hit(article)
    summary = _article_summary_snippet(article, 400)
    domain = "P2" if is_p2 else "Other"
    score = 3.4 if is_p2 else 2.6
    decision = "skim" if is_p2 else "skim"
    return {
        "domain": domain,
        "domain_confidence": 0.65 if is_p2 else 0.35,
        "score": score,
        "decision": decision,
        "event": article.get("title", "Untitled"),
        "actors": "",
        "region": "",
        "core_fact": summary or article.get("title", "Untitled"),
        "why_it_matters": "需要快速判断是否有新增事实。" if is_p2 else "",
        "novelty": "unknown",
        "needs_deep_read": bool(is_p2 and len(summary) < 240 and article.get("link")),
        "rec": "P2 候选，需看事实增量" if is_p2 else "常规候选",
        "source": "fallback",
    }

def _cached_batch_triage(article: dict) -> dict | None:
    article_id = article.get("id", "")
    if not article_id:
        return None
    cached = get_app_cache(f"batch_triage:v{BATCH_TRIAGE_CACHE_VERSION}:{article_id}")
    if not cached:
        return None
    return dict(cached)


def _save_batch_triage(article: dict, triage: dict) -> None:
    article_id = article.get("id", "")
    if not article_id:
        return
    set_app_cache(
        f"batch_triage:v{BATCH_TRIAGE_CACHE_VERSION}:{article_id}",
        triage,
        ttl_seconds=14 * 24 * 60 * 60,
    )


def _build_batch_triage_prompt(articles: list[dict]) -> str:
    return build_readflow_triage_prompt(articles, max_summary_chars=800, max_content_chars=0)


def _parse_batch_triage_results(articles: list[dict], raw_items: list) -> dict[str, dict]:
    return parse_readflow_triage_results(articles, raw_items)


def _batch_triage_articles(
    articles: list[dict],
    chunk_size: int = 50,
    stats: dict | None = None,
) -> dict[str, dict]:
    """Triage all articles with title + origin + summary, chunked for latency."""
    from openai import OpenAI

    from rss_analyzer.config import (
        build_chat_completion_kwargs,
        build_openai_client_kwargs,
        get_openai_task_config,
    )

    if not articles:
        return {}

    cfg = get_openai_task_config("summary", "gpt-4o-mini")
    client = OpenAI(**build_openai_client_kwargs(cfg))
    final: dict[str, dict] = {}
    uncached: list[dict] = []

    for article in articles:
        cached = _cached_batch_triage(article)
        if cached:
            final[article.get("id", "")] = cached
        else:
            uncached.append(article)

    size = max(1, int(chunk_size or 50))
    llm_chunk_count = 0
    fallback_chunk_count = 0
    for chunk in _chunked(uncached, size):
        try:
            llm_chunk_count += 1
            resp = client.chat.completions.create(
                **build_chat_completion_kwargs(
                    cfg,
                    messages=[{"role": "user", "content": _build_batch_triage_prompt(chunk)}],
                    temperature=0.2,
                    max_tokens=8192,
                )
            )
            raw = resp.choices[0].message.content if resp.choices else ""
            parsed = _parse_batch_triage_results(chunk, _extract_json_array(raw))
            for article in chunk:
                aid = article.get("id", "")
                triage = parsed.get(aid) or _fallback_batch_triage(article)
                final[aid] = triage
                _save_batch_triage(article, triage)
        except Exception:
            fallback_chunk_count += 1
            logger.warning("Batch triage chunk failed; using fallback triage", exc_info=True)
            for article in chunk:
                aid = article.get("id", "")
                triage = _fallback_batch_triage(article)
                final[aid] = triage
                _save_batch_triage(article, triage)

    if stats is not None:
        stats.update(
            {
                "triage_cached_count": len(articles) - len(uncached),
                "triage_uncached_count": len(uncached),
                "llm_chunk_count": llm_chunk_count,
                "fallback_chunk_count": fallback_chunk_count,
                "llm_chunk_size": size,
            }
        )

    logger.info(
        "Batch triaged %s/%s articles (%s cached, %s LLM chunks)",
        len(final),
        len(articles),
        len(articles) - len(uncached),
        llm_chunk_count,
    )
    return final


def process_batch(
    *,
    stream_id: str | None,
    stream_label: str | None = None,
    batch_size: int = 100,
    days: int = 3,
) -> dict:
    """Process a single batch of unread articles for batch reading mode.

    Fetches the unread backlog, then triages every recent article in
    chunked LLM calls using title, source, and Feedly summary.  ``batch_size``
    controls LLM chunk size, not the number of articles fetched.
    """
    from rss_analyzer.stream_strategy import (
        _bucket_key,
        _is_low_priority,
        _prefilter_articles,
        _rank_article,
        filter_recent_articles,
    )

    articles = fetch_filter_articles(BATCH_READ_FETCH_LIMIT, stream_id=stream_id)
    if not articles:
        return {
            "success": True,
            "strategy": "batch",
            "article_count": 0,
            "fetched_count": 0,
            "summary": "No unread articles found.",
            "digest": None,
            "markdown": "",
        }

    recent = filter_recent_articles(articles, days)
    prefiltered_out, recent = _prefilter_articles(recent)

    logger.info("Batch triaging %s articles in chunks of %s...", len(recent), batch_size)
    triage_stats: dict = {}
    triage_map = _batch_triage_articles(recent, batch_size, stats=triage_stats)

    original_by_id = {a.get("id", ""): a for a in recent}
    grouped: dict[str, list[dict]] = {}
    clear_items: list[dict] = []
    all_candidates: list[dict] = []

    # Pre-filtered articles (keyword/URL/short) go directly to clear
    for article in prefiltered_out:
        clear_items.append({
            "id": article.get("id", ""),
            "title": article.get("title", "No Title"),
            "link": article.get("link", ""),
            "origin": article.get("origin", ""),
            "published": article.get("published", 0),
            "bucket": "prefiltered",
            "summary": _article_summary_snippet(article, 400),
            "low_priority": True,
            "score": 0.0,
            "interpretation": "关键词/URL/长度预筛命中",
            "domain": "Other",
            "domain_confidence": 1.0,
            "decision": "clear",
            "event": "",
            "actors": "",
            "region": "",
            "core_fact": "",
            "why_it_matters": "",
            "novelty": "repeat",
            "needs_deep_read": False,
        })

    for article in recent:
        bucket = _bucket_key(article, stream_label)
        aid = article.get("id", "")
        triage = triage_map.get(aid) or _fallback_batch_triage(article, bucket)
        if triage.get("domain") == "P2":
            bucket = "国际政治 / P2"
        is_low = _is_low_priority(article, bucket)
        preview = {
            "id": aid,
            "title": article.get("title", "No Title"),
            "link": article.get("link", ""),
            "origin": article.get("origin", ""),
            "published": article.get("published", 0),
            "bucket": bucket,
            "summary": _article_summary_snippet(article, 400),
            "low_priority": is_low,
            "score": triage.get("score"),
            "interpretation": triage.get("rec", ""),
            "domain": triage.get("domain", "Other"),
            "domain_confidence": triage.get("domain_confidence", 0.0),
            "decision": triage.get("decision", "skim"),
            "event": triage.get("event", ""),
            "actors": triage.get("actors", ""),
            "region": triage.get("region", ""),
            "core_fact": triage.get("core_fact", ""),
            "why_it_matters": triage.get("why_it_matters", ""),
            "novelty": triage.get("novelty", "unclear"),
            "needs_deep_read": triage.get("needs_deep_read", False),
        }
        if preview["decision"] == "clear" or (is_low and preview["domain"] != "P2"):
            clear_items.append(preview)
        else:
            grouped.setdefault(bucket, []).append(preview)
            all_candidates.append(preview)

    theme_groups = []
    for bucket, items in sorted(
        grouped.items(), key=lambda e: (-len(e[1]), e[0])
    ):
        sorted_items = sorted(
            items,
            key=lambda item: (float(item.get("score") or 0), _rank_article(item)),
            reverse=True,
        )
        theme_groups.append(
            {
                "bucket": bucket,
                "count": len(items),
                "low_priority_count": sum(1 for item in items if item.get("low_priority")),
                "summary": f"{len(items)} articles",
                "representatives": sorted_items[:3],
            }
        )

    p2_candidates = [item for item in all_candidates if item.get("domain") == "P2"]
    deep_inputs = []
    for preview in p2_candidates:
        if not preview.get("needs_deep_read"):
            continue
        original = original_by_id.get(preview.get("id", ""))
        if original:
            merged = dict(original)
            merged.update(preview)
            deep_inputs.append(merged)
        else:
            deep_inputs.append(preview)

    logger.info("Deep analyzing %s P2 candidates that need full text...", len(deep_inputs))
    deep_results = _deep_analyze_digest_candidates(deep_inputs)
    deep_by_id = {item.get("id", ""): item for item in deep_results}

    must_read: list[dict] = []
    skim: list[dict] = []
    demoted_clear: list[dict] = []

    for item in all_candidates:
        enriched = deep_by_id.get(item.get("id", ""), item)
        score = enriched.get("score")
        decision = enriched.get("decision", item.get("decision", "skim"))
        if item.get("id") in deep_by_id:
            if score is not None and score < 2.5:
                decision = "clear"
            elif score is not None and score < 3.6:
                decision = "skim"
            elif score is not None:
                decision = "must_read"
            enriched["decision"] = decision

        if decision == "clear":
            demoted_clear.append(enriched)
        elif decision == "must_read":
            must_read.append(enriched)
        else:
            skim.append(enriched)

    def _priority_key(item: dict) -> tuple:
        is_p2 = 1 if item.get("domain") == "P2" else 0
        needs_deep = 1 if item.get("needs_deep_read") else 0
        return (
            is_p2,
            float(item.get("score") or 0),
            needs_deep,
            _rank_article(item),
        )

    must_read.sort(key=_priority_key, reverse=True)
    skim.sort(key=_priority_key, reverse=True)

    clear_items = demoted_clear + clear_items

    p2_items = sorted(
        [deep_by_id.get(item.get("id", ""), item) for item in p2_candidates],
        key=_priority_key,
        reverse=True,
    )
    p2_must = [item for item in p2_items if item.get("decision") == "must_read"]
    p2_skim = [item for item in p2_items if item.get("decision") == "skim"]
    p2_clear = [item for item in clear_items if item.get("domain") == "P2"]
    p2_briefing = {
        "headline": (
            f"P2 命中 {len(p2_items) + len(p2_clear)} 条，"
            f"{len(p2_must)} 条建议优先点开，{len(deep_results)} 条已做正文复核。"
        ),
        "must_read": _mark_digest_openable(p2_must),
        "skim": _mark_digest_openable(p2_skim),
        "clear": _mark_digest_openable(p2_clear),
        "items": _mark_digest_openable(p2_items),
    }

    digest = {
        "headline": (
            f"{len(articles)} articles fetched, {len(recent)} in window, "
            f"{len(triage_map)} triaged, {len(deep_results)} P2 deep-analyzed"
        ),
        "executive_summary": p2_briefing["headline"],
        "top_themes": theme_groups,
        "must_read_candidates": _mark_digest_openable(must_read),
        "deep_analyzed_reads": _mark_digest_openable(must_read),
        "skim_items": _mark_digest_openable(skim),
        "clear_items": _mark_digest_openable(clear_items),
        "triage_items": _mark_digest_openable(all_candidates + clear_items),
        "p2_items": _mark_digest_openable(p2_items),
        "p2_briefing": p2_briefing,
        "actions": [],
        "stats": {
            "fetched_count": len(articles),
            "article_count": len(recent),
            "candidate_count": len(all_candidates),
            "must_read_count": len(must_read),
            "skim_count": len(skim),
            "clear_count": len(clear_items),
            "ai_scored_count": len(triage_map),
            "triage_count": len(triage_map),
            "p2_count": len(p2_items) + len(p2_clear),
            "p2_deep_analyzed_count": len(deep_results),
            **triage_stats,
        },
    }

    mark_read_candidates = [item["id"] for item in clear_items if item.get("id")]

    # Auto mark-read for low-score articles when threshold is configured
    auto_mark_threshold = PROJ_CONFIG.get("auto_mark_read_threshold", 0)
    auto_marked_result = None
    if auto_mark_threshold and mark_read_candidates:
        auto_marked_result = mark_articles_read(mark_read_candidates, dry_run=False)
        digest["auto_marked_read"] = auto_marked_result
        logger.info(
            "Auto marked %s clear articles as read (threshold=%.1f)",
            auto_marked_result.get("marked_count", 0),
            auto_mark_threshold,
        )

    return {
        "success": True,
        "strategy": "batch",
        "article_count": len(recent),
        "fetched_count": len(articles),
        "summary": digest["headline"],
        "digest": digest,
        "mark_read_candidates": mark_read_candidates,
        "auto_marked_read": auto_marked_result,
        "markdown": "",
    }


def mark_articles_read(article_ids: list[str], *, dry_run: bool = False) -> dict:
    """Mark a list of article IDs as read in Feedly.

    Returns a dict with success status and counts.
    """
    cleaned_ids = [aid for aid in article_ids if aid]
    if not cleaned_ids:
        return {"success": True, "marked_count": 0, "candidate_count": 0, "dry_run": dry_run}
    success = mark_article_ids_as_read(
        cleaned_ids, label="batch-read", dry_run=dry_run, mark_read=True
    )
    return {
        "success": success,
        "marked_count": len(cleaned_ids) if success and not dry_run else 0,
        "candidate_count": len(cleaned_ids),
        "dry_run": dry_run,
    }


def mark_stream_low_priority_read(article_ids: list[str], *, dry_run: bool = False) -> dict:
    cleaned_ids = [article_id for article_id in article_ids if article_id]
    success = mark_article_ids_as_read(
        cleaned_ids,
        label="low-priority",
        dry_run=dry_run,
        mark_read=True,
    )
    return {
        "success": success,
        "marked_count": len(cleaned_ids) if success and not dry_run else 0,
        "candidate_count": len(cleaned_ids),
        "dry_run": dry_run,
    }
