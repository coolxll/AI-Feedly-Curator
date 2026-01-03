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


# 评分维度配置 (保留 Metadata，权重现在是动态的)
SCORING_DIMENSIONS = {
    "relevance": {"name": "相关性"},
    "informativeness_accuracy": {"name": "信息量与准确性"},
    "depth_opinion": {"name": "深度与观点"},
    "readability": {"name": "可读性"},
    "non_redundancy": {"name": "原创性/水分度"}
}

# 动态权重配置
DEFAULT_WEIGHTS = PROJ_CONFIG.get("scoring_weights", {}).get("default", {
    "relevance": 2, "informativeness_accuracy": 2, "depth_opinion": 2, "readability": 2, "non_redundancy": 1
})

# 负面清单配置
RED_FLAGS = [
    "pure_promotion",  # 纯推广/软文
    "clickbait",       # 标题党
    "ai_generated",    # AI 生成感过重
    "outdated"         # 过时信息
]


def build_scoring_prompt(title: str, summary: str, content: str) -> str:
    """构建结构化评分提示词"""
    persona = PROJ_CONFIG.get("scoring_persona", "")
    
    return f"""{persona}

请根据你的专业背景和偏好，从以下三个方面评估这篇文章：

### 第一步：类型判断 & 负面检测
1. **判断文章类型**：是 `news` (新闻/资讯)、`tutorial` (教程/实操)、还是 `opinion` (观点/深度分析)？
2. **检测负面特征 (Red Flags)**：
   - `pure_promotion`: 是否整篇只为卖课或卖产品？
   - `clickbait`: 是否标题惊悚但内容空洞？
   - `ai_generated`: 是否有明显的车轱辘话、逻辑断层？
   - `outdated`: 是否讨论几年前的过时技术？

### 第二步：多维度打分 (1-5分)
1. **相关性**：是否紧扣【测试开发、DevOps、AI编程、Vibe Coding】。
2. **信息量与准确性**：是否提供新工具、新见解。
3. **深度与观点**：是否有启发性，拒绝简单归纳。
4. **可读性**：代码/结构是否优雅 (Vibe Coding)。
5. **原创性/水分度**：分数越高水分越少。

### 输出格式 (JSON)
{{
  "article_type": "news/tutorial/opinion",
  "red_flags": ["clickbait", ...],  // 如果没有则为空列表 []
  "scores": {{
    "relevance": <分数>,
    "informativeness_accuracy": <分数>,
    "depth_opinion": <分数>,
    "readability": <分数>,
    "non_redundancy": <分数>
  }},
  "comment": "简短评价（包含主要优点/缺点）"
}}

下面是文章内容：
标题：{title}
摘要：{summary[:200] if summary else '无'}
正文：{content[:3000]}
"""


def calculate_weighted_score(scores: Dict[str, int], article_type: str, red_flags: list) -> float:
    """计算加权总分"""
    # 1. 获取对应类型的权重
    weights_config = PROJ_CONFIG.get("scoring_weights", {})
    weights = weights_config.get(article_type, weights_config.get("default", DEFAULT_WEIGHTS))
    
    # 2. 计算加权平均分
    total_score = 0
    total_weight = 0
    
    for key, score in scores.items():
        w = weights.get(key, 1)
        total_score += score * w
        total_weight += w
    
    avg_score = total_score / total_weight if total_weight > 0 else 0
    
    # 3. 负面清单惩罚 (Red Flags Penalty)
    # 如果有 red_flags，最高分限制为 2.5 (不推荐)，或者直接扣分
    if red_flags:
        # 简单粗暴：有硬伤直接不及格
        return min(avg_score, 2.5)
        
    return round(avg_score, 1)


def parse_score_response(response_text: str) -> Dict[str, Any]:
    """解析响应并计算总分"""
    try:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            
            # 兼容旧代码的字段映射
            scores = data.get("scores", {})
            article_type = data.get("article_type", "default")
            red_flags = data.get("red_flags", [])
            
            # 计算加权总分
            overall_score = calculate_weighted_score(scores, article_type, red_flags)
            
            # 生成结论
            if overall_score >= 4.0:
                verdict = "值得阅读"
            elif overall_score >= 3.0:
                verdict = "一般，可选阅读"
            else:
                verdict = "不太值得阅读"
                
            if red_flags:
                verdict = f"不推荐 (含: {', '.join(red_flags)})"

            return {
                "relevance_score": scores.get("relevance", 0),
                "informativeness_accuracy_score": scores.get("informativeness_accuracy", 0),
                "depth_opinion_score": scores.get("depth_opinion", 0),
                "readability_score": scores.get("readability", 0),
                "non_redundancy_score": scores.get("non_redundancy", 0),
                "overall_score": overall_score,
                "verdict": verdict,
                "comment": data.get("comment", ""),
                "article_type": article_type,
                "red_flags": red_flags
            }
            
        return _default_error_result(f"无法解析: {response_text[:50]}")
    except Exception as e:
        logger.error(f"解析失败: {e}")
        return _default_error_result(str(e))


def _default_error_result(msg: str):
    return {
        "overall_score": 0.0,
        "verdict": "解析错误",
        "comment": msg,
        "red_flags": []
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
