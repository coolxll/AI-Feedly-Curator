# Final Report Template

Use this template when turning an `output/reading-reports/<timestamp>/reading-packet.json` file into a human-facing reading report.

## Requirements

- Write in Markdown.
- Keep conclusions and original links in the same document.
- Every article mention must use a Markdown link: `[title](url)`.
- Mark low-confidence items when they rely on `摘要回退` or `抓取失败`.
- Prefer concise judgment over long paraphrase.

## Template

```md
# 阅读报告

- 输入文件: `<input_file>`
- 分析样本: `<total_articles>` 篇
- 证据覆盖: `<正文_count>` 篇正文，`<RSS全文_count>` 篇 RSS 全文，`<摘要回退_count>` 篇摘要回退，`<抓取失败_count>` 篇抓取失败

## 总体摘要

用 2-4 句话总结这一批文章最值得关注的主线。这里必须直接提到 2-4 篇最值得点开的文章，并使用链接：
例如：[文章标题](https://example.com)

## 值得关注

- [文章标题](https://example.com)：一句话说明为什么值得关注。
- [文章标题](https://example.com)：一句话说明为什么值得关注。
- [文章标题](https://example.com)：一句话说明为什么值得关注。

## 阅读策略

- 第一优先级：先读哪些文章，直接列链接。
- 第二优先级：再读哪些文章，直接列链接。
- 哪些类别可以整体后置。

## 风险提醒

- 哪些结论主要基于 `摘要回退`。
- 哪些正文其实是论坛壳或低信息密度内容。
- 哪些主题噪音较多、容易浪费时间。

## 必读

### 1. [文章标题](https://example.com)
- 证据: `正文 / RSS全文 / 摘要回退 / 抓取失败`
- 建议: 必读
- 理由: 1-2 句话说明为什么值得投入时间。

### 2. [文章标题](https://example.com)
- 证据: `正文 / RSS全文 / 摘要回退 / 抓取失败`
- 建议: 必读
- 理由: 1-2 句话说明为什么值得投入时间。

## 选读

### 1. [文章标题](https://example.com)
- 证据: `正文 / RSS全文 / 摘要回退 / 抓取失败`
- 建议: 选读
- 理由: 1-2 句话说明为什么值得顺手看，但不必优先。

### 2. [文章标题](https://example.com)
- 证据: `正文 / RSS全文 / 摘要回退 / 抓取失败`
- 建议: 选读
- 理由: 1-2 句话说明为什么值得顺手看，但不必优先。

## 跳过

- [文章标题](https://example.com)
  理由: 一句话说明为什么可以跳过。
- [文章标题](https://example.com)
  理由: 一句话说明为什么可以跳过。

## 配套文件

- 原文索引: `<sources_md_path>`
- 机器素材包: `<reading_packet_json_path>`
```

## Selection guidance

- `必读`: high relevance + meaningful information gain + strong enough evidence.
- `选读`: useful but narrower, weaker, or lower leverage.
- `跳过`: noise, repetition, promotion, low relevance, or low information density.
- If a recommended item is based on `摘要回退`, explicitly say it should be opened and verified in the original post.

