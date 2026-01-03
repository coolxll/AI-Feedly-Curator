import json
import requests
import os
import logging
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# === 用户配置区域 (方便IDE直接运行) ===
# 你可以在这里修改默认值，这样直接运行脚本时就会生效
PROJ_CONFIG = {
    "input_file": "unread_news.json",
    "limit": 100,
    "mark_read": True,  # 是否默认标记已读 (True/False)
    "debug": False,      # 是否默认开启Debug (True/False)
    "refresh": False,    # 是否默认刷新 (True/False)
    "proxy": "http://127.0.0.1:7890", # 代理服务器 (例如: "http://127.0.0.1:7890" 或从环境变量读取)
    
    # API Profile 配置 (指定使用哪个 profile)
    "analysis_profile": LOCAL_QWEN,  # 文章分析使用的 profile (例如: "local", "aliyun", None=使用默认)
    "summary_profile": LOCAL_QWEN,   # 总结生成使用的 profile (例如: "aliyun", "deepseek", None=使用默认)
}
# ==========================================

# 配置日志
logger = logging.getLogger(__name__)

def setup_logging(debug_mode=False):
    """配置日志系统"""
    level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 将HTTP请求日志设置为WARNING级别，避免干扰
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

def get_config(key, default=None, profile=None):
    """
    获取配置项，支持多环境配置切换。
    
    逻辑：
    1. 如果指定了 profile 参数，优先使用该 profile
    2. 否则检查环境变量 ACTIVE_PROFILE (例如: "local", "azure")
    3. 如果存在 profile，优先查找 {PROFILE}_{KEY} 的环境变量
    4. 如果未找到 profile 特有的配置，回退到默认 KEY
    
    参数：
        key: 配置键名
        default: 默认值
        profile: 指定使用的 profile (例如: "local", "aliyun")
    """
    # 优先使用传入的 profile，否则从环境变量读取
    active_profile = profile or os.getenv("ACTIVE_PROFILE")
    
    if active_profile:
        # 尝试查找带前缀的配置
        prefixed_key = f"{active_profile.upper()}_{key}"
        val = os.getenv(prefixed_key)
        if val is not None:
            return val
    
    # 回退到默认配置
    return os.getenv(key, default)

def log_debug(title, content):
    """Debug日志打印"""
    logger.debug(f"\n--- {title} ---\n{content}\n{'-' * 50}")

def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description="AI Article Analyzer")
    
    # 使用 PROJ_CONFIG 中的值作为默认值
    parser.add_argument("--input", default=PROJ_CONFIG["input_file"], help=f"Input JSON file (default: {PROJ_CONFIG['input_file']})")
    parser.add_argument("--limit", type=int, default=PROJ_CONFIG["limit"], help=f"Number of articles to process (default: {PROJ_CONFIG['limit']})")
    
    # 对于布尔值，我们需要特殊处理以支持从配置中默认开启
    # 如果配置中是True，我们需要提供 --no-xxx 选项来关闭
    # 这里为了简单，我们让 CLI 参数作为"覆盖"或"触发"
    
    parser.add_argument("--mark-read", action="store_true", default=PROJ_CONFIG["mark_read"], help=f"Mark processed articles as read (default: {PROJ_CONFIG['mark_read']})")
    parser.add_argument("--debug", action="store_true", default=PROJ_CONFIG["debug"], help=f"Enable debug mode (default: {PROJ_CONFIG['debug']})")
    parser.add_argument("--refresh", action="store_true", default=PROJ_CONFIG["refresh"], help=f"Refresh unread_news.json from Feedly before processing (default: {PROJ_CONFIG['refresh']})")

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
        
        # 保存到 unread_news.json
        output_file = "unread_news.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存 {len(articles)} 篇未读文章到 {output_file}")
        
        # 如果没有指定输入文件，默认使用刚刷新的文件
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
    for idx, article in enumerate(articles[:args.limit], 1):  # 使用参数控制限制
        logger.info(f"处理第 {idx} 篇: {article['title']}")
        
        summary = article.get('summary', '')
        # 如果摘要足够长（超过500字符），直接使用摘要作为内容分析，跳过抓取
        # 很多RSS源的summary其实已经是全文了
        if summary and len(summary) > 500:
             logger.info(f"  - 摘要较长({len(summary)}字符)，直接作为内容分析，跳过抓取")
             content = summary
        else:
             # 获取文章内容
             content = fetch_article_content(article['link'])
             logger.info(f"  - 获取内容: {len(content)} 字符")
        
        # LLM分析
        analysis = analyze_article_with_llm(
            article['title'],
            summary,
            content
        )
        logger.info(f"  - 评分: {analysis['score']}/10")
        logger.info(f"  - 摘要: {analysis['summary'][:50]}...")
        
        analyzed_articles.append({
            **article,
            "analysis": analysis
        })

        if article.get('id'):
            processed_ids.append(article['id'])
    
    # 保存分析结果
    with open('analyzed_articles.json', 'w', encoding='utf-8') as f:
        json.dump(analyzed_articles, f, ensure_ascii=False, indent=2)
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
    articles = load_articles('analyzed_articles.json')
    overall_summary = generate_overall_summary(articles)
    
    with open('articles_summary.md', 'w', encoding='utf-8') as f:
        f.write(overall_summary)
    print("总体摘要已重新生成并保存到 articles_summary.md")

def load_articles(json_file):
    """加载文章列表"""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def fetch_article_content(url):
    """获取文章内容 - 使用 trafilatura 增强提取能力"""
    # 特定域名跳过抓取
    if "weixin.sogou.com" in url:
        return "内容跳过: 微信链接通常无法直接抓取，仅基于标题摘要分析"

    try:
        # 尝试导入 trafilatura
        try:
            import trafilatura
        except ImportError:
            return "错误: 请先安装 trafilatura 库 (pip install trafilatura) 以获得更好的文章提取效果"

        # 配置代理 (优先使用环境变量，其次使用配置)
        proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or PROJ_CONFIG.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        
        # 直接使用 requests 获取，确保代理生效
        try:
            response = requests.get(url, headers=headers, proxies=proxies, timeout=15)
            if response.status_code == 200:
                downloaded = response.content
            else:
                return f"获取失败: HTTP {response.status_code}"
        except Exception as req_err:
            return f"请求异常: {str(req_err)}"

        # 提取正文
        if downloaded:
            result = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if result:
                return result[:10000] # 限制长度
            else:
                return "内容提取为空 (可能是纯JS渲染页面)"
        else:
            return "下载内容为空"

    except Exception as e:
        import traceback
        import sys
        traceback.print_exc(file=sys.stderr)
        return f"处理异常: {str(e)}"

def analyze_article_with_llm(title, summary, content):
    """使用 OpenAI 兼容 API 分析文章"""
    try:
        # 使用配置中指定的 analysis_profile
        analysis_profile = PROJ_CONFIG.get("analysis_profile")
        
        client = OpenAI(
            api_key=get_config("OPENAI_API_KEY", profile=analysis_profile),
            base_url=get_config("OPENAI_BASE_URL", profile=analysis_profile)
        )
        
        prompt = f"""请分析以下文章并提供：
1. 评分（1-10分，10分最高）
2. 简短摘要（50-100字）
3. 评分理由

文章标题：{title}
文章摘要：{summary[:200] if summary else '无'}
文章内容：{content[:2000]}

请以JSON格式返回：
{{
  "score": <分数>,
  "summary": "<摘要>",
  "reason": "<评分理由>"
}}
"""
        
        log_debug("LLM Request Prompt", prompt)

        response = client.chat.completions.create(
            model=get_config("OPENAI_MODEL", "gpt-4o-mini", profile=analysis_profile),
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1024
        )
        
        response_text = response.choices[0].message.content
        log_debug("LLM Response Raw", response_text)
        
        if not response_text:
             return {
                "score": 0,
                "summary": "分析失败: 模型未返回内容",
                "reason": "API响应内容为空 (可能是模型服务出错或被截断)"
            }

        # 尝试提取JSON
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {
                "score": 5,
                "summary": "无法解析LLM响应",
                "reason": response_text[:200]
            }
    except Exception as e:
        import traceback
        import sys
        traceback.print_exc(file=sys.stderr)
        return {
            "score": 0,
            "summary": f"分析失败: {str(e)}",
            "reason": "API调用错误"
        }

def generate_overall_summary(analyzed_articles):
    """生成总体摘要"""
    try:
        # 使用配置中指定的 summary_profile
        summary_profile = PROJ_CONFIG.get("summary_profile")
        
        # 优先使用 Summary 专用的配置，如果不存在则 fallback 到通用配置
        api_key = get_config("OPENAI_SUMMARY_API_KEY", profile=summary_profile) or get_config("OPENAI_API_KEY", profile=summary_profile)
        base_url = get_config("OPENAI_SUMMARY_BASE_URL", profile=summary_profile) or get_config("OPENAI_BASE_URL", "https://api.openai.com/v1", profile=summary_profile)
        
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        
        # 准备文章列表
        articles_info = []
        for article in analyzed_articles:
            articles_info.append({
                "title": article["title"],
                "link": article.get("link", ""),
                "score": article["analysis"]["score"],
                "summary": article["analysis"]["summary"]
            })
        
        prompt = f"""基于以下已评分和摘要的文章列表,生成一份总体摘要报告：

文章列表：
{json.dumps(articles_info, ensure_ascii=False, indent=2)}

请提供：
1. 整体趋势分析
2. 高分文章（8分以上）的共同特点
3. 主要话题分类
4. 推荐阅读优先级

注意：
- 请直接输出 Markdown 格式的内容，不要用代码块包裹
- 提到文章时，请使用 Markdown 链接格式：[文章标题](link)
"""
        
        # 获取配置参数
        model = get_config("OPENAI_SUMMARY_MODEL", "gpt-4o-mini", profile=summary_profile)
        temperature = 0.7
        extra_body = {"enable_thinking": True}
        
        # 打印请求信息（始终显示，便于调试）
        print(f"\n{'='*60}")
        print("OpenAI API 请求信息:")
        print(f"{'='*60}")
        print(f"Base URL: {base_url}")
        print(f"Model: {model}")
        print(f"Temperature: {temperature}")
        print(f"Extra Body: {json.dumps(extra_body, ensure_ascii=False)}")
        print(f"API Key: {'*' * 20}{api_key[-8:] if api_key else 'NOT SET'}")
        print(f"\n提示词 (Prompt):\n{'-'*60}\n{prompt}\n{'-'*60}\n")
        
        # 发送请求
        print("正在发送请求到 OpenAI API...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            extra_body=extra_body,
            temperature=temperature
            # 不限制 max_tokens，让模型自由生成完整内容
        )
        
        # 打印响应信息
        print(f"\n{'='*60}")
        print("OpenAI API 响应信息:")
        print(f"{'='*60}")
        print(f"Response ID: {response.id if hasattr(response, 'id') else 'N/A'}")
        print(f"Model: {response.model if hasattr(response, 'model') else 'N/A'}")
        print(f"Created: {response.created if hasattr(response, 'created') else 'N/A'}")
        
        # 打印使用统计
        if hasattr(response, 'usage') and response.usage:
            print(f"\nToken 使用统计:")
            print(f"  - Prompt Tokens: {response.usage.prompt_tokens if hasattr(response.usage, 'prompt_tokens') else 'N/A'}")
            print(f"  - Completion Tokens: {response.usage.completion_tokens if hasattr(response.usage, 'completion_tokens') else 'N/A'}")
            print(f"  - Total Tokens: {response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 'N/A'}")
        
        # 打印选择信息
        if response.choices and len(response.choices) > 0:
            choice = response.choices[0]
            print(f"\n响应详情:")
            print(f"  - Finish Reason: {choice.finish_reason if hasattr(choice, 'finish_reason') else 'N/A'}")
            print(f"  - Index: {choice.index if hasattr(choice, 'index') else 'N/A'}")
            
            # 打印响应内容
            content = choice.message.content if hasattr(choice.message, 'content') else None
            if content:
                print(f"\n响应内容 (前500字符):\n{'-'*60}")
                print(content[:500])
                if len(content) > 500:
                    print(f"... (总共 {len(content)} 字符)")
                print(f"{'-'*60}")
            else:
                print("\n⚠️ 警告: 响应内容为空!")
        else:
            print("\n⚠️ 警告: 没有返回任何选择 (choices)!")
        
        print(f"{'='*60}\n")
        
        content = response.choices[0].message.content
        if not content:
            return "生成总结失败: 模型未返回内容"
        return content
    except Exception as e:
        import traceback
        import sys
        print(f"\n{'='*60}")
        print("❌ OpenAI API 调用失败:")
        print(f"{'='*60}")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        print(f"\n完整堆栈跟踪:")
        traceback.print_exc(file=sys.stderr)
        print(f"{'='*60}\n")
        return f"生成总结失败: {str(e)}"

# Feedly Integration
FEEDLY_CONFIG_FILE = os.path.join(os.getcwd(), '.claude', 'skills', 'rss_reader', 'feedly_config.json')

def load_feedly_config():
    if os.path.exists(FEEDLY_CONFIG_FILE):
        with open(FEEDLY_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def get_feedly_headers(token):
    return {
        'Authorization': f'OAuth {token}'
    }

def feedly_fetch_unread(stream_id=None, limit=999):
    """从Feedly获取未读文章"""
    config = load_feedly_config()
    if not config:
        logger.error("Feedly未配置，无法获取未读文章")
        return None
    
    token = config['token']
    user_id = config['user_id']
    base_url = "https://cloud.feedly.com/v3"
    
    target_stream = stream_id
    if not target_stream:
        target_stream = f"user/{user_id}/category/global.all"

    try:
        params = {
            'streamId': target_stream,
            'count': limit,
            'unreadOnly': 'true'
        }
        
        # 配置代理
        proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or PROJ_CONFIG.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        response = requests.get(
            f"{base_url}/streams/contents", 
            headers=get_feedly_headers(token), 
            params=params,
            proxies=proxies
        )
        
        if response.status_code == 401:
            logger.error("Feedly认证失败，请检查token")
            return None
        if response.status_code != 200:
            logger.error(f"Feedly API错误: {response.status_code} - {response.text}")
            return None

        data = response.json()
        articles = []
        if 'items' in data:
            for entry in data['items']:
                article = {
                    'title': entry.get('title', 'No Title'),
                    'link': entry.get('alternate', [{}])[0].get('href', '') if entry.get('alternate') else '',
                    'published': entry.get('published', 0),
                    'summary': entry.get('summary', {}).get('content', '') or entry.get('content', {}).get('content', ''),
                    'id': entry.get('id', ''),
                    'origin': entry.get('origin', {}).get('title', '')
                }
                articles.append(article)
        
        return articles
    except Exception as e:
        logger.error(f"获取Feedly未读文章异常: {str(e)}")
        import traceback
        import sys
        traceback.print_exc(file=sys.stderr)
        return None


def feedly_mark_read(article_ids):
    """标记文章为已读"""
    config = load_feedly_config()
    if not config:
        logger.error("未找到 Feedly 配置，无法标记已读")
        return False
    
    token = config['token']
    base_url = "https://cloud.feedly.com/v3"

    if isinstance(article_ids, str):
        article_ids = [article_ids]
        
    try:
        # 配置代理
        proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or PROJ_CONFIG.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        data = {
            "action": "markAsRead",
            "type": "entries",
            "entryIds": article_ids
        }
        response = requests.post(
            f"{base_url}/markers", 
            headers=get_feedly_headers(token), 
            json=data,
            proxies=proxies
        )
        
        if response.status_code == 200:
            logger.info(f"成功标记 {len(article_ids)} 篇文章为已读")
            return True
        else:
            logger.error(f"标记已读失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"标记已读异常: {str(e)}")
        return False

if __name__ == "__main__":
    regenerate_summary()
