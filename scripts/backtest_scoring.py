#!/usr/bin/env python3
"""
Run scoring backtests against a local article dump such as output/unread_news.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_BACKTEST_CONFIG = PROJECT_ROOT / "scripts" / "backtest_scoring.local.json"

from rss_analyzer.config import (
    LATEST_UNREAD_FILE,
    PROJ_CONFIG,
    get_openai_task_config,
    setup_logging,
)
from rss_analyzer.scoring import score_article, score_articles_batch
from rss_analyzer.utils import load_articles, strip_html_tags

logger = logging.getLogger(__name__)


def _parse_target_spec(spec: str) -> dict:
    parts = [part.strip() for part in spec.split("|")]
    if len(parts) != 4 or any(not part for part in parts):
        raise ValueError(
            "Invalid --target format. Expected: label|model|base_url|api_key_env"
        )

    label, model, base_url, api_key_token = parts
    api_key = os.getenv(api_key_token) or api_key_token

    return {
        "label": label,
        "model": model,
        "base_url": base_url,
        "api_key_env": api_key_token if os.getenv(api_key_token) else None,
        "api_key": api_key,
    }


def _load_backtest_config(path: str | None) -> dict:
    config_path = Path(path) if path else DEFAULT_BACKTEST_CONFIG
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Backtest config must be a JSON object")
    return data


def _resolve_content(article: dict) -> str:
    content = strip_html_tags(article.get("content", "") or "")
    if content:
        return content
    return strip_html_tags(article.get("summary", "") or "")


def _score_band(score: float) -> str:
    if score >= 4.2:
        return "4.2+"
    if score >= 3.6:
        return "3.6-4.1"
    if score >= 3.0:
        return "3.0-3.5"
    if score >= 2.0:
        return "2.0-2.9"
    return "<2.0"


def _select_articles(
    articles: list[dict],
    *,
    limit: int,
    offset: int,
    origin_filter: str | None,
) -> list[dict]:
    selected = articles
    if origin_filter:
        origin_filter_lower = origin_filter.lower()
        selected = [
            article
            for article in selected
            if origin_filter_lower in (article.get("origin", "") or "").lower()
        ]

    if offset:
        selected = selected[offset:]
    if limit > 0:
        selected = selected[:limit]
    return selected


def _score_batch(batch: list[dict]) -> list[dict]:
    payload = [
        {
            "title": article.get("title", ""),
            "summary": strip_html_tags(article.get("summary", "") or ""),
            "content": _resolve_content(article),
        }
        for article in batch
    ]
    results = score_articles_batch(payload)
    if not results:
        return [
            score_article(
                article.get("title", ""),
                strip_html_tags(article.get("summary", "") or ""),
                _resolve_content(article),
            )
            for article in batch
        ]
    return results


@contextmanager
def _temporary_analysis_target(target: dict):
    env_map = {
        "ANALYSIS_OPENAI_MODEL": target["model"],
        "OPENAI_BASE_URL": target["base_url"],
        "OPENAI_API_KEY": target["api_key"],
    }
    originals = {key: os.environ.get(key) for key in env_map}
    for key, value in env_map.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, original in originals.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


def _backtest_articles(
    articles: list[dict], batch_size: int, target: dict
) -> list[dict]:
    scored_rows: list[dict] = []
    total = len(articles)
    label = target["label"]

    with _temporary_analysis_target(target):
        for start in range(0, total, batch_size):
            batch = articles[start : start + batch_size]
            logger.info(
                "Backtest[%s]: scoring batch %s-%s/%s",
                label,
                start + 1,
                min(start + len(batch), total),
                total,
            )
            results = _score_batch(batch)
            for article, result in zip(batch, results):
                scored_rows.append(
                    {
                        "id": article.get("id"),
                        "title": article.get("title", ""),
                        "origin": article.get("origin", ""),
                        "link": article.get("link", ""),
                        "published": article.get("published"),
                        "score": result.get("overall_score", 0.0),
                        "weighted_score": result.get("weighted_score"),
                        "verdict": result.get("verdict", ""),
                        "article_type": result.get("article_type", "default"),
                        "reason": result.get("reason", ""),
                        "why_not_higher": result.get("why_not_higher", ""),
                        "negative_signals": result.get("negative_signals", []),
                        "red_flags": result.get("red_flags", []),
                        "model": target["model"],
                        "label": label,
                        "base_url": target["base_url"],
                    }
                )

    return scored_rows


def _build_report(rows: list[dict], source_file: str, target: dict) -> dict:
    score_bands = Counter(_score_band(float(row.get("score", 0.0))) for row in rows)
    article_types = Counter(row.get("article_type", "default") for row in rows)
    origins = Counter(row.get("origin", "") or "Unknown" for row in rows)
    negative_signals = Counter(
        signal for row in rows for signal in row.get("negative_signals", [])
    )
    red_flags = Counter(flag for row in rows for flag in row.get("red_flags", []))

    scored_rows = sorted(rows, key=lambda row: row.get("score", 0.0), reverse=True)
    avg_score = round(
        sum(float(row.get("score", 0.0)) for row in rows) / max(1, len(rows)),
        2,
    )

    return {
        "generated_at": datetime.now().isoformat(),
        "source_file": source_file,
        "label": target["label"],
        "model": target["model"],
        "base_url": target["base_url"],
        "article_count": len(rows),
        "average_score": avg_score,
        "score_bands": dict(score_bands),
        "article_types": dict(article_types),
        "top_origins": dict(origins.most_common(10)),
        "negative_signals": dict(negative_signals.most_common(10)),
        "red_flags": dict(red_flags.most_common(10)),
        "top_articles": scored_rows[:10],
        "bottom_articles": list(reversed(scored_rows[-10:])),
        "rows": scored_rows,
    }


def _aggregate_repeat_reports(reports: list[dict], source_file: str, target: dict) -> dict:
    if len(reports) == 1:
        report = dict(reports[0])
        report["repeat_count"] = 1
        report["run_reports"] = reports
        report["stability"] = {"average_spread": 0.0, "largest_spreads": []}
        return report

    rows_by_run = [report["rows"] for report in reports]
    by_article: dict[str, list[dict]] = {}
    for rows in rows_by_run:
        for row in rows:
            by_article.setdefault(row["id"], []).append(row)

    aggregated_rows = []
    spreads = []
    for article_id, samples in by_article.items():
        scores = [float(sample.get("score", 0.0)) for sample in samples]
        mean_score = round(sum(scores) / len(scores), 2)
        min_score = round(min(scores), 2)
        max_score = round(max(scores), 2)
        spread = round(max_score - min_score, 2)
        variance = sum((score - mean_score) ** 2 for score in scores) / len(scores)
        stddev = round(math.sqrt(variance), 3)
        representative = max(samples, key=lambda sample: sample.get("score", 0.0))
        aggregated_rows.append(
            {
                **representative,
                "score": mean_score,
                "score_min": min_score,
                "score_max": max_score,
                "score_spread": spread,
                "score_stddev": stddev,
                "score_samples": scores,
            }
        )
        spreads.append(
            {
                "id": article_id,
                "title": representative.get("title", ""),
                "origin": representative.get("origin", ""),
                "score_samples": scores,
                "spread": spread,
                "stddev": stddev,
            }
        )

    aggregated = _build_report(aggregated_rows, source_file, target)
    spreads.sort(key=lambda item: item["spread"], reverse=True)
    aggregated["repeat_count"] = len(reports)
    aggregated["run_reports"] = reports
    aggregated["stability"] = {
        "average_spread": round(
            sum(item["spread"] for item in spreads) / max(1, len(spreads)), 3
        ),
        "largest_spreads": spreads[:15],
    }
    return aggregated


def _print_report(report: dict) -> None:
    print("\n=== Scoring Backtest Summary ===")
    print(f"Target: {report['label']}")
    print(f"Model: {report['model']}")
    print(f"Base URL: {report['base_url']}")
    print(f"Source: {report['source_file']}")
    print(f"Articles: {report['article_count']}")
    print(f"Average score: {report['average_score']}")
    if report.get("repeat_count", 1) > 1:
        print(f"Repeat count: {report['repeat_count']}")
        print(
            f"Average spread: {report.get('stability', {}).get('average_spread', 0.0)}"
        )

    print("\nScore bands:")
    for band in ("4.2+", "3.6-4.1", "3.0-3.5", "2.0-2.9", "<2.0"):
        print(f"  {band}: {report['score_bands'].get(band, 0)}")

    print("\nTop origins:")
    for origin, count in report["top_origins"].items():
        print(f"  {origin}: {count}")

    print("\nNegative signals:")
    for signal, count in report["negative_signals"].items():
        print(f"  {signal}: {count}")

    print("\nTop scored articles:")
    for item in report["top_articles"][:5]:
        spread_text = ""
        if "score_spread" in item:
            spread_text = f" | spread {item['score_spread']:.2f}"
        print(
            f"  {item['score']:.1f} | {item['origin']} | {item['title']} | {item['verdict']}{spread_text}"
        )

    if report.get("repeat_count", 1) > 1:
        print("\nMost unstable articles:")
        for item in report.get("stability", {}).get("largest_spreads", [])[:5]:
            sample_text = ", ".join(f"{score:.1f}" for score in item["score_samples"])
            print(
                f"  spread {item['spread']:.2f} | {item['origin']} | {item['title']}"
            )
            print(f"    samples: {sample_text}")


def _build_comparison(model_reports: list[dict]) -> dict:
    comparison_rows: list[dict] = []
    model_names = [report["label"] for report in model_reports]
    rows_by_model = {
        report["label"]: {row["id"]: row for row in report["rows"]} for report in model_reports
    }
    common_ids = set.intersection(*(set(rows.keys()) for rows in rows_by_model.values()))

    for article_id in common_ids:
        score_map = {
            model: float(rows_by_model[model][article_id].get("score", 0.0))
            for model in model_names
        }
        ordered_scores = list(score_map.values())
        spread = max(ordered_scores) - min(ordered_scores)
        first_row = rows_by_model[model_names[0]][article_id]
        comparison_rows.append(
            {
                "id": article_id,
                "title": first_row.get("title", ""),
                "origin": first_row.get("origin", ""),
                "score_by_model": score_map,
                "spread": round(spread, 2),
            }
        )

    comparison_rows.sort(key=lambda row: row["spread"], reverse=True)
    model_averages = {report["label"]: report["average_score"] for report in model_reports}
    return {
        "models": model_names,
        "article_count": len(common_ids),
        "average_score_by_model": model_averages,
        "largest_disagreements": comparison_rows[:15],
    }


def _print_comparison(comparison: dict) -> None:
    print("\n=== Model Comparison ===")
    print(f"Models: {', '.join(comparison['models'])}")
    print(f"Common articles: {comparison['article_count']}")
    print("Average scores:")
    for model, avg_score in comparison["average_score_by_model"].items():
        print(f"  {model}: {avg_score}")

    print("\nLargest disagreements:")
    for item in comparison["largest_disagreements"][:10]:
        score_text = ", ".join(
            f"{model}={score:.1f}" for model, score in item["score_by_model"].items()
        )
        print(f"  spread {item['spread']:.1f} | {item['origin']} | {item['title']}")
        print(f"    {score_text}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest current scoring logic.")
    parser.add_argument(
        "--config",
        help=(
            "Optional JSON config file for targets and default run settings. "
            f"If omitted, auto-loads {DEFAULT_BACKTEST_CONFIG.name} when present."
        ),
    )
    parser.add_argument(
        "--input",
        default=LATEST_UNREAD_FILE,
        help=f"Input article dump (default: {LATEST_UNREAD_FILE})",
    )
    parser.add_argument("--limit", type=int, default=30, help="How many articles to score")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N articles")
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Analysis model to backtest when all models share the same OPENAI_BASE_URL/API key.",
    )
    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="Full target spec: label|model|base_url|api_key_env. Repeat to compare multiple providers.",
    )
    parser.add_argument(
        "--origin-filter",
        help="Only score articles whose origin contains this substring",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=max(1, int(PROJ_CONFIG.get("batch_size", 10))),
        help="Batch size for score_articles_batch",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat each target multiple times to measure scoring drift.",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON output path. Defaults to output/scoring_backtests/<timestamp>.json",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.debug)
    config = _load_backtest_config(args.config)

    input_file = args.input if args.input != LATEST_UNREAD_FILE or not config.get("input") else config["input"]
    limit = args.limit if args.limit != 30 or "limit" not in config else int(config["limit"])
    offset = args.offset if args.offset != 0 or "offset" not in config else int(config["offset"])
    origin_filter = args.origin_filter if args.origin_filter is not None else config.get("origin_filter")
    batch_size = (
        args.batch_size
        if args.batch_size != max(1, int(PROJ_CONFIG.get("batch_size", 10))) or "batch_size" not in config
        else int(config["batch_size"])
    )
    repeat = args.repeat if args.repeat != 1 or "repeat" not in config else int(config["repeat"])
    output_override = args.output or config.get("output")

    articles = load_articles(input_file)
    selected = _select_articles(
        articles,
        limit=limit,
        offset=offset,
        origin_filter=origin_filter,
    )
    if not selected:
        print("No articles selected for backtest.")
        return 1

    logger.info("Backtest: selected %s articles from %s", len(selected), input_file)
    default_model = get_openai_task_config("analysis", default_model="gpt-4o-mini").model
    targets = []
    if args.targets:
        targets = [_parse_target_spec(spec) for spec in args.targets]
    elif config.get("targets"):
        targets = [_parse_target_spec(spec) for spec in config["targets"]]
    else:
        model_names = args.models or config.get("models") or [default_model]
        for model_name in model_names:
            targets.append(
                {
                    "label": model_name,
                    "model": model_name,
                    "base_url": os.getenv("OPENAI_BASE_URL", ""),
                    "api_key_env": "OPENAI_API_KEY",
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                }
            )

    reports = []

    for target in targets:
        run_reports = []
        for run_index in range(repeat):
            logger.info(
                "Backtest: running target %s using model %s @ %s (run %s/%s)",
                target["label"],
                target["model"],
                target["base_url"],
                run_index + 1,
                repeat,
            )
            rows = _backtest_articles(selected, max(1, batch_size), target)
            run_reports.append(_build_report(rows, input_file, target))

        report = _aggregate_repeat_reports(run_reports, input_file, target)
        _print_report(report)
        reports.append(report)

    comparison = _build_comparison(reports) if len(reports) > 1 else None
    if comparison:
        _print_comparison(comparison)

    output_path = Path(output_override) if output_override else (
        Path("output")
        / "scoring_backtests"
        / f"scoring_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "source_file": input_file,
        "reports": reports,
        "comparison": comparison,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
