# Arena-App Rust 迁移兼容契约

## 1. Target 配置契约

### 1.1 Target 格式解析
```
label|model|base_url|api_key_token
```

### 1.2 api_key_token 解析语义
1. 首先尝试作为环境变量名读取: `std::env::var(api_key_token)`
2. 如果环境变量不存在，则直接使用该字符串作为 api_key
3. 这个行为必须与 Python `_parse_target_spec()` 完全一致

### 1.3 Target 配置示例
```json
{
  "targets": [
    "gpt-4o|gpt-4o-mini|https://api.openai.com/v1/|OPENAI_API_KEY",
    "qwen|qwen-turbo|https://dashscope.aliyuncs.com/v1/|sk-xxxxxx"
  ]
}
```

## 2. 评分结果一致性契约

### 2.1 批量评分行为契约

**成功路径**:
1. 调用 OpenAI API 获取批量评分响应
2. 解析 JSON 数组，提取每个文章的评分结果
3. 对每个结果调用 `_score_from_data()` 计算最终分数
4. 返回完整的结果列表

**部分失败恢复** (关键行为):
1. 如果批量响应解析后某些索引缺失 (返回 `None` 占位符)
2. 对缺失的索引，使用单篇评分 `score_article()` 补全
3. 单篇失败时填入 `_default_error_result()`
4. 最终返回完整列表，不允许有 `None` 项

**完全失败回退**:
1. 批量评分返回 `None` 时
2. 逐篇调用单篇评分作为 fallback
3. 保持与输入相同的顺序

### 2.2 JSON 解析鲁棒性契约

**批量响应解析策略** (按优先级):
1. 尝试提取 Markdown 代码块中的 JSON 数组
2. 尝试完整解析响应中的 JSON 数组
3. 如果失败，使用 `_robust_parse_objects()` 流式提取:
   - 查找所有 `{"index":` 模式的起始位置
   - 使用栈式解析器找到匹配的闭合 `}`
   - 尝试解析每个提取的对象
4. 返回按索引组织的结果，缺失的索引用 `None` 占位

**单篇响应解析策略**:
1. 尝试提取 Markdown 代码块中的 JSON
2. 尝试找到所有完整的 `{...}` 块，取最后一个（思维链在前，JSON在后）
3. 优先选择包含 `"scores"` 字段的 JSON
4. 如果都失败，返回解析错误结果

### 2.3 分数计算契约

**加权分数计算** (`calculate_weighted_score`):
```rust
// 1. 获取类型对应的权重配置
weights = PROJ_CONFIG.scoring_weights[article_type] || PROJ_CONFIG.scoring_weights["default"]

// 2. 计算加权分 (百分比权重，总和为1.0)
weighted_score = sum(score * weight for each dimension)

// 3. 相关性熔断
if relevance < relevance_threshold (2.5):
    weighted_score = min(weighted_score, relevance_threshold)

// 4. 负面标记惩罚
if hard_red_flags (ai_generated):
    return 1.0
if soft_red_flags:
    penalty = len(red_flags) * 0.5
    weighted_score = max(1.0, weighted_score - penalty)

return round(weighted_score, 1)
```

**分数校准** (`calibrate_score_distribution`):
```rust
// 1. 基础校准
if weighted_score >= 3.0:
    calibrated = 3.0 + (weighted_score - 3.0) * 0.72
else:
    calibrated = 3.0 - (3.0 - weighted_score) * 0.9

// 2. 负面信号惩罚
calibrated -= min(1.2, len(negative_signals) * 0.35)

// 3. 严格性校准
if why_not_higher 有内容:
    calibrated -= 0.1

// 4. 维度上限限制
if informativeness <= 3: calibrated = min(calibrated, 3.8)
if non_redundancy <= 3: calibrated = min(calibrated, 3.7)
if article_type != "news" and depth <= 3: calibrated = min(calibrated, 4.0)
if relevance <= 3: calibrated = min(calibrated, 3.5)

// 5. 高分稀缺性保护
if weighted_score >= 4.5:
    qualifies = relevance >= 5
              and informativeness >= 5
              and non_redundancy >= 4
              and (depth >= 4 or article_type == "news")
              and no red_flags
              and no negative_signals
    if not qualifies:
        calibrated = min(calibrated, 4.3)

// 6. 4.0+ 分保护
if weighted_score >= 4.0:
    qualifies = relevance >= 4 and informativeness >= 4 and non_redundancy >= 4
    if not qualifies:
        calibrated = min(calibrated, 3.9)

return round(max(1.0, min(5.0, calibrated)), 1)
```

**Verdict 判定**:
- score >= 4.2: "强烈推荐"
- score >= 3.6: "值得阅读"
- score >= 3.0: "一般，可选阅读"
- score < 3.0: "不太值得阅读"
- 如果有 red_flags: 在 verdict 后附加 `(含 {flags})`

### 2.4 重试与退避契约

**批量评分重试**:
- 最大重试次数: 3
- 指数退避: delay = (2^attempt) * 1.5 + random(0, 1) 秒
- 仅对 RateLimitError (429) 使用完整退避
- 其他错误等待 1 秒后重试

**单篇评分**: 不重试，直接返回错误结果

## 3. 进度与取消契约

### 3.1 进度事件模型

Rust 内部使用状态机产生进度事件，替代原来解析 Python 日志的方式:

```rust
enum RunPhase {
    Prepare,      // 准备输入数据
    TargetStart { label: String, index: usize },  // 开始处理某个 target
    BatchProgress { label: String, processed: usize, total: usize },
    Finalize,     // 生成报告
    Done,
    Cancelled,
    Error,
}

struct ProgressEvent {
    phase: RunPhase,
    current: usize,      // 总体进度当前值
    total: usize,        // 总体进度总值
    message: String,
    target: Option<String>,
}
```

### 3.2 取消机制

**取消信号传递**:
1. 前端调用 `stop_run()` 设置 `cancel_requested = true`
2. 评分循环定期检查取消信号
3. 发现取消后，优雅地停止当前批次，保存已完成的进度
4. 返回 Cancelled 状态，不生成完整报告

**取消检查点**:
- 每个 target 开始前
- 每批次评分完成后
- 单篇补全的间隙

## 4. Run Record Schema 契约

### 4.1 最终落盘格式

```json
{
  "id": "run-20250115-143052",
  "dataset": "mixed_feed_v1",
  "target": "gpt-4o|gpt-4o-mini|https://api.openai.com/v1/|OPENAI_API_KEY",
  "timestamp": "2025-01-15T14:30:52+08:00",
  "metrics": {
    "average_spread": 0.15,
    "max_spread": 0.8,
    "high_score_rate": 0.25,
    "negative_signal_presence_rate": 0.10,
    "cheap_vs_sota_gap": 0.3
  },
  "results": [
    {
      "item_id": "article-001",
      "title": "文章标题",
      "score": 4.2,
      "spread": 0.1,
      "reason": "评分理由"
    }
  ]
}
```

### 4.2 Metrics 计算契约

**average_spread**: 所有文章的 score_spread 平均值 (仅 repeat > 1 时有意义)

**max_spread**: 所有文章中最大的 score_spread

**high_score_rate**: score >= 4.2 的文章占比

**negative_signal_presence_rate**: 有 negative_signals 的文章占比

**cheap_vs_sota_gap**: 当前模型与其他模型平均分差的绝对值最大值 (仅多模型对比时有意义)

### 4.3 Report 生成契约

**单次运行报告** (`_build_report`):
```rust
{
  "generated_at": ISO8601,
  "source_file": input_path,
  "label": target.label,
  "model": target.model,
  "base_url": target.base_url,
  "article_count": rows.len(),
  "average_score": avg_score,
  "score_bands": { "4.2+": n, "3.6-4.1": n, ... },
  "article_types": { "news": n, "tutorial": n, ... },
  "top_origins": { "origin1": n, ... },
  "negative_signals": { "signal1": n, ... },
  "red_flags": { "flag1": n, ... },
  "top_articles": [...],      // 前10篇，按分数降序
  "bottom_articles": [...],   // 后10篇，按分数升序
  "rows": [...]               // 所有评分结果
}
```

**多次运行聚合** (`_aggregate_repeat_reports`):
- 对每个文章，计算多次运行的平均分、最小分、最大分、spread、stddev
- 保留最后一次运行的其他字段作为 representative
- stability.average_spread: 所有文章 spread 的平均值
- stability.largest_spreads: spread 最大的15篇文章

**多模型对比** (`_build_comparison`):
- 只比较所有模型都评分的文章 (common_ids)
- 计算每篇文章在不同模型间的 spread
- 返回分歧最大的15篇文章

## 5. 配置来源契约

### 5.1 Target 配置
- 来源: `arena/scoring/configs/targets.json`
- 格式: JSON 对象，targets 字段是字符串数组
- 每个字符串格式: `label|model|base_url|api_key_token`

### 5.2 评分参数配置

**硬编码默认值** (与 Python PROJ_CONFIG 一致):

```rust
const SCORING_PERSONA: &str = r#"
你是一名关注广泛的资深程序员...
"#;

const SCORING_WEIGHTS: ScoringWeights = ScoringWeights {
    news: DimensionWeights {
        relevance: 0.40,
        informativeness_accuracy: 0.35,
        depth_opinion: 0.05,
        readability: 0.15,
        non_redundancy: 0.05,
    },
    tutorial: DimensionWeights { ... },
    opinion: DimensionWeights { ... },
    default: DimensionWeights { ... },
};

const RELEVANCE_THRESHOLD: f64 = 2.5;
```

**可选配置文件** (`arena-app-config.toml`):
```toml
[scoring]
persona = "..."
relevance_threshold = 2.5

[scoring.weights.news]
relevance = 0.40
informativeness_accuracy = 0.35
# ...
```

### 5.3 OpenAI 请求参数

**请求体格式**:
```json
{
  "model": "gpt-4o-mini",
  "messages": [{"role": "user", "content": "prompt"}],
  "temperature": 0,
  "max_tokens": 16000
}
```

**Headers**:
- `Authorization: Bearer {api_key}`
- `Content-Type: application/json`
- 可选: `HTTP-Referer`, `X-Title`

## 6. 验证契约

### 6.1 结果一致性验证
- 使用相同数据集对比 Python 和 Rust 版本的评分结果
- 允许浮点数精度差异 (±0.1)
- 所有字段必须存在且类型正确

### 6.2 行为一致性验证
- 批量失败时正确回退到单篇
- 部分解析失败时正确补全
- 取消信号正确响应
- 进度事件正确产生

### 6.3 性能验证
- 评分速度不低于 Python 版本
- 内存使用合理
- 并发安全
