"""
文章评分模块
基于多维度评估文章的阅读价值
"""

import json
import re
import time
import random
import logging
from typing import Dict, Any
from datetime import datetime

from openai import OpenAI, RateLimitError

from .config import (
    PROJ_CONFIG,
    build_openai_client_kwargs,
    get_openai_task_config,
    log_debug,
)

logger = logging.getLogger(__name__)


# 评分维度配置 (保留 Metadata，权重现在是动态的)
SCORING_DIMENSIONS = {
    "relevance": {"name": "相关性"},
    "informativeness_accuracy": {"name": "信息量与准确性"},
    "depth_opinion": {"name": "深度与观点"},
    "readability": {"name": "可读性"},
    "non_redundancy": {"name": "原创性/水分度"},
}

# 动态权重配置
DEFAULT_WEIGHTS = PROJ_CONFIG.get("scoring_weights", {}).get(
    "default",
    {
        "relevance": 2,
        "informativeness_accuracy": 2,
        "depth_opinion": 2,
        "readability": 2,
        "non_redundancy": 1,
    },
)

# 负面清单配置
RED_FLAGS = [
    "pure_promotion",  # 纯推广/软文 (Soft)
    "clickbait",  # 标题党 (Soft)
    "ai_generated",  # AI 生成感过重/逻辑混乱 (Hard)
]

HARD_RED_FLAGS = {"ai_generated"}
DEFAULT_SCORE_ANCHOR = 3.0
HIGH_SCORE_THRESHOLD = 4.2
RECOMMENDED_SCORE_THRESHOLD = 3.6
NEGATIVE_SIGNAL_PENALTY = 0.35


def _build_content_snippet(content: str) -> str:
    """智能截断正文，保留头尾关键信息。"""
    if len(content) > 10000:
        return (
            content[:6000] + "\n\n...[内容过长，中间部分省略]...\n\n" + content[-3000:]
        )
    return content


def build_scoring_prompt(title: str, summary: str, content: str) -> str:
    """构建结构化评分提示词 (含思维链 & 智能截断)"""
    persona = PROJ_CONFIG.get("scoring_persona", "")

    # 智能截断：保留头部和尾部，中间截断
    content_snippet = _build_content_snippet(content)

    today_str = datetime.now().strftime("%Y-%m-%d")

    return f"""{persona}

当前日期：{today_str}

请根据你的专业背景，按照以下步骤对文章进行深度评估。
你的任务不是判断“这像不像一篇合格文章”，而是判断“这篇对一个见多识广、阈值很高的技术/投资/国际政治读者，是否真的有新增价值”。
请默认大部分文章只值 3 分左右；4.2 分以上必须非常少见，4.5 分以上必须近乎稀缺。

### 第一步：分析与思考 (Chain of Thought)
请先通读全文，**首先判断文章类型**，然后根据类型特点进行评估：

**类型识别指南**：
- **news（资讯）**: 报道事件、数据、发布消息，重点是“是什么”
- **tutorial（教程）**: 教授技能、展示步骤、提供代码，重点是“怎么做”
- **opinion（观点）**: 分析问题、评论现象、提出见解，重点是“为什么”

**针对性分析**：
- 资讯类：关注时效性、准确性、数据完整性
- 教程类：关注可复现性、步骤清晰度、实际解决问题
- 观点类：关注论证深度、独到见解、逻辑自洽

通用检查：
- 是否有过度的营销话术或误导性标题？
- 是否有明显的AI生成痕迹或逻辑混乱？

### 第二步：类型判断 & 负面检测
1. **判断文章类型**：`news` (资讯), `tutorial` (教程), `opinion` (观点).
2. **检测负面特征**：
   - `pure_promotion`: 纯广告/卖课/推销产品 (Soft Flag). **注意：技术视角的工具推荐、新功能发布、开源项目介绍、投行报告摘要均不算广告。**
   - `clickbait`: 标题党 (Soft Flag)
   - `ai_generated`: 明显的 AI 生成痕迹/逻辑混乱 (Hard Flag)

### 第三步：多维度打分 (1-5分，根据类型灵活评分)

> **重要：不同类型文章的评分侧重点不同，而且要默认从严。**

#### 通用评分标准
- 5分：极少出现，必须是罕见的高价值原创/深度内容
- 4分：明显有增量，值得优先看
- 3分：合格但常规，大部分文章应落在这里
- 1-2分：低价值或明显浪费时间

#### 维度详解（请根据文章类型调整评分重点）

1. **相关性**（所有类型的首要维度）
   - 是否符合用户人设（Tech / 投资 / 国际政治）
   - ⚠️ 如果相关性 < 2.5，即使其他维度再高，文章也不推荐

2. **信息量与准确性**
   - **news**: 核心维度！数据是否完整、来源是否可靠、是否有新增信息
   - **tutorial**: 步骤是否详尽、代码是否可用、是否解决真实问题
   - **opinion**: 论据是否充分、事实是否准确
   - 如果只是把公开信息重写、重新排版、泛泛总结，不能给高分

3. **深度与观点**（权重因类型而异）
   - **news**: ⚠️ 不强求深度分析！如果是及时、准确的市场动态/行业资讯，即使只是数据汇总，也应给 ≥3分
   - **tutorial**: 是否基于实践经验、是否覆盖常见坑点
   - **opinion**: 核心维度！是否有独到见解、论证是否深刻

4. **可读性**
   - 结构是否清晰、逻辑是否顺畅
   - tutorial类：步骤编号、代码格式是否清晰（权重更高）

5. **原创性/水分度**
   - news: 是否首发、是否洗稿
   - tutorial: ⚠️ 对于troubleshooting（排错）类文章，即使方案常见但只要解决了具体问题，也应给 ≥3分
   - opinion: 是否拄袖、是否泛泛而谈
   - 如果只是行业常识、旧观点重述、营销包装、术语堆砌但没有新增洞见，应明显压低

### 第四步：强制降温校准
请额外回答：
1. 这篇文章最主要的短板是什么？
2. 为什么它不配拿到 4.5+？
3. 是否存在以下负面信号（可多选）：
   - `generic_rehash`: 旧知识/公开信息重写
   - `low_novelty`: 缺乏新增信息或新增结论
   - `weak_evidence`: 结论强于证据
   - `shallow_take`: 看起来完整但分析浅
   - `marketing_tone`: 营销包装感过强
   - `no_actionable_detail`: 缺少可复用细节/可执行信息

如果你已经指出明显短板，就不要再给慷慨高分。

### 输出格式 (JSON Only)
请只返回以下 JSON 格式，不要包含其他文本：
{{
  "analysis": "1-2句话的简要分析，说明打分理由",
  "why_not_higher": "一句话说明为什么不该更高分；如果接近满分，也要说明稀缺性依据",
  "article_type": "news/tutorial/opinion",
  "red_flags": ["clickbait", ...],  // 无则为空数组
  "negative_signals": ["low_novelty", ...],  // 无则为空数组
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
摘要：{summary[:200] if summary else "无"}
正文：
{content_snippet}
"""


def build_batch_scoring_prompt(articles: list[dict]) -> str:
    """构建批量评分提示词 (JSON 数组输出)"""
    persona = PROJ_CONFIG.get("scoring_persona", "")
    today_str = datetime.now().strftime("%Y-%m-%d")

    items = []
    for idx, article in enumerate(articles):
        content_snippet = _build_content_snippet(article.get("content", ""))
        items.append(
            f"""
### 文章 {idx}
标题：{article.get("title", "")}
摘要：{(article.get("summary") or "")[:200] if article.get("summary") else "无"}
正文：
{content_snippet}
""".strip()
        )

    articles_block = "\n\n".join(items)

    return f"""{persona}

当前日期：{today_str}

请根据你的专业背景，对下面多篇文章逐一评分。请严格按照以下要求：
- 输出必须是 JSON 数组，数组内每个元素对应一篇文章
- 每个元素必须包含 "index" 字段（与文章编号一致）
- 不要输出任何额外文本
- 默认大部分文章只值 3 分左右，4.2+ 必须非常罕见

评分流程与要求：
1. 先判断文章类型：`news`（资讯）, `tutorial`（教程）, `opinion`（观点）
2. 检测负面特征：`pure_promotion`, `clickbait`, `ai_generated`
3. 按维度打分（1-5）：relevance, informativeness_accuracy, depth_opinion, readability, non_redundancy
4. 补充两个严格校准字段：
   - `why_not_higher`
   - `negative_signals`: `generic_rehash`, `low_novelty`, `weak_evidence`, `shallow_take`, `marketing_tone`, `no_actionable_detail`

输出格式（JSON Only）：
[
  {{
    "index": 0,
    "analysis": "1-2句话的简要分析",
    "why_not_higher": "为什么不该更高分",
    "article_type": "news/tutorial/opinion",
    "red_flags": ["clickbait"],
    "negative_signals": ["low_novelty"],
    "scores": {{
      "relevance": 1-5,
      "informativeness_accuracy": 1-5,
      "depth_opinion": 1-5,
      "readability": 1-5,
      "non_redundancy": 1-5
    }}
  }}
]

---
{articles_block}
"""


def calculate_weighted_score(
    scores: Dict[str, int], article_type: str, red_flags: list
) -> float:
    """
    计算加权总分 (动态权重 + 相关性熔断 + 负面惩罚)

    新算法特点:
    1. 使用百分比权重（总和为1.0），不同类型文章权重不同
    2. 相关性熔断机制：如果相关性过低，一票否决
    3. 优化的惩罚机制：Soft Flags 惩罚降低至0.5/项
    """
    # 1. 获取权重配置（现在是百分比形式）
    weights_config = PROJ_CONFIG.get("scoring_weights", {})
    weights = weights_config.get(article_type, weights_config.get("default", {}))

    # 2. 计算加权分（百分比权重，总和为1.0）
    weighted_score = 0.0
    for key, score in scores.items():
        w = weights.get(key, 0.2)  # 默认20%权重
        weighted_score += score * w
        logger.debug(f"  {key}: {score} × {w} = {score * w}")

    logger.debug(f"基础加权分: {weighted_score:.2f}")

    # 3. 相关性熔断机制（一票否决）
    relevance_threshold = PROJ_CONFIG.get("relevance_threshold", 2.5)
    relevance_score = scores.get("relevance", 5)

    if relevance_score < relevance_threshold:
        original_score = weighted_score
        weighted_score = min(weighted_score, relevance_threshold)
        logger.info(
            f"⚠️ 相关性熔断触发: relevance={relevance_score} < {relevance_threshold}, "
            f"总分限制 {original_score:.1f} → {weighted_score:.1f}"
        )

    # 4. 负面清单处理
    if red_flags:
        # Hard Flags: 直接打入冷宫（最高1.0分）
        if any(flag in HARD_RED_FLAGS for flag in red_flags):
            logger.warning(f"🚫 Hard Flag触发: {red_flags}, 总分锁定为1.0")
            return 1.0

        # Soft Flags: 每项扣0.5分（原来是1.0，过于严格）
        penalty = len(red_flags) * 0.5
        original_score = weighted_score
        weighted_score = max(1.0, weighted_score - penalty)
        logger.info(
            f"🚩 Soft Flags惩罚: {red_flags}, 扣{penalty}分, {original_score:.1f} → {weighted_score:.1f}"
        )

    return round(weighted_score, 1)


def calibrate_score_distribution(
    weighted_score: float,
    scores: Dict[str, int],
    article_type: str,
    red_flags: list[str],
    negative_signals: list[str],
    why_not_higher: str,
) -> float:
    """压缩高分通胀，让 4.2+ 变成真正稀缺分数。"""
    calibrated = weighted_score
    if weighted_score >= DEFAULT_SCORE_ANCHOR:
        calibrated = DEFAULT_SCORE_ANCHOR + (
            weighted_score - DEFAULT_SCORE_ANCHOR
        ) * 0.72
    else:
        calibrated = DEFAULT_SCORE_ANCHOR - (
            DEFAULT_SCORE_ANCHOR - weighted_score
        ) * 0.9

    if negative_signals:
        calibrated -= min(1.2, len(negative_signals) * NEGATIVE_SIGNAL_PENALTY)

    if why_not_higher and why_not_higher.strip():
        calibrated -= 0.1

    relevance = scores.get("relevance", 0)
    informativeness = scores.get("informativeness_accuracy", 0)
    depth = scores.get("depth_opinion", 0)
    non_redundancy = scores.get("non_redundancy", 0)

    if informativeness <= 3:
        calibrated = min(calibrated, 3.8)
    if non_redundancy <= 3:
        calibrated = min(calibrated, 3.7)
    if article_type != "news" and depth <= 3:
        calibrated = min(calibrated, 4.0)
    if relevance <= 3:
        calibrated = min(calibrated, 3.5)

    if weighted_score >= 4.5:
        qualifies_rare_high_score = (
            relevance >= 5
            and informativeness >= 5
            and non_redundancy >= 4
            and (depth >= 4 or article_type == "news")
            and not red_flags
            and not negative_signals
        )
        if not qualifies_rare_high_score:
            calibrated = min(calibrated, 4.3)
    elif weighted_score >= 4.0:
        qualifies_clear_recommendation = (
            relevance >= 4 and informativeness >= 4 and non_redundancy >= 4
        )
        if not qualifies_clear_recommendation:
            calibrated = min(calibrated, 3.9)

    return round(max(1.0, min(5.0, calibrated)), 1)


def extract_json_from_response(response_text: str) -> str | None:
    """
    从 LLM 响应中提取 JSON，支持多种格式：
    1. 纯 JSON 响应
    2. Markdown 代码块中的 JSON
    3. 思维链后面跟着的 JSON
    """
    # 策略1: 尝试提取 Markdown 代码块中的 JSON
    code_block_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL
    )
    if code_block_match:
        return code_block_match.group(1)

    # 策略2: 找到所有完整的 JSON 对象，取最后一个（通常思维链在前，JSON在后）
    # 使用非贪婪匹配，找每个独立的 {...} 块
    json_objects = []
    depth = 0
    start_idx = None

    for i, char in enumerate(response_text):
        if char == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start_idx is not None:
                candidate = response_text[start_idx : i + 1]
                # 验证是否是有效 JSON
                try:
                    json.loads(candidate)
                    json_objects.append(candidate)
                except json.JSONDecodeError:
                    pass
                start_idx = None

    if json_objects:
        # 优先返回包含 "scores" 字段的 JSON（这是我们期望的格式）
        for obj in reversed(json_objects):
            if '"scores"' in obj:
                return obj
        # 否则返回最后一个有效 JSON
        return json_objects[-1]

    # 策略3: 回退到原来的贪婪匹配（兼容性）
    json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response_text, re.DOTALL)
    if json_match:
        return json_match.group()

    return None


def extract_json_array_from_response(response_text: str) -> str | None:
    """从 LLM 响应中提取 JSON 数组，支持 markdown 代码块和智能边界识别。"""
    # 策略1: 尝试提取 Markdown 代码块 (更宽松的正则)
    # 匹配 ```json ... ``` 或 ``` ... ```
    code_block_match = re.search(r"```(?:json)?\s*(.*?)```", response_text, re.DOTALL)
    if code_block_match:
        content = code_block_match.group(1).strip()
        if content.startswith("[") and content.endswith("]"):
            return content

    # 策略2: 智能寻找最外层的 [] 对，且忽略字符串内的括号
    # 这比简单的深度计数更健壮，能处理 [{"title": "文章[1]"}] 这种情况

    candidates = []

    # 寻找所有的 '[' 作为潜在起点
    start_indices = [m.start() for m in re.finditer(r"\[", response_text)]

    for start in start_indices:
        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(response_text)):
            char = response_text[i]

            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        # 找到闭合的数组
                        candidate = response_text[start : i + 1]
                        try:
                            # 验证是否为有效 JSON
                            json.loads(candidate)
                            candidates.append(candidate)
                            # 找到一个有效的就跳出内层循环，继续找下一个可能的起点（虽然通常只要找到最大的那个就行）
                            break
                        except json.JSONDecodeError:
                            pass

    if candidates:
        # 返回最长的那个（通常是最外层的）
        return max(candidates, key=len)

    return None


def _score_from_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """从已解析的 JSON 数据生成评分结果。"""
    scores = data.get("scores", {})
    article_type = data.get("article_type", "default")
    red_flags = data.get("red_flags", [])
    negative_signals = data.get("negative_signals", [])
    analysis_text = data.get("analysis", "")
    why_not_higher = data.get("why_not_higher", "")

    weighted_score = calculate_weighted_score(scores, article_type, red_flags)
    overall_score = calibrate_score_distribution(
        weighted_score,
        scores,
        article_type,
        red_flags,
        negative_signals,
        why_not_higher,
    )

    if overall_score >= HIGH_SCORE_THRESHOLD:
        verdict = "强烈推荐"
    elif overall_score >= RECOMMENDED_SCORE_THRESHOLD:
        verdict = "值得阅读"
    elif overall_score >= 3.0:
        verdict = "一般，可选阅读"
    else:
        verdict = "不太值得阅读"

    if red_flags:
        verdict += f" (含 {', '.join(red_flags)})"

    return {
        "relevance_score": scores.get("relevance", 0),
        "informativeness_accuracy_score": scores.get("informativeness_accuracy", 0),
        "depth_opinion_score": scores.get("depth_opinion", 0),
        "readability_score": scores.get("readability", 0),
        "non_redundancy_score": scores.get("non_redundancy", 0),
        "weighted_score": weighted_score,
        "overall_score": overall_score,
        "verdict": verdict,
        "reason": analysis_text,
        "comment": data.get("comment", analysis_text),
        "why_not_higher": why_not_higher,
        "negative_signals": negative_signals,
        "article_type": article_type,
        "red_flags": red_flags,
        "detailed_scores": data,
        "score": overall_score,
    }


def parse_score_response(response_text: str) -> Dict[str, Any]:
    """解析响应并计算总分"""
    try:
        # 使用改进的 JSON 提取方法
        json_str = extract_json_from_response(response_text)
        if json_str:
            data = json.loads(json_str)
            return _score_from_data(data)

        return _default_error_result(f"无法解析JSON: {response_text[:200]}")
    except json.JSONDecodeError as e:
        # JSON解析错误，记录更详细的信息
        logger.error(f"JSON解析失败: {e}")
        logger.error(f"原始响应内容: {response_text[:500]}...")
        return _default_error_result(
            f"JSON解析错误: {e} | 响应片段: {response_text[:100]}"
        )
    except Exception as e:
        logger.error(f"解析失败: {e}")
        logger.error(f"原始响应内容: {response_text[:500]}...")
        return _default_error_result(f"解析异常: {e}")


def _default_error_result(msg: str):
    return {
        "overall_score": 0.0,
        "verdict": "解析错误",
        "reason": msg,
        "comment": msg,
        "red_flags": [],
        "detailed_scores": {},
    }


def score_article(title: str, summary: str, content: str) -> Dict[str, Any]:
    """
    对文章进行多维度评分
    """
    try:
        openai_config = get_openai_task_config("analysis", default_model="gpt-4o-mini")
        logger.info(f"Single Scoring - Connecting to: {openai_config.base_url}")

        client = OpenAI(**build_openai_client_kwargs(openai_config))

        logger.info(f"Single Scoring - Using Model: {openai_config.model}")

        prompt = build_scoring_prompt(title, summary, content)
        log_debug("Scoring Prompt", prompt)

        response = client.chat.completions.create(
            model=openai_config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=16000,  # 增加 Token 上限以容纳 Analysis
        )

        response_text = response.choices[0].message.content
        log_debug("Scoring Response", response_text)

        if not response_text:
            return _default_error_result("模型返回为空")

        result = parse_score_response(response_text)

        # 补全 score 字段，兼容旧的 article_analyzer 调用
        result["score"] = result["overall_score"]
        result["model"] = openai_config.model

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
        emoji = "🗑️"  # 垃圾桶
    elif overall < 3.0:
        emoji = "👎"

    return f"{emoji} {verdict} ({overall}/5.0)"


def parse_batch_score_response(
    response_text: str, expected_count: int
) -> list[Dict[str, Any]] | None:
    """
    解析批量评分响应并返回结果列表，失败时返回 None。
    改进逻辑：
    1. 即使 JSON 数组未闭合，也尝试提取已解析的对象。
    2. 如果数量不足，返回部分结果（列表长度 < expected_count），由调用者负责补全。
    """
    try:
        # 1. 尝试完整解析
        json_str = extract_json_array_from_response(response_text)
        data = None
        if json_str:
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 2. 如果完整解析失败，尝试流式提取（应对截断情况）
        if not data:
            data = _robust_parse_objects(response_text)

        if not data or not isinstance(data, list):
            logger.warning("Batch parse failed: No valid objects found")
            return None

        results_by_index = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            score_result = _score_from_data(item)
            if index is not None:
                results_by_index[index] = score_result

        if not results_by_index:
            return None

        # 3. 构造有序列表（包含 None 占位符）
        ordered = []
        valid_count = 0
        for i in range(expected_count):
            if i in results_by_index:
                ordered.append(results_by_index[i])
                valid_count += 1
            else:
                ordered.append(None)  # 标记为缺失

        if valid_count == 0:
            return None

        # 只要有部分成功，就返回这个包含 None 的列表
        return ordered

    except Exception as e:
        logger.error(f"批量解析失败: {e}")
        return None


def _robust_parse_objects(text: str) -> list[dict]:
    """
    从可能截断的文本中尽可能多地提取 JSON 对象。
    原理：查找所有 {"index": ...} 模式的块，尝试解析。
    """
    objects = []
    # 查找所有潜在的对象起始点
    # 假设每个对象都以 {"index": 开头（受 prompt 约束）
    # 或者通用的 { ... }

    # 简单策略：按 '{"index":' 分割，或者使用非贪婪正则提取
    # 注意：正则可能无法处理嵌套大括号，所以这里使用一个简单的栈式解析器扫描

    start_indices = [m.start() for m in re.finditer(r'\{\s*"index"', text)]

    for start in start_indices:
        # 尝试从 start 开始向后寻找合法的闭合 }
        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            char = text[i]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        # 找到一个完整的对象候选
                        candidate = text[start : i + 1]
                        try:
                            obj = json.loads(candidate)
                            objects.append(obj)
                        except Exception:
                            pass
                        break  # 跳出内层循环，处理下一个 start
    return objects


def score_articles_batch(
    articles: list[dict], max_retries: int = 3
) -> list[Dict[str, Any]] | None:
    """对多篇文章进行批量评分，支持重试和部分恢复，失败时返回 None。"""
    try:
        openai_config = get_openai_task_config("analysis", default_model="gpt-4o-mini")
        logger.info(f"Batch Scoring - Connecting to: {openai_config.base_url}")

        client = OpenAI(**build_openai_client_kwargs(openai_config))
    except Exception as e:
        logger.error(f"Client init failed: {e}")
        return None

    prompt = build_batch_scoring_prompt(articles)
    log_debug("Batch Scoring Prompt", prompt)

    for attempt in range(max_retries):
        try:
            logger.info(f"Batch scoring attempt {attempt + 1}/{max_retries}...")
            logger.info(f"Batch Scoring - Using Model: {openai_config.model}")

            response = client.chat.completions.create(
                model=openai_config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=16000,  # Explicitly set high limit for Gemini
            )

            response_text = response.choices[0].message.content
            log_debug(f"Batch Scoring Response (Attempt {attempt + 1})", response_text)

            if not response_text:
                logger.warning(f"Batch attempt {attempt + 1} failed: Empty response")
                continue

            # 解析结果（可能包含 None）
            batch_results = parse_batch_score_response(response_text, len(articles))

            if batch_results:
                # 检查是否有缺失项 (None)
                missing_indices = [i for i, r in enumerate(batch_results) if r is None]

                # 为所有成功的结果添加模型信息
                for res in batch_results:
                    if res:
                        res["model"] = openai_config.model

                if not missing_indices:
                    return batch_results  # 完美成功

                logger.warning(
                    f"Batch attempt {attempt + 1} partial success. Missing indices: {missing_indices}. Filling gaps..."
                )

                # 补全缺失项（单篇调用）
                for i in missing_indices:
                    logger.info(f"Filling gap for article {i} (single mode)...")
                    article = articles[i]
                    # 使用单篇评分补全
                    try:
                        score_result = score_article(
                            article.get("title", ""),
                            article.get("summary", ""),
                            article.get("content", ""),
                        )
                        batch_results[i] = score_result
                    except Exception as e:
                        logger.error(f"Failed to fill gap for article {i}: {e}")
                        # 保持 None 或者填入错误占位符，这里填入默认错误
                        batch_results[i] = _default_error_result(
                            f"Fill gap failed: {e}"
                        )

                return batch_results

            logger.warning(
                f"Batch attempt {attempt + 1} failed: Parse error or no valid objects found"
            )
            logger.warning(f"Response length: {len(response_text)} chars")
            logger.warning(
                f"Response starts with: {response_text[:200] if response_text else 'EMPTY'}"
            )
            logger.warning(
                f"Response ends with: {response_text[-200:] if response_text else 'EMPTY'}"
            )

        except Exception as e:
            # 智能退避策略 (Exponential Backoff)
            is_rate_limit = isinstance(e, RateLimitError) or "429" in str(e)

            if is_rate_limit:
                # 指数退避: 1s, 2s, 4s... + 随机抖动
                delay = (2**attempt) * 1.5 + random.uniform(0, 1)
                logger.warning(
                    f"⚠️ Batch attempt {attempt + 1} hit Rate Limit (429). Cooling down for {delay:.2f}s..."
                )
                time.sleep(delay)
            else:
                logger.warning(f"Batch attempt {attempt + 1} exception: {e}")
                # 对于非 429 错误，也稍微等待一下避免死循环轰炸
                time.sleep(1)

    logger.error("All batch scoring attempts failed.")
    return None




