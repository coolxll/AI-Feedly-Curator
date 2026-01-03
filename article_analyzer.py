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
        logger.info("正在从 Feedly 获取未读文章...")
        articles = feedly_fetch_unread(limit=args.limit)
        if articles is None:
            logger.error("无法从 Feedly 获取文章，退出")
            return
        
        output_file = "unread_news.json"
        save_articles(articles, output_file)
        logger.info(f"已保存 {len(articles)} 篇未读文章到 {output_file}")
        
        if args.input == PROJ_CONFIG["input_file"]:
            args.input = output_file

    # 确定输入文件
    input_file = args.input
    if not os.path.exists(input_file):
        logger.error(f"找不到输入文件: {input_file}")
        logger.info("提示: 使用 --refresh 参数从 Feedly 获取最新文章")
        return

    # 加载文章列表
    articles = load_articles(input_file)
    logger.info(f"从 {input_file} 加载了 {len(articles)} 篇文章")
    
    analyzed_articles = []
    processed_ids = []
    
    # 处理每篇文章
    for idx, article in enumerate(articles[:args.limit], 1):
        logger.info(f"处理第 {idx} 篇: {article['title']}")
        
        summary = article.get('summary', '')
        if summary and len(summary) > 500:
            logger.info(f"  - 摘要较长({len(summary)}字符)，跳过抓取")
            content = summary
        else:
            content = fetch_article_content(article['link'])
            logger.info(f"  - 获取内容: {len(content)} 字符")
        
        analysis = analyze_article_with_llm(article['title'], summary, content)
        logger.info(f"  - 评分: {analysis['score']}/10")
        logger.info(f"  - 摘要: {analysis['summary'][:50]}...")
        
        analyzed_articles.append({**article, "analysis": analysis})

        if article.get('id'):
            processed_ids.append(article['id'])
    
    # 保存分析结果
    save_articles(analyzed_articles, 'analyzed_articles.json')
    logger.info("\n分析结果已保存到 analyzed_articles.json")
    
    # 标记已读
    if args.mark_read and processed_ids:
        logger.info(f"\n正在标记 {len(processed_ids)} 篇文章为已读...")
        feedly_mark_read(processed_ids)
    
    # 生成总体摘要
    logger.info("\n生成总体摘要...")
    overall_summary = generate_overall_summary(analyzed_articles)
    
    with open('articles_summary.md', 'w', encoding='utf-8') as f:
        f.write(overall_summary)
    logger.info("总体摘要已保存到 articles_summary.md")
    
    logger.info("\n" + "="*50)
    logger.info("总体摘要:")
    logger.info("="*50)
    logger.info(f"\n{overall_summary}")


def regenerate_summary():
    """重新生成总体摘要"""
    setup_logging()
    articles = load_articles('analyzed_articles.json')
    overall_summary = generate_overall_summary(articles)
    
    with open('articles_summary.md', 'w', encoding='utf-8') as f:
        f.write(overall_summary)
    print("总体摘要已重新生成并保存到 articles_summary.md")


if __name__ == "__main__":
    main()
