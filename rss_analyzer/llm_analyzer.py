"""
LLM 分析模块
使用 OpenAI 兼容 API 进行文章分析和摘要生成
"""

import json
import logging
import sys
import traceback

from openai import OpenAI

from .config import get_openai_task_config

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
    from .scoring import format_score_result, score_article

    try:
        score_result = score_article(title, summary, content)
        return {
            "score": score_result.get("overall_score", 0.0),
            "verdict": score_result.get("verdict", "未知"),
            "summary": score_result.get("comment", ""),
            "reason": format_score_result(score_result),
            "model": score_result.get("model", "unknown"),
            "detailed_scores": {
                "relevance": score_result.get("relevance_score", 0),
                "informativeness": score_result.get(
                    "informativeness_accuracy_score", 0
                ),
                "depth": score_result.get("depth_opinion_score", 0),
                "readability": score_result.get("readability_score", 0),
                "originality": score_result.get("non_redundancy_score", 0),
                "red_flags": score_result.get("red_flags", []),
                "article_type": score_result.get("article_type", "default"),
            },
        }
    except Exception as e:
        logger.error(f"文章分析失败: {e}")
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
                "originality": 0,
            },
        }


def analyze_articles_with_llm_batch(articles: list[dict]) -> list[dict]:
    """
    使用 OpenAI 兼容 API 批量分析文章

    Args:
        articles: [{title, summary, content}, ...]
    Returns:
        分析结果列表，与输入顺序一致
    """
    from .scoring import format_score_result, score_articles_batch

    try:
        score_results = score_articles_batch(articles)
        if not score_results or len(score_results) != len(articles):
            raise ValueError("batch scoring failed or size mismatch")

        analyzed = []
        for score_result in score_results:
            analyzed.append(
                {
                    "score": score_result.get("overall_score", 0.0),
                    "verdict": score_result.get("verdict", "未知"),
                    "summary": score_result.get("comment", ""),
                    "reason": format_score_result(score_result),
                    "model": score_result.get("model", "unknown"),
                    "detailed_scores": {
                        "relevance": score_result.get("relevance_score", 0),
                        "informativeness": score_result.get(
                            "informativeness_accuracy_score", 0
                        ),
                        "depth": score_result.get("depth_opinion_score", 0),
                        "readability": score_result.get("readability_score", 0),
                        "originality": score_result.get("non_redundancy_score", 0),
                        "red_flags": score_result.get("red_flags", []),
                        "article_type": score_result.get("article_type", "default"),
                    },
                }
            )

        return analyzed
    except Exception as e:
        logger.warning(f"批量评分失败，回退为单篇评分: {e}")
        fallback = []
        for article in articles:
            fallback.append(
                analyze_article_with_llm(
                    article.get("title", ""),
                    article.get("summary", ""),
                    article.get("content", ""),
                )
            )
        return fallback


def summarize_single_article(text: str, task: str = "analysis") -> str:
    """
    Summarize a single article using a task-scoped model configuration.

    Args:
        text: The article text to summarize
        task: Task config namespace, usually analysis or summary

    Returns:
        The summary text
    """
    try:
        openai_config = get_openai_task_config(task, default_model="gpt-3.5-turbo")
        client = OpenAI(
            api_key=openai_config.api_key,
            base_url=openai_config.base_url,
        )

        prompt = """
You are an expert analyst. Provide a comprehensive summary of the following article.
Do NOT just skim the surface. Deeply analyze the content and provide a detailed summary.

Structure your response as follows:

### Core Argument
State the main point or event in 1-2 clear sentences.

### Key Details
- List 3-5 crucial details, facts, or data points from the article.
- Include specific numbers, names, or dates if present.
- Capture the nuance of the argument.

### Implications
What does this mean? What are the consequences or conclusions drawn?

Output Format: Markdown.
"""

        response = client.chat.completions.create(
            model=openai_config.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Article Content:\n\n{text}"},
            ],
            temperature=0.5,
        )

        content = response.choices[0].message.content
        if not content:
            return "Summarization failed: Model returned empty content"
        return content

    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return f"Summarization failed: {str(e)}"


def generate_overall_summary(analyzed_articles: list) -> str:
    """
    生成总体摘要

    Args:
        analyzed_articles: 已分析的文章列表

    Returns:
        Markdown 格式的总体摘要
    """
    try:
        openai_config = get_openai_task_config("summary", default_model="gpt-4o-mini")
        client = OpenAI(
            api_key=openai_config.api_key,
            base_url=openai_config.base_url,
        )

        articles_info = []
        skipped_count = 0

        for article in analyzed_articles:
            analysis = article["analysis"]
            score = analysis.get("score", 0.0)
            red_flags = analysis.get("detailed_scores", {}).get("red_flags", [])

            if score < 3.0 or red_flags:
                skipped_count += 1
                continue

            articles_info.append(
                {
                    "title": article["title"],
                    "link": article.get("link", ""),
                    "score": score,
                    "verdict": analysis.get("verdict", "未知"),
                    "summary": analysis.get("summary", ""),
                    "detailed_scores": analysis.get("detailed_scores", {}),
                }
            )

        if not articles_info:
            return "没有值得总结的高质量文章。"

        prompt = f"""你是一位专业的内容编辑，请基于以下已筛选的高质量文章列表（已过滤掉低分和垃圾内容），生成一份详细的阅读推荐报告。

文章列表（共 {len(articles_info)} 篇，已跳过 {skipped_count} 篇低质量文章）：
{json.dumps(articles_info, ensure_ascii=False, indent=2)}

评分说明：
- 评分范围：0-5.0 分
- 分类标准：
  * ≥4.0 分：🔥 值得阅读
  * 3.0-3.9 分：😐 一般，可选阅读
  * <3.0 分：👎 不太值得阅读
- 评分维度：相关性、信息量、深度、可读性、原创性（各 1-5 分）

请按以下结构生成报告：

## 📊 整体概况
- 文章总数和评分分布
- 平均分和整体质量评价
- 主要话题领域

## 🔥 强烈推荐（≥4.0分）
对于每篇高分文章，请提供：
1. 标题（带链接）和评分
2. 推荐理由（为什么值得读？有什么亮点？）
3. 核心观点或价值（1-2句话）

## 😐 可选阅读（3.0-3.9分）
列出这些文章（标题带链接），并简要说明适合什么情况下阅读。
格式示例：
- [文章标题](链接) **评分: 3.5/5.0** - 适用场景说明

## 📈 趋势分析
- 高分文章的共同特点
- 主要话题分类
- 值得关注的方向

## 💡 阅读建议
根据评分和内容，给出优先级建议

注意事项：
- 使用 Markdown 格式，不要用代码块包裹
- 文章标题使用链接格式：[标题](link)
- 在每篇推荐文章后标注评分，如：**评分: 4.5/5.0** 🔥
- 充分利用 summary 字段中的文章评价信息
- 推荐理由要具体，不要泛泛而谈
"""

        temperature = 0.7
        extra_body = {"enable_thinking": True}

        print(f"\n{'=' * 60}")
        print("OpenAI API 请求信息:")
        print(f"{'=' * 60}")
        print(f"Base URL: {openai_config.base_url}")
        print(f"Model: {openai_config.model}")
        print(f"Temperature: {temperature}")
        print(f"Extra Body: {json.dumps(extra_body, ensure_ascii=False)}")
        print(
            f"API Key: {'*' * 20}{openai_config.api_key[-8:] if openai_config.api_key else 'NOT SET'}"
        )
        print(f"\n提示词 (Prompt):\n{'-' * 60}\n{prompt}\n{'-' * 60}\n")

        print("正在发送请求到 OpenAI API...")
        response = client.chat.completions.create(
            model=openai_config.model,
            messages=[{"role": "user", "content": prompt}],
            extra_body=extra_body,
            temperature=temperature,
        )

        print(f"\n{'=' * 60}")
        print("OpenAI API 响应信息:")
        print(f"{'=' * 60}")
        print(f"Response ID: {response.id if hasattr(response, 'id') else 'N/A'}")
        print(f"Model: {response.model if hasattr(response, 'model') else 'N/A'}")
        print(f"Created: {response.created if hasattr(response, 'created') else 'N/A'}")

        if hasattr(response, "usage") and response.usage:
            print("\nToken 使用统计:")
            print(
                f"  - Prompt Tokens: {response.usage.prompt_tokens if hasattr(response.usage, 'prompt_tokens') else 'N/A'}"
            )
            print(
                f"  - Completion Tokens: {response.usage.completion_tokens if hasattr(response.usage, 'completion_tokens') else 'N/A'}"
            )
            print(
                f"  - Total Tokens: {response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 'N/A'}"
            )

        if response.choices and len(response.choices) > 0:
            choice = response.choices[0]
            print("\n响应详情:")
            print(
                f"  - Finish Reason: {choice.finish_reason if hasattr(choice, 'finish_reason') else 'N/A'}"
            )
            print(f"  - Index: {choice.index if hasattr(choice, 'index') else 'N/A'}")

            content = choice.message.content if hasattr(choice.message, "content") else None
            if content:
                print(f"\n响应内容 (前500字符):\n{'-' * 60}")
                print(content[:500])
                if len(content) > 500:
                    print(f"... (总共 {len(content)} 字符)")
                print(f"{'-' * 60}")
            else:
                print("\n⚠️ 警告: 响应内容为空!")
        else:
            print("\n⚠️ 警告: 没有返回任何选择 (choices)!")

        print(f"{'=' * 60}\n")

        content = response.choices[0].message.content
        if not content:
            return "生成总结失败: 模型未返回内容"
        return content
    except Exception as e:
        print(f"\n{'=' * 60}")
        print("❌ OpenAI API 调用失败:")
        print(f"{'=' * 60}")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        print("\n完整堆栈跟踪:")
        traceback.print_exc(file=sys.stderr)
        print(f"{'=' * 60}\n")
        return f"生成总结失败: {str(e)}"
