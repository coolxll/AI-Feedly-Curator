"""
文章评分模块
基于多维度评估文章的阅读价值
"""
import json
import re
import logging
from typing import Dict, Any
from datetime import datetime

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
    "pure_promotion",  # 纯推广/软文 (Hard)
    "clickbait",       # 标题党 (Soft)
    "ai_generated",    # AI 生成感过重/逻辑混乱 (Hard)
    "outdated"         # 过时信息 (Soft)
]

HARD_RED_FLAGS = {"ai_generated"}


def build_scoring_prompt(title: str, summary: str, content: str) -> str:
    """构建结构化评分提示词 (含思维链 & 智能截断)"""
    persona = PROJ_CONFIG.get("scoring_persona", "")
    
    # 智能截断：保留头部和尾部，中间截断
    if len(content) > 10000:
        content_snippet = content[:6000] + "\n\n...[内容过长，中间部分省略]...\n\n" + content[-3000:]
    else:
        content_snippet = content

    today_str = datetime.now().strftime("%Y-%m-%d")

    return f"""{persona}

当前日期：{today_str}

请根据你的专业背景，按照以下步骤对文章进行深度评估：

### 第一步：分析与思考 (Chain of Thought)
请先通读全文，分析文章的核心价值、技术深度和潜在缺陷。
- 这篇文章是讲什么的？解决了什么问题？
- 是否有实质性的代码或独到见解，还是仅为搬运/洗稿？
- 是否有过度的营销话术或误导性标题？
- **时间检查**：对比"当前日期"，判断文章讨论的内容是否过时（例如2026年还在讨论2020年的旧闻）。

### 第二步：类型判断 & 负面检测
1. **判断文章类型**：`news` (资讯), `tutorial` (教程), `opinion` (观点).
2. **检测负面特征**：
   - `pure_promotion`: 纯广告/卖课/推销产品 (Soft Flag). **注意：技术视角的工具推荐、新功能发布、开源项目介绍、投行报告摘要均不算广告。**
   - `clickbait`: 标题党 (Soft Flag)
   - `ai_generated`: 明显的 AI 生成痕迹/逻辑混乱 (Hard Flag)
   - `outdated`: 严重过时 (Soft Flag) - **请基于{today_str}判断**

### 第三步：多维度打分 (1-5分，严谨评分)
> 评分标准：
> - 5分：极佳。行业突破性见解、极其详尽的原创教程、极具启发性的深度好文。
> - 4分：优秀。内容扎实，有代码或具体实践，值得细读。
> - 3分：及格。普通资讯、简单的入门介绍、常见的八股文。大部分文章应在此分数段。
> - 1-2分：差。无营养、重复废话、明显错误或纯广告。

维度：
1. **相关性**：是否符合我的人设（Tech / 投资 / 国际政治）。
2. **信息量与准确性**：信息密度如何，是否准确可靠。
3. **深度与观点**：是否有独家见解或深入分析。
4. **可读性**：结构清晰，代码优雅（如果是技术文）或逻辑顺畅。
5. **原创性/水分度**：是否原创，是否水分太大。

### 输出格式 (JSON Only)
请只返回以下 JSON 格式，不要包含其他文本：
{{
  "analysis": "1-2句话的简要分析，说明打分理由",
  "article_type": "news/tutorial/opinion",
  "red_flags": ["clickbait", ...],  // 无则为空数组
  "scores": {{
    "relevance": <1-5>,
    "informativeness_accuracy": <1-5>,
    "depth_opinion": <1-5>,
    "readability": <1-5>,
    "non_redundancy": <1-5>
  }}
}}

---
文章信息：
标题：{title}
摘要：{summary[:200] if summary else '无'}
正文：
{content_snippet}
"""


def calculate_weighted_score(scores: Dict[str, int], article_type: str, red_flags: list) -> float:
    """计算加权总分 (含负面惩罚)"""
    # 1. 获取权重
    weights_config = PROJ_CONFIG.get("scoring_weights", {})
    weights = weights_config.get(article_type, weights_config.get("default", DEFAULT_WEIGHTS))
    
    # 2. 计算基础加权分
    total_score = 0
    total_weight = 0
    
    for key, score in scores.items():
        w = weights.get(key, 1)
        total_score += score * w
        total_weight += w
    
    avg_score = total_score / total_weight if total_weight > 0 else 0
    
    # 3. 负面清单处理 (Tiered Penalty)
    if red_flags:
        # Hard Flags: 直接打入冷宫 (最高 1.0 分)
        if any(flag in HARD_RED_FLAGS for flag in red_flags):
            return 1.0
        
        # Soft Flags: 每一项扣 1.0 分
        penalty = len(red_flags) * 1.0
        avg_score = max(1.0, avg_score - penalty)
        
    return round(avg_score, 1)


def parse_score_response(response_text: str) -> Dict[str, Any]:
    """解析响应并计算总分"""
    try:
        # 尝试提取 JSON
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            
            scores = data.get("scores", {})
            article_type = data.get("article_type", "default")
            red_flags = data.get("red_flags", [])
            analysis_text = data.get("analysis", "") # 获取分析文本
            
            # 计算加权总分
            overall_score = calculate_weighted_score(scores, article_type, red_flags)
            
            # 生成一句话 Verdict
            if overall_score >= 3.8:  # User feedback: 3.9 is also high quality
                verdict = "值得阅读"
            elif overall_score >= 3.0:
                verdict = "一般，可选"
            else:
                verdict = "不值得读"
                
            if red_flags:
                verdict += f" (含: {', '.join(red_flags)})"

            return {
                "relevance_score": scores.get("relevance", 0),
                "informativeness_accuracy_score": scores.get("informativeness_accuracy", 0),
                "depth_opinion_score": scores.get("depth_opinion", 0),
                "readability_score": scores.get("readability", 0),
                "non_redundancy_score": scores.get("non_redundancy", 0),
                "overall_score": overall_score,
                "verdict": verdict,
                "reason": analysis_text, # 使用 analysis 字段作为 reason
                "comment": data.get("comment", analysis_text), # 兼容 comment
                "article_type": article_type,
                "red_flags": red_flags,
                "detailed_scores": data # 保存完整原始数据
            }
            
        return _default_error_result(f"无法解析JSON: {response_text[:100]}")
    except Exception as e:
        logger.error(f"解析失败: {e}")
        return _default_error_result(str(e))


def _default_error_result(msg: str):
    return {
        "overall_score": 0.0,
        "verdict": "解析错误",
        "reason": msg,
        "comment": msg,
        "red_flags": [],
        "detailed_scores": {}
    }


def score_article(title: str, summary: str, content: str) -> Dict[str, Any]:
    """
    对文章进行多维度评分
    """
    try:
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
            temperature=0.2,  # 稍微降低一点，更稳定
            max_tokens=1500   # 增加 Token 上限以容纳 Analysis
        )
        
        response_text = response.choices[0].message.content
        log_debug("Scoring Response", response_text)
        
        if not response_text:
            return _default_error_result("模型返回为空")
        
        result = parse_score_response(response_text)
        
        # 补全 score 字段，兼容旧的 article_analyzer 调用
        result['score'] = result['overall_score']
        
        return result
        
    except Exception as e:
        logger.error(f"评分过程异常: {e}")
        return _default_error_result(f"Exception: {str(e)}")


def format_score_result(score_result: Dict[str, Any]) -> str:
    """格式化展示"""
    verdict = score_result.get("verdict", "未知")
    overall = score_result.get("overall_score", 0.0)
    
    emoji = "😐"
    if overall >= 3.8:
        emoji = "🔥"
    elif overall <= 2.0:
        emoji = "🗑️" # 垃圾桶
    elif overall < 3.0:
        emoji = "👎"
    
    return f"{emoji} {verdict} ({overall}/5.0)"
