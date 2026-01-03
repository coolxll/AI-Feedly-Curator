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

from .config import PROJ_CONFIG, get_config, log_debug

logger = logging.getLogger(__name__)


def analyze_article_with_llm(title: str, summary: str, content: str) -> dict:
    """
    使用 OpenAI 兼容 API 分析文章
    
    Args:
        title: 文章标题
        summary: 文章摘要
        content: 文章内容
    
    Returns:
        分析结果字典，包含详细评分和简短摘要
    """
    from .scoring import score_article, format_score_result
    
    try:
        # 使用新的评分系统
        score_result = score_article(title, summary, content)
        
        # 转换为兼容的格式
        return {
            "score": score_result.get("overall_score", 0.0),
            "verdict": score_result.get("verdict", "未知"),
            "summary": score_result.get("comment", ""),
            "reason": format_score_result(score_result),
            "detailed_scores": {
                "relevance": score_result.get("relevance_score", 0),
                "informativeness": score_result.get("informativeness_accuracy_score", 0),
                "depth": score_result.get("depth_opinion_score", 0),
                "readability": score_result.get("readability_score", 0),
                "originality": score_result.get("non_redundancy_score", 0)
            }
        }
    except Exception as e:
        logger.error(f"文章分析失败: {e}")
        import traceback
        import sys
        traceback.print_exc(file=sys.stderr)
        return {
            "score": 0.0,
            "verdict": "不太值得阅读",
            "summary": f"分析失败: {str(e)}",
            "reason": "API调用错误",
            "detailed_scores": {
                "relevance": 0,
                "informativeness": 0,
                "depth": 0,
                "readability": 0,
                "originality": 0
            }
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
