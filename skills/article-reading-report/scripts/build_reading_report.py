import argparse
import json
import logging
import math
import re
from collections import Counter
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.config import PROJ_CONFIG

logger = logging.getLogger(__name__)

FETCH_ERROR_PREFIXES = (
    "错误:",
    "获取失败:",
    "请求异常:",
    "处理异常:",
    "下载内容为空",
    "内容提取为空",
    "内容跳过:",
)

SOURCE_LABELS = {
    "fetched_body": "正文",
    "embedded_content": "RSS全文",
    "summary_fallback": "摘要回退",
    "failed": "抓取失败",
}

DEFAULT_CONFIG = {
    "min_content_chars": 600,
    "output_dir": "output/reading-reports",
}


def get_config():
    config = DEFAULT_CONFIG.copy()
    reading_report_config = PROJ_CONFIG.get("reading_report", {})
    config.update(reading_report_config)
    return config


CONFIG = get_config()


def load_articles(input_path: Path) -> list[dict[str, Any]]:
    try:
        logger.info(f"Loading articles from {input_path}")
        with input_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError("Input JSON must be a list of article objects")
        logger.info(f"Loaded {len(data)} articles")
        return data
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in input file: {e}")
        raise
    except ValueError as e:
        logger.error(f"Invalid input data: {e}")
        raise


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", strip_html(text)).strip()


def looks_like_fetch_error(text: str) -> bool:
    if not text:
        return True
    stripped = text.strip()
    return any(stripped.startswith(prefix) for prefix in FETCH_ERROR_PREFIXES)


def estimate_read_minutes(text: str) -> int:
    clean = normalize_text(text)
    if not clean:
        return 1
    return max(1, math.ceil(len(clean) / 900))


def classify_content_source(
    article: dict[str, Any], fetched_text: str, min_content_chars: int
) -> tuple[str, str, str | None]:
    embedded = normalize_text(article.get("content", ""))
    summary = normalize_text(article.get("summary", ""))
    fetched = normalize_text(fetched_text)

    if fetched and not looks_like_fetch_error(fetched) and len(fetched) >= min_content_chars:
        return fetched, "fetched_body", None

    if embedded and len(embedded) >= min_content_chars:
        return embedded, "embedded_content", "Used embedded content because fetch failed or was too short."

    if summary:
        note = "Fell back to RSS summary because full article fetching was unavailable or insufficient."
        return summary, "summary_fallback", note

    return "", "failed", "No usable article body or summary was available."


def prepare_article_record(
    article: dict[str, Any], min_content_chars: int, fetched_text: str | None = None
) -> dict[str, Any]:
    try:
        title = article.get("title", "")
        link = article.get("link", "")

        if fetched_text is None:
            fetched_text = fetch_article_content(link) if link else ""

        content, content_source, fallback_note = classify_content_source(
            article, fetched_text, min_content_chars
        )

        return {
            "title": title,
            "link": link,
            "origin": article.get("origin", ""),
            "published": article.get("published"),
            "summary": normalize_text(article.get("summary", "")),
            "content": content,
            "content_source": content_source,
            "content_source_label": SOURCE_LABELS.get(content_source, content_source),
            "content_chars": len(content),
            "estimated_read_minutes": estimate_read_minutes(content),
            "fallback_note": fallback_note,
        }
    except Exception as e:
        logger.error(f"Error processing article {article.get('title', 'Unknown')}: {e}")
        return {
            "title": article.get("title", ""),
            "link": article.get("link", ""),
            "origin": article.get("origin", ""),
            "published": article.get("published"),
            "summary": normalize_text(article.get("summary", "")),
            "content": f"处理异常: {str(e)}",
            "content_source": "failed",
            "content_source_label": "抓取失败",
            "content_chars": 0,
            "estimated_read_minutes": 0,
            "fallback_note": f"Error processing article: {str(e)}",
        }


def prepare_reading_packet(
    articles: list[dict[str, Any]], min_content_chars: int
) -> dict[str, Any]:
    logger.info(f"Preparing reading packet for {len(articles)} articles")
    records = []

    for index, article in enumerate(articles, start=1):
        logger.info(f"Processing article {index}/{len(articles)}")
        records.append(prepare_article_record(article, min_content_chars))

    source_counts = Counter(record["content_source_label"] for record in records)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_articles": len(records),
        "source_counts": dict(source_counts),
        "records": records,
    }


def escape_markdown_link_text(text: str) -> str:
    return text.replace("[", r"\[").replace("]", r"\]")


def render_sources_markdown(input_path: Path, packet: dict[str, Any]) -> str:
    lines = [
        "# Reading Sources",
        "",
        f"- Input file: `{input_path.name}`",
        f"- Generated at: {packet['generated_at']}",
        f"- Total articles: **{packet['total_articles']}**",
        "",
        "## Articles",
        "",
    ]

    for index, record in enumerate(packet["records"], start=1):
        title = record.get("title", "Untitled")
        safe_title = escape_markdown_link_text(title)
        link = record.get("link", "")
        title_line = f"### {index}. [{safe_title}]({link})" if link else f"### {index}. {safe_title}"
        lines.append(title_line)
        lines.append(
            f"- Evidence: **{record.get('content_source_label', '未知')}** | Read time: **{record.get('estimated_read_minutes', 1)} min** | Source: **{record.get('origin', '未知') or '未知'}**"
        )
        if record.get("fallback_note"):
            lines.append(f"- Note: {record['fallback_note']}")
        summary = record.get("summary", "")
        if summary:
            lines.append(f"- Summary: {summary[:180]}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return now.strftime("%Y%m%d-%H%M%S")


def save_outputs(output_dir: Path, input_path: Path, packet: dict[str, Any]) -> tuple[Path, Path]:
    logger.info(f"Saving reading outputs to {output_dir}")
    run_dir = output_dir / build_run_id()
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "reading-packet.json"
    md_path = run_dir / "reading-sources.md"

    payload = {
        "input_file": input_path.name,
        "run_id": run_dir.name,
        **packet,
    }

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(render_sources_markdown(input_path, packet))

    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a content-first reading packet from exported RSS JSON."
    )
    parser.add_argument("--input", required=True, help="Path to exported Feedly/RSS JSON file")
    parser.add_argument("--limit", type=int, default=None, help="Limit article count for preparation")
    parser.add_argument(
        "--min-content-chars",
        type=int,
        default=CONFIG["min_content_chars"],
        help="Minimum extracted body length before falling back to summary",
    )
    parser.add_argument(
        "--output-dir",
        default=CONFIG["output_dir"],
        help="Directory for generated outputs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)

    articles = load_articles(input_path)
    if args.limit:
        articles = articles[: args.limit]

    packet = prepare_reading_packet(articles, args.min_content_chars)
    json_path, md_path = save_outputs(output_dir, input_path, packet)

    print(f"Prepared {packet['total_articles']} articles")
    print(f"Packet output: {json_path}")
    print(f"Sources index: {md_path}")
    print("Next step: ask the agent to read the packet and write the final reading report.")


if __name__ == "__main__":
    main()
