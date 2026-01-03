#!/usr/bin/env python3
"""
RSS 文章分析器
使用 AI 分析 RSS 订阅文章，生成评分和摘要

使用方法：
    python article_analyzer.py [--refresh] [--limit N] [--mark-read] [--debug]

配置：
    修改 src/config.py 中的 PROJ_CONFIG 来调整默认设置
    修改 .env 文件来配置 API 密钥和 Profile
"""
import os
import argparse
import logging

# 导入模块
from rss_analyzer.config import PROJ_CONFIG, setup_logging
from rss_analyzer.feedly_client import feedly_fetch_unread, feedly_mark_read
from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.llm_analyzer import analyze_article_with_llm, generate_overall_summary
from rss_analyzer.utils import load_articles, save_articles

logger = logging.getLogger(__name__)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="AI Article Analyzer")
    
    parser.add_argument("--input", default=PROJ_CONFIG["input_file"], 
                        help=f"Input JSON file (default: {PROJ_CONFIG['input_file']})")
    parser.add_argument("--limit", type=int, default=PROJ_CONFIG["limit"], 
                        help=f"Number of articles to process (default: {PROJ_CONFIG['limit']})")
    parser.add_argument("--mark-read", action="store_true", default=PROJ_CONFIG["mark_read"], 
                        help=f"Mark processed articles as read (default: {PROJ_CONFIG['mark_read']})")
    parser.add_argument("--debug", action="store_true", default=PROJ_CONFIG["debug"], 
                        help=f"Enable debug mode (default: {PROJ_CONFIG['debug']})")
    parser.add_argument("--refresh", action="store_true", default=PROJ_CONFIG["refresh"], 
                        help=f"Refresh from Feedly before processing (default: {PROJ_CONFIG['refresh']})")

    args = parser.parse_args()

    # 设置日志级别
    debug_mode = args.debug or os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
    setup_logging(debug_mode)
    
    if debug_mode:
        logger.info("Debug模式已启用")

    # 刷新unread_news.json
    if args.refresh:
        logger.info("=" * 60)
        logger.info("📥 从 Feedly 刷新文章")
        logger.info("=" * 60)
        logger.info(f"正在获取最新 {args.limit} 篇未读文章...")
        articles = feedly_fetch_unread(limit=args.limit)
        if articles is None:
            logger.error("❌ 无法从 Feedly 获取文章，退出")
            return
        
        output_file = "unread_news.json"
        save_articles(articles, output_file)
        logger.info(f"✓ 已保存 {len(articles)} 篇未读文章到 {output_file}")
        logger.info("")
        
        if args.input == PROJ_CONFIG["input_file"]:
            args.input = output_file
    else:
        logger.info("=" * 60)
        logger.info("📂 使用本地文章数据（未刷新）")
        logger.info("=" * 60)
        logger.info(f"提示: 使用 --refresh 参数可从 Feedly 获取最新文章")
        logger.info("")

    # 确定输入文件
    input_file = args.input
    if not os.path.exists(input_file):
        logger.error(f"❌ 找不到输入文件: {input_file}")
        logger.info("提示: 使用 --refresh 参数从 Feedly 获取最新文章")
        return

    # 加载文章列表
    articles = load_articles(input_file)
    logger.info(f"📖 从 {input_file} 加载了 {len(articles)} 篇文章")
    logger.info(f"🎯 将处理前 {min(args.limit, len(articles))} 篇文章")
    logger.info("")
    
    analyzed_articles = []
    processed_ids = []
    seen_titles = set()
    
    # 处理每篇文章
    for idx, article in enumerate(articles[:args.limit], 1):
        logger.info(f"处理第 {idx}/{min(args.limit, len(articles))} 篇: {article['title']}")
        
        # 1. 关键词过滤 (Pre-filtering)
        filter_keywords = PROJ_CONFIG.get("filter_keywords", [])
        if any(kw in article['title'] for kw in filter_keywords):
            logger.info(f"  🚫 标题包含过滤词，跳过")
            continue
        
        # 1.2 URL模式过滤 (Pre-filtering)
        filter_url_patterns = PROJ_CONFIG.get("filter_url_patterns", [])
        article_url = article.get('link', '') or article.get('originId', '')
        if any(pattern in article_url for pattern in filter_url_patterns):
            logger.info(f"  🚫 URL匹配过滤规则 ({article_url})，跳过")
            continue
            
        # 1.3 简单去重 (Redundancy Filter)
        norm_title = "".join(filter(str.isalnum, article['title'].lower()))
        # 检查是否太短（防止像 "Update" 这种通用标题误杀），但 filter_keywords 应该已经覆盖了一些
        if len(norm_title) > 5: 
            if norm_title in seen_titles:
                logger.info(f"  🚫 标题重复 (Redundancy)，跳过")
                continue
            seen_titles.add(norm_title)

        # 优先使用已有的 content (例如来自测试数据或 RSS 全文)
        content = article.get('content', '')
        summary = article.get('summary', '')
        
        if content and len(content) > 200:
             logger.info(f"  ✓ 使用已有正文 ({len(content)} 字符)")
        elif summary and len(summary) > 500:
            logger.info(f"  ✓ 摘要较长 ({len(summary)} 字符)，跳过网页抓取")
            content = summary
        else:
            logger.info(f"  → 开始抓取网页内容...")
            fetched_content = fetch_article_content(article['link'])
            if fetched_content:
                content = fetched_content
            logger.info(f"  ✓ 抓取完成: {len(content)} 字符")
            
        # 2. 长度过滤 (Pre-filtering)
        min_length = PROJ_CONFIG.get("filter_min_length", 100)
        if len(content) < min_length:
            logger.info(f"  🚫 内容太短 ({len(content)} < {min_length})，跳过")
            continue
        
        analysis = analyze_article_with_llm(article['title'], summary, content)
        
        # 格式化输出 Verdict
        verdict = analysis.get('verdict', '未知')
        score = analysis['score']
        # 添加 Red Flag 标识
        if 'red_flags' in analysis.get('detailed_scores', {}) and analysis['detailed_scores']['red_flags']:
             red_flags = analysis['detailed_scores']['red_flags']
             logger.info(f"  ⚠️ 发现 Red Flags: {red_flags}")
             verdict = f"🚫 {verdict}"
            
        logger.info(f"  ✓ 评分: {score:.1f}/5.0 - {verdict}")
        logger.info(f"  ✓ 评价: {analysis.get('reason', '')}")
        if 'detailed_scores' in analysis:
            scores = analysis['detailed_scores']
            logger.info(f"     相关性:{scores['relevance']} 信息量:{scores['informativeness']} "
                       f"深度:{scores['depth']} 可读性:{scores['readability']} 原创性:{scores['originality']}")

        
        analyzed_articles.append({**article, "analysis": analysis})

        if article.get('id'):
            processed_ids.append(article['id'])
    
    # 生成带时间戳的文件名，按月份组织
    from datetime import datetime
    now = datetime.now()
    month_dir = now.strftime("%Y-%m")  # 例如: 2026-01
    output_dir = os.path.join("output", month_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    
    # 保存分析结果到归档目录
    analyzed_file = os.path.join(output_dir, f"analyzed_articles_{timestamp}.json")
    save_articles(analyzed_articles, analyzed_file)
    
    # 同时保存到根目录（为了兼容性和方便访问）
    save_articles(analyzed_articles, 'analyzed_articles.json')
    
    logger.info(f"\n分析结果已保存到:")
    logger.info(f"  - {analyzed_file}")
    logger.info(f"  - analyzed_articles.json (最新版本)")
    
    # 标记已读
    if args.mark_read and processed_ids:
        logger.info(f"\n正在标记 {len(processed_ids)} 篇文章为已读...")
        feedly_mark_read(processed_ids)
    
    # 生成总体摘要
    logger.info("\n生成总体摘要...")
    overall_summary = generate_overall_summary(analyzed_articles)
    
    # 生成带时间戳的文件名，按月份组织
    from datetime import datetime
    now = datetime.now()
    month_dir = now.strftime("%Y-%m")  # 例如: 2026-01
    output_dir = os.path.join("output", month_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    summary_file = os.path.join(output_dir, f"summary_{timestamp}.md")
    
    # 同时保存到最新版本（在根 output 目录）
    latest_file = os.path.join("output", "summary_latest.md")
    
    # 保存摘要（与 analyzed_articles 在同一目录）
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(overall_summary)
    with open(latest_file, 'w', encoding='utf-8') as f:
        f.write(overall_summary)
    
    logger.info(f"总体摘要已保存到:")
    logger.info(f"  - {summary_file}")
    logger.info(f"  - {latest_file}")
    logger.info(f"\n归档文件:")
    logger.info(f"  - {analyzed_file}")
    logger.info(f"  - {summary_file}")
    
    logger.info("\n" + "="*50)
    logger.info("总体摘要:")
    logger.info("="*50)
    logger.info(f"\n{overall_summary}")


if __name__ == "__main__":
    main()
