"""
文章评分模块
基于多维度评估文章的阅读价值
"""
import json
import re
import logging
from typing import Dict, Any

from openai import OpenAI

from .config import PROJ_CONFIG, get_config, log_debug

logger = logging.getLogger(__name__)


# 评分维度配置
SCORING_DIMENSIONS = {
    "relevance": {"name": "相关性", "max": 5},
    "informativeness_accuracy": {"name": "信息量与准确性", "max": 5},
    "depth_opinion": {"name": "深度与观点", "max": 5},
    "readability": {"name": "可读性", "max": 5},
    "non_redundancy": {"name": "原创性/水分度", "max": 5}
}

# 评分分类
SCORE_CATEGORIES = {
    "must_read": {"min": 4.0, "label": "值得阅读", "emoji": "🔥"},
    "optional": {"min": 3.0, "label": "一般，可选阅读", "emoji": "😐"},
    "skip": {"min": 0.0, "label": "不太值得阅读", "emoji": "👎"}
}


def build_scoring_prompt(title: str, summary: str, content: str) -> str:
    """
    构建结构化评分提示词
    """
    persona = PROJ_CONFIG.get("scoring_persona", "")
    
    return f"""{persona}

请根据你的专业背景和偏好，以及下面的标准，判断给定文章是否值得你花时间完整阅读。

评分维度：

1. 相关性（1–5 分）：文章内容是否紧扣【测试开发、DevOps、AI编程、Vibe Coding】等你的核心兴趣点。

2. 信息量与准确性（1–5 分）：是否提供新的工具、框架、方法论，或对现有技术有独到见解。

3. 深度与观点（1–5 分）：是否有技术深度，能否启发思考，而不是简单的入门教程或文档翻译。

4. 可读性（1–5 分）：代码示例是否清晰，逻辑是否顺畅，读起来是否享受（符合 Vibe Coding 的美感）。

5. 重复度/水分（1–5 分）：分数越高表示"水分越少"。拒绝营销软文、无意义的焦虑贩卖。

请按以下步骤完成任务：

1. 先根据五个维度分别打 1–5 分。
2. 计算一个总分（取五个维度的平均分，保留一位小数）。
3. 根据总分给出一个结论：
   - 总分 ≥ 4.0：结论写"值得阅读"
   - 3.0–3.9：结论写"一般，可选阅读"
   - ＜ 3.0：结论写"不太值得阅读"
4. 用 2–4 句话简要说明理由，并指出 1–2 个主要优点和缺点。

输出必须使用如下 JSON 格式，不要添加多余说明：

{{
  "relevance_score": 分数,
  "informativeness_accuracy_score": 分数,
  "depth_opinion_score": 分数,
  "readability_score": 分数,
  "non_redundancy_score": 分数,
  "overall_score": 总分,
  "verdict": "值得阅读/一般，可选阅读/不太值得阅读",
  "comment": "2-4 句话说明理由，包含主要优点和缺点"
}}

下面是文章内容：

标题：{title}
摘要：{summary[:200] if summary else '无'}
正文：{content[:3000]}
"""


def parse_score_response(response_text: str) -> Dict[str, Any]:
    """
    解析 LLM 评分响应
    
    Args:
        response_text: LLM 响应文本
    
    Returns:
        解析后的评分结果
    """
    try:
        # 尝试提取 JSON
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            
            # 验证必需字段
            required_fields = [
                "relevance_score", "informativeness_accuracy_score",
                "depth_opinion_score", "readability_score",
                "non_redundancy_score", "overall_score", "verdict", "comment"
            ]
            
            if all(field in result for field in required_fields):
                return result
        
        # 解析失败，返回默认值
        return {
            "relevance_score": 3,
            "informativeness_accuracy_score": 3,
            "depth_opinion_score": 3,
            "readability_score": 3,
            "non_redundancy_score": 3,
            "overall_score": 3.0,
            "verdict": "一般，可选阅读",
            "comment": f"无法解析评分响应: {response_text[:100]}"
        }
    except Exception as e:
        logger.error(f"解析评分响应失败: {e}")
        return {
            "relevance_score": 0,
            "informativeness_accuracy_score": 0,
            "depth_opinion_score": 0,
            "readability_score": 0,
            "non_redundancy_score": 0,
            "overall_score": 0.0,
            "verdict": "不太值得阅读",
            "comment": f"评分解析错误: {str(e)}"
        }


def score_article(title: str, summary: str, content: str) -> Dict[str, Any]:
    """
    对文章进行多维度评分
    
    Args:
        title: 文章标题
        summary: 文章摘要
        content: 文章内容
    
    Returns:
        评分结果字典
    """
    try:
        # 使用配置中指定的 analysis_profile
        analysis_profile = PROJ_CONFIG.get("analysis_profile")
        
        client = OpenAI(
            api_key=get_config("OPENAI_API_KEY", profile=analysis_profile),
            base_url=get_config("OPENAI_BASE_URL", profile=analysis_profile)
        )
        
        prompt = build_scoring_prompt(title, summary, content)
        log_debug("Scoring Prompt", prompt)
        
        response = client.chat.completions.create(
            model=get_config("OPENAI_MODEL", "gpt-4o-mini", profile=analysis_profile),
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # 降低温度以获得更一致的评分
            max_tokens=1024
        )
        
        response_text = response.choices[0].message.content
        log_debug("Scoring Response", response_text)
        
        if not response_text:
            return {
                "relevance_score": 0,
                "informativeness_accuracy_score": 0,
                "depth_opinion_score": 0,
                "readability_score": 0,
                "non_redundancy_score": 0,
                "overall_score": 0.0,
                "verdict": "不太值得阅读",
                "comment": "模型未返回内容"
            }
        
        return parse_score_response(response_text)
        
    except Exception as e:
        logger.error(f"评分失败: {e}")
        import traceback
        import sys
        traceback.print_exc(file=sys.stderr)
        return {
            "relevance_score": 0,
            "informativeness_accuracy_score": 0,
            "depth_opinion_score": 0,
            "readability_score": 0,
            "non_redundancy_score": 0,
            "overall_score": 0.0,
            "verdict": "不太值得阅读",
            "comment": f"评分失败: {str(e)}"
        }


def format_score_result(score_result: Dict[str, Any]) -> str:
    """
    格式化评分结果为可读字符串
    
    Args:
        score_result: 评分结果字典
    
    Returns:
        格式化后的字符串
    """
    verdict = score_result.get("verdict", "未知")
    overall = score_result.get("overall_score", 0.0)
    
    # 添加 emoji
    emoji = "😐"
    if overall >= 4.0:
        emoji = "🔥"
    elif overall < 3.0:
        emoji = "👎"
    
    return f"{emoji} {verdict} ({overall}/5.0)"
