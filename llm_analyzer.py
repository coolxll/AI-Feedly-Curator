"""
LLM 分析模块
使用 OpenAI 兼容 API 进行文章分析和摘要生成
"""
import json
import re
import logging
import traceback
import sys

from openai import OpenAI

from config import PROJ_CONFIG, get_config, log_debug

logger = logging.getLogger(__name__)


def analyze_article_with_llm(title: str, summary: str, content: str) -> dict:
    """
    使用 OpenAI 兼容 API 分析文章
    
    Args:
        title: 文章标题
        summary: 文章摘要
        content: 文章内容
    
    Returns:
        分析结果字典，包含 score, summary, reason
    """
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
        traceback.print_exc(file=sys.stderr)
        return {
            "score": 0,
            "summary": f"分析失败: {str(e)}",
            "reason": "API调用错误"
        }


def generate_overall_summary(analyzed_articles: list) -> str:
    """
    生成总体摘要
    
    Args:
        analyzed_articles: 已分析的文章列表
    
    Returns:
        Markdown 格式的总体摘要
    """
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
        print(f"\n{'='*60}")
        print("❌ OpenAI API 调用失败:")
        print(f"{'='*60}")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        print(f"\n完整堆栈跟踪:")
        traceback.print_exc(file=sys.stderr)
        print(f"{'='*60}\n")
        return f"生成总结失败: {str(e)}"
