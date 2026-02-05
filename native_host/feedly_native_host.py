#!/usr/bin/env python3
import json
import os
import struct
import sys
import traceback
import logging
from logging.handlers import TimedRotatingFileHandler


def setup_native_logging():
    """配置 Native Host 的日志系统：按日轮转，降噪，支持环境变量覆盖"""
    # 1. 确定日志目录和文件
    current_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.environ.get("RSS_NATIVE_LOG_DIR", os.path.join(current_dir, "logs"))
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            # 如果没法创建目录，就退回到当前目录
            log_dir = current_dir

    log_file = os.path.join(log_dir, "native_host.log")

    # 2. 确定日志级别 (默认 INFO)
    level_str = os.environ.get("RSS_NATIVE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    # 3. 配置 Handler (按日轮转，保留 7 天)
    handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    # 4. 配置 Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # 清除旧的 handlers (如果有)
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)

    # 5. 限制第三方库日志噪声
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    return log_file


# 在最开始调用
LOG_FILE = setup_native_logging()
logging.info("Native Host 启动...")
logging.debug(f"Python解释器: {sys.executable}")
logging.debug(f"当前工作目录: {os.getcwd()}")
logging.debug(f"系统路径: {sys.path}")

try:
    # 这一步是为了让它能找到上级目录的 rss_analyzer 包
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    # 设置数据库路径环境变量
    DB_PATH = os.path.join(PROJECT_ROOT, "rss_scores.db")
    os.environ["RSS_SCORES_DB"] = DB_PATH
    logging.info(f"设置 RSS_SCORES_DB: {DB_PATH}")

    from rss_analyzer.cache import get_cached_score, save_cached_score
    from rss_analyzer.article_fetcher import fetch_article_content
    from rss_analyzer.llm_analyzer import (
        analyze_article_with_llm,
        summarize_single_article,
        analyze_articles_with_llm_batch,
    )
    from rss_analyzer.vector_store import vector_store

    logging.info("成功导入 rss_analyzer 模块")
except Exception:
    logging.exception("导入模块失败！")
    sys.exit(1)


def _read_message():
    try:
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) == 0:
            logging.debug("stdin closed")
            return None
        if len(raw_length) != 4:
            logging.error(f"Invalid length header: {len(raw_length)} bytes")
            return None
        message_length = struct.unpack("<I", raw_length)[0]
        if message_length == 0:
            logging.warning("Message length is 0")
            return None
        message = sys.stdin.buffer.read(message_length)
        if not message:
            logging.error("Failed to read message body")
            return None
        try:
            decoded = json.loads(message.decode("utf-8"))
            return decoded
        except Exception as e:
            logging.error(f"JSON decode error: {e}")
            return None
    except Exception:
        logging.exception("Read message exception")
        return None


def _send_message(payload: dict):
    try:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
    except Exception:
        logging.exception("Send message exception")


def _perform_analysis(
    article_id: str, title: str, url: str | None, summary: str, content: str | None
) -> dict:
    """执行实时分析并保存缓存"""
    logging.info(f"Performing real-time analysis for {article_id}: {title}")

    # 1. 准备内容
    final_content = content or summary
    if url and (not content or len(content) < 200):
        logging.info(f"Fetching content from {url}...")
        fetched = fetch_article_content(url)
        if fetched and len(fetched) > 100:
            final_content = fetched
            logging.info(f"Fetched {len(fetched)} chars")
        else:
            logging.warning("Fetch failed or too short, using summary")

    # 2. 调用 LLM
    try:
        analysis = analyze_article_with_llm(title, summary, final_content)
        score = analysis.get("score", 0)

        # 3. 保存缓存
        save_cached_score(article_id, score, analysis)
        logging.info(f"Analysis complete. Score: {score}")

        return {"score": score, "data": analysis, "updated_at": None}
    except Exception as e:
        logging.error(f"Analysis failed: {e}")
        return None


def _normalize_item(article_id: str, cached: dict | None) -> dict:
    if not cached:
        return {
            "id": article_id,
            "score": None,
            "data": {},
            "updated_at": None,
            "found": False,
        }
    return {
        "id": article_id,
        "score": cached.get("score"),
        "data": cached.get("data") or {},
        "updated_at": cached.get("updated_at"),
        "found": True,
    }


def _handle_get_score(msg: dict) -> dict:
    article_id = msg.get("id")
    logging.debug(f"Handling get_score for: {article_id}")
    cached = get_cached_score(article_id)

    if not cached:
        # 如果请求中包含了元数据，尝试实时计算
        if msg.get("title"):
            result = _perform_analysis(
                article_id,
                msg.get("title"),
                msg.get("url"),
                msg.get("summary", ""),
                msg.get("content"),
            )
            if result:
                cached = result

    logging.debug(f"Cache result: {'Found' if cached else 'Not Found'}")
    return _normalize_item(article_id, cached)


def _handle_get_scores(msg: dict) -> dict:
    # msg['items'] 是 list[dict] 或 msg['ids'] 是 list[str]
    input_items = msg.get("items")
    ids = msg.get("ids")

    # 统一格式为 list[dict]
    items_to_process = []
    if input_items:
        items_to_process = input_items
    elif ids:
        items_to_process = [{"id": i} for i in ids]

    logging.info(f"Handling get_scores for {len(items_to_process)} items")

    results = {}
    missing_items = []

    # 1. 第一遍扫描：检查缓存，收集未命中的文章
    for item in items_to_process:
        # 兼容 dict 或 str
        if isinstance(item, str):
            item = {"id": item}

        article_id = item.get("id")
        if not article_id:
            continue

        cached = get_cached_score(article_id)

        # 如果缓存未命中，且有标题，则标记为需要分析
        if not cached and item.get("title"):
            missing_items.append(item)
        else:
            results[article_id] = _normalize_item(article_id, cached)

    # 2. 决定批处理还是单篇处理
    missing_count = len(missing_items)
    if missing_count == 0:
        return {"items": results}

    logging.info(f"Cache miss for {missing_count} articles. Threshold=10")

    if missing_count > 10:
        # === 批量处理模式 ===
        logging.info(f"Triggering BATCH analysis for {missing_count} articles...")
        try:
            # 准备数据给批量分析器
            analyzed_batch = analyze_articles_with_llm_batch(missing_items)

            # 匹配结果并保存缓存
            if analyzed_batch and len(analyzed_batch) == missing_count:
                for idx, analyzed in enumerate(analyzed_batch):
                    item = missing_items[idx]
                    article_id = item.get("id")

                    score = analyzed.get("score", 0)
                    save_cached_score(article_id, score, analyzed)

                    results[article_id] = _normalize_item(
                        article_id,
                        {"score": score, "data": analyzed, "updated_at": None},
                    )
                logging.info("Batch analysis completed successfully")
            else:
                logging.error(
                    "Batch analysis returned mismatching results, fallback to failed"
                )
                # 标记为失败，避免卡死
                for item in missing_items:
                    article_id = item.get("id")
                    results[article_id] = _normalize_item(article_id, None)

        except Exception as e:
            logging.error(f"Batch analysis exception: {e}")
            # 出错了也尽量返回能返回的
            for item in missing_items:
                article_id = item.get("id")
                if article_id not in results:
                    results[article_id] = _normalize_item(article_id, None)

    else:
        # === 单篇处理模式 (原有逻辑) ===
        logging.info(f"Triggering SINGLE analysis for {missing_count} articles...")
        for item in missing_items:
            article_id = item.get("id")
            logging.info(f"Analyzing single: {article_id}")

            analyzed = _perform_analysis(
                article_id,
                item.get("title"),
                item.get("url"),
                item.get("summary", ""),
                item.get("content"),
            )

            # 如果分析失败（返回None），analyzed就是None，_normalize_item会处理
            cached = analyzed
            results[article_id] = _normalize_item(article_id, cached)

    return {"items": results}


def _handle_analyze_article(msg: dict) -> dict:
    """处理单篇文章的显式分析请求"""
    article_id = msg.get("id")
    if not article_id:
        return {"error": "no_id"}

    result = _perform_analysis(
        article_id,
        msg.get("title", "Unknown"),
        msg.get("url"),
        msg.get("summary", ""),
        msg.get("content"),
    )

    if result:
        return _normalize_item(article_id, result)
    else:
        return {"error": "analysis_failed"}


def _handle_summarize_article(msg: dict) -> dict:
    """Handle on-demand summarization request"""
    article_id = msg.get("id")
    title = msg.get("title", "")
    content = msg.get("content", "")
    url = msg.get("url")

    logging.info(f"Handling summarize_article for {article_id}: {title}")

    # Ensure we have content
    final_content = content
    if url and (not content or len(content) < 200):
        logging.info(f"Fetching content for summary from {url}...")
        fetched = fetch_article_content(url)
        if fetched and len(fetched) > 100:
            final_content = fetched
            logging.info(f"Fetched {len(fetched)} chars for summary")

    if not final_content:
        return {"error": "no_content", "message": "Could not retrieve article content"}

    summary = summarize_single_article(final_content)

    # Update Cache if exists
    cached = get_cached_score(article_id)
    if cached:
        score = cached.get("score")
        data = cached.get("data") or {}
        data["summary"] = summary
        # If the original analysis didn't include a verdict/reason, we might want to keep it that way
        # or maybe add a note?
        # Just update summary is safe.
        save_cached_score(article_id, score, data)
        logging.info(f"Updated cache for {article_id} with new summary")

    return {"id": article_id, "summary": summary}


def _handle_semantic_search(msg: dict) -> dict:
    """Handle semantic search request"""
    query = msg.get("query")
    limit = msg.get("limit", 5)

    if not query:
        return {"error": "no_query", "message": "Query string is required"}

    logging.info(f"Handling semantic_search: query='{query}', limit={limit}")

    try:
        results = vector_store.search_similar(query, limit)
        return {"query": query, "results": results}
    except Exception as e:
        logging.error(f"Semantic search error: {e}")
        return {"error": "search_failed", "message": str(e)}


def _handle_get_article_tags(msg: dict) -> dict:
    """Handle request to get tags for an article"""
    article_id = msg.get("article_id")

    if not article_id:
        return {"error": "no_article_id", "message": "Article ID is required"}

    logging.info(f"Handling get_article_tags: article_id='{article_id}'")

    try:
        tags = vector_store.get_article_tags(article_id)
        return {
            "article_id": article_id,
            "tags": tags
        }
    except Exception as e:
        logging.error(f"Get article tags error: {e}")
        return {"error": "tags_failed", "message": str(e)}


def _handle_discover_trending_topics(msg: dict) -> dict:
    """Handle request to discover trending topics"""
    limit = msg.get("limit", 5)

    logging.info(f"Handling discover_trending_topics: limit={limit}")

    try:
        trending_topics = vector_store.discover_trending_topics(limit)
        return {
            "topics": trending_topics,
            "limit": limit
        }
    except Exception as e:
        logging.error(f"Discover trending topics error: {e}")
        return {"error": "trending_failed", "message": str(e)}


def _handle_health(_: dict) -> dict:
    return {"ok": True}


def _handle_message(msg: dict) -> dict:
    msg_type = msg.get("type")
    if msg_type == "get_score":
        return _handle_get_score(msg)
    if msg_type == "get_scores":
        return _handle_get_scores(msg)
    if msg_type == "analyze_article":
        return _handle_analyze_article(msg)
    if msg_type == "summarize_article":
        return _handle_summarize_article(msg)
    if msg_type == "semantic_search":
        return _handle_semantic_search(msg)
    if msg_type == "get_article_tags":
        return _handle_get_article_tags(msg)
    if msg_type == "discover_trending_topics":
        return _handle_discover_trending_topics(msg)
    if msg_type == "health":
        return _handle_health(msg)
    return {"error": "unknown_type"}


def main():
    logging.info("进入主循环")
    while True:
        msg = _read_message()
        if msg is None:
            break

        # 记录请求
        logging.debug(f"Received message: {json.dumps(msg, ensure_ascii=False)}")

        try:
            response = _handle_message(msg)
        except Exception as exc:
            logging.exception("处理消息时发生异常")
            response = {
                "error": "exception",
                "detail": str(exc),
                "trace": traceback.format_exc(limit=3),
            }

        # 记录响应
        logging.debug(f"Sending response: {json.dumps(response, ensure_ascii=False)}")

        _send_message(response)


if __name__ == "__main__":
    main()
