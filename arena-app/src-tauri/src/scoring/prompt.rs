use chrono::Local;

/// 安全截断字符串，确保在 UTF-8 字符边界处截断
fn safe_truncate(s: &str, max_len: usize) -> &str {
    if s.len() <= max_len {
        return s;
    }
    // 从 max_len 位置向前查找，找到第一个有效的 UTF-8 字符边界
    let mut idx = max_len;
    while idx > 0 && !s.is_char_boundary(idx) {
        idx -= 1;
    }
    &s[..idx]
}

/// 构建单篇评分 prompt
pub fn build_scoring_prompt(title: &str, summary: &str, content: &str, persona: &str) -> String {
    let content_snippet = build_content_snippet(content);
    let today = Local::now().format("%Y-%m-%d");
    let summary_excerpt = safe_truncate(summary, 200);

    format!(r#"{}

当前日期：{}

请根据你的专业背景，按照以下步骤对文章进行深度评估。
你的任务不是判断"这像不像一篇合格文章"，而是判断"这篇对一个见多识广、阈值很高的技术/投资/国际政治读者，是否真的有新增价值"。
请默认大部分文章只值 3 分左右；4.2 分以上必须非常少见，4.5 分以上必须近乎稀缺。

### 第一步：分析与思考 (Chain of Thought)
请先通读全文，**首先判断文章类型**，然后根据类型特点进行评估：

**类型识别指南**：
- **news（资讯）**: 报道事件、数据、发布消息，重点是"是什么"
- **tutorial（教程）**: 教授技能、展示步骤、提供代码，重点是"怎么做"
- **opinion（观点）**: 分析问题、评论现象、提出见解，重点是"为什么"

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
标题：{}
摘要：{}
正文：
{}
"#,
        persona, today, title, summary_excerpt, content_snippet
    )
}

/// 构建批量评分 prompt
pub fn build_batch_scoring_prompt(
    articles: &[(String, String, String)], // (title, summary, content)
    persona: &str,
) -> String {
    let today = Local::now().format("%Y-%m-%d");

    let items: Vec<String> = articles
        .iter()
        .enumerate()
        .map(|(idx, (title, summary, content))| {
            let content_snippet = build_content_snippet(content);
            let summary_excerpt = safe_truncate(summary, 200);
            format!(
                r#"### 文章 {}
标题：{}
摘要：{}
正文：
{}"#,
                idx, title, summary_excerpt, content_snippet
            )
        })
        .collect();

    let articles_block = items.join("\n\n");

    format!(r#"{}

当前日期：{}

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
{}
"#,
        persona, today, articles_block
    )
}

/// 智能截断正文（在 UTF-8 字符边界处截断）
fn build_content_snippet(content: &str) -> String {
    if content.len() > 10000 {
        let head = safe_truncate(content, 6000);
        let tail_start = find_char_boundary(content, content.len() - 3000);
        let tail = &content[tail_start..];
        format!("{}\n\n...[内容过长，中间部分省略]...\n\n{}", head, tail)
    } else {
        content.to_string()
    }
}

/// 从指定位置向后查找 UTF-8 字符边界
fn find_char_boundary(s: &str, start: usize) -> usize {
    let mut idx = start;
    while idx < s.len() && !s.is_char_boundary(idx) {
        idx += 1;
    }
    idx
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_scoring_prompt_contains_required_fields() {
        let prompt = build_scoring_prompt("Test Title", "Test Summary", "Test Content", "Test Persona");

        assert!(prompt.contains("Test Title"));
        assert!(prompt.contains("Test Summary"));
        assert!(prompt.contains("Test Content"));
        assert!(prompt.contains("Test Persona"));
        assert!(prompt.contains("analysis"));
        assert!(prompt.contains("scores"));
        assert!(prompt.contains("relevance"));
    }

    #[test]
    fn test_build_content_snippet_short() {
        let content = "Short content";
        let snippet = build_content_snippet(content);
        assert_eq!(snippet, content);
    }

    #[test]
    fn test_build_content_snippet_long() {
        let content = "a".repeat(15000);
        let snippet = build_content_snippet(&content);
        assert!(snippet.contains("...[内容过长，中间部分省略]..."));
        assert!(snippet.len() < content.len());
    }

    #[test]
    fn test_build_content_snippet_long_utf8() {
        let content = "你好世界".repeat(4000);
        let snippet = build_content_snippet(&content);
        assert!(snippet.contains("...[内容过长，中间部分省略]..."));
        assert!(std::str::from_utf8(snippet.as_bytes()).is_ok());
    }
}
