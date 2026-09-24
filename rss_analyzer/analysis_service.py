"""Unified article analysis orchestration and cache validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.cache import get_cached_score, save_cached_score
from rss_analyzer.config import PROJ_CONFIG, get_openai_task_config
from rss_analyzer.llm_analyzer import (
    analyze_article_with_llm,
    analyze_articles_with_llm_batch,
)


ANALYSIS_POLICY_VERSION = "2026-09-24-v1"


@dataclass(frozen=True)
class PreparedArticle:
    article_id: str
    title: str
    url: str
    summary: str
    content: str


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_analysis_fingerprint() -> str:
    """Identify the model and scoring policy that produced a result."""
    config = get_openai_task_config("analysis", default_model="gpt-4o-mini")
    return _stable_hash(
        {
            "policy_version": ANALYSIS_POLICY_VERSION,
            "model": config.model,
            "base_url": config.base_url,
            "persona": PROJ_CONFIG.get("scoring_persona", ""),
            "weights": PROJ_CONFIG.get("scoring_weights", {}),
        }
    )


def build_content_hash(article: PreparedArticle) -> str:
    return _stable_hash(
        {
            "title": article.title,
            "summary": article.summary,
            "content": article.content,
        }
    )


def _article_url(article: dict) -> str:
    if article.get("url"):
        return article["url"]
    if article.get("link"):
        return article["link"]
    if article.get("canonicalUrl"):
        return article["canonicalUrl"]
    alternate = article.get("alternate") or []
    if alternate and isinstance(alternate[0], dict):
        return alternate[0].get("href", "")
    return ""


class ArticleAnalysisService:
    """Own content preparation, cache validity, analysis, and persistence."""

    def __init__(
        self,
        *,
        fetch_content: Callable[[str], str] = fetch_article_content,
        analyze_one: Callable[[str, str, str], dict] = analyze_article_with_llm,
        analyze_batch: Callable[[list[dict]], list[dict]] = analyze_articles_with_llm_batch,
        cache_get: Callable[..., dict | None] = get_cached_score,
        cache_save: Callable[[str, float, dict], None] = save_cached_score,
    ) -> None:
        self._fetch_content = fetch_content
        self._analyze_one = analyze_one
        self._analyze_batch = analyze_batch
        self._cache_get = cache_get
        self._cache_save = cache_save

    def prepare(self, article: dict) -> PreparedArticle:
        title = str(article.get("title") or "")
        summary = str(article.get("summary") or "")
        content = str(article.get("content") or "")
        url = _article_url(article)

        if not (content and len(content) > 200):
            if len(summary) > 500:
                content = summary
            elif url:
                content = self._fetch_content(url) or summary
            else:
                content = summary

        return PreparedArticle(
            article_id=str(article.get("id") or ""),
            title=title,
            url=url,
            summary=summary,
            content=content,
        )

    def analyze(self, article: dict, *, use_cache: bool = True) -> dict:
        prepared = self.prepare(article)
        return self.analyze_prepared(prepared, use_cache=use_cache)

    def analyze_prepared(
        self,
        article: PreparedArticle,
        *,
        use_cache: bool = True,
    ) -> dict:
        fingerprint = build_analysis_fingerprint()
        content_hash = build_content_hash(article)
        if use_cache and article.article_id:
            cached = self._cache_get(
                article.article_id,
                analysis_fingerprint=fingerprint,
                content_hash=content_hash,
            )
            if cached:
                return cached["data"]

        result = self._analyze_one(article.title, article.summary, article.content)
        return self._persist_success(article, result, fingerprint, content_hash)

    def analyze_many_prepared(
        self,
        articles: list[PreparedArticle],
        *,
        use_cache: bool = True,
    ) -> list[dict]:
        fingerprint = build_analysis_fingerprint()
        results: list[dict | None] = [None] * len(articles)
        pending: list[tuple[int, PreparedArticle, str]] = []

        for index, article in enumerate(articles):
            content_hash = build_content_hash(article)
            cached = None
            if use_cache and article.article_id:
                cached = self._cache_get(
                    article.article_id,
                    analysis_fingerprint=fingerprint,
                    content_hash=content_hash,
                )
            if cached:
                results[index] = cached["data"]
            else:
                pending.append((index, article, content_hash))

        if pending:
            raw_results = self._analyze_batch(
                [
                    {
                        "title": article.title,
                        "summary": article.summary,
                        "content": article.content,
                    }
                    for _, article, _ in pending
                ]
            )
            if len(raw_results) != len(pending):
                raise ValueError("Batch analysis result count does not match input count")
            for (index, article, content_hash), result in zip(pending, raw_results):
                results[index] = self._persist_success(
                    article,
                    result,
                    fingerprint,
                    content_hash,
                )

        if any(result is None for result in results):
            raise RuntimeError("Analysis service left an input without a result")
        return list(results)  # type: ignore[return-value]

    def _persist_success(
        self,
        article: PreparedArticle,
        result: dict,
        fingerprint: str,
        content_hash: str,
    ) -> dict:
        enriched = {
            **result,
            "title": result.get("title") or article.title,
            "url": result.get("url") or article.url,
            "content": result.get("content") or article.content,
            "analysis_fingerprint": fingerprint,
            "content_hash": content_hash,
            "analysis_policy_version": ANALYSIS_POLICY_VERSION,
        }
        if (
            enriched.get("status", "success") == "success"
            and enriched.get("score") is not None
            and article.article_id
        ):
            self._cache_save(article.article_id, enriched["score"], enriched)
        return enriched


analysis_service = ArticleAnalysisService()
