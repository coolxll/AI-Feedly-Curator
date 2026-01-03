# RSS Article Analyzer

AI 驱动的 RSS 文章分析器，自动从 Feedly 获取未读文章，使用 LLM 进行内容分析评分，并生成总体摘要报告。

## 功能特性

- 📥 **Feedly 集成** - 自动从 Feedly 获取未读文章
- 🤖 **AI 多维度评分** - 基于相关性、信息量、深度等维度进行 1-5 分量化评分
- 🚩 **负面特征检测** - 自动识别软文、标题党、AI 生成及过时信息
- 📊 **总体报告** - 生成包含趋势分析和高质量推荐的 Markdown 报告
- 🔄 **多 Profile 支持** - 灵活切换不同的 API 服务商（支持不同任务使用不同模型）
- ✅ **自动标记已读** - 处理后自动同步 Feedly 阅读状态

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并填入你的 API 密钥：

```bash
cp .env.example .env
```

### 3. 运行

```bash
# 从 Feedly 获取文章并分析
python article_analyzer.py --refresh

# 分析已有的文章
python article_analyzer.py --input unread_news.json

# 限制处理数量并标记已读
python article_analyzer.py --refresh --limit 50 --mark-read

# 重新生成总体摘要（基于已分析的文章，不重新调用 API 评分）
python regenerate_summary.py
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input` | 输入 JSON 文件 | `unread_news.json` |
| `--limit` | 处理文章数量 | `100` |
| `--refresh` | 从 Feedly 刷新文章 | `False` |
| `--mark-read` | 标记已读 | `True` |
| `--debug` | 启用调试模式 | `False` |

## 多 Profile 配置

支持配置多个 API 服务商并灵活切换，**Profile 使用大写命名**。

### 在 `.env` 中定义 Profile

```env
# Profile: LOCAL_QWEN (本地 Qwen 代理)
LOCAL_QWEN_OPENAI_API_KEY=sk-xxx
LOCAL_QWEN_OPENAI_BASE_URL=http://127.0.0.1:8045/v1
LOCAL_QWEN_OPENAI_MODEL=qwen-flash

# Profile: DEEPSEEK
DEEPSEEK_OPENAI_API_KEY=sk-xxx
DEEPSEEK_OPENAI_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_OPENAI_MODEL=deepseek-v3.2
```

### 在代码中指定 Profile

编辑 `rss_analyzer/config.py` 中的 `PROJ_CONFIG`：

```python
PROJ_CONFIG = {
    # ...
    "analysis_profile": "LOCAL_QWEN",   # 文章分析评分用本地模型
    "summary_profile": "DEEPSEEK",      # 总体报告生成用更强的模型
}
```

## 评分系统

系统使用结构化 Prompt 进行评估，包含：
- **Persona 偏好**：可自定义关注点（如测试开发、DevOps 等）
- **动态权重**：根据文章类型（新闻、教程、观点）自动调整评分权重
- **惩罚机制**：发现 Red Flags（如 `clickbait`）时自动降低评分

## 项目结构与输出

```
rss-opml/
├── article_analyzer.py   # 主程序入口
├── regenerate_summary.py # 重新生成摘要脚本
├── rss_analyzer/         # 核心代码
│   ├── config.py         # 配置文件
│   ├── scoring.py        # 评分逻辑
│   ├── llm_analyzer.py   # LLM 交互
│   └── ...
├── output/               # 输出目录
│   ├── 2026-01/          # 按月份归档
│   │   ├── analyzed_articles_20260103_120000.json
│   │   └── summary_20260103_120000.md
│   └── summary_latest.md # 最新生成的摘要报告
└── tests/                # 单元测试
```

## 测试

运行所有测试：

```bash
python -m unittest discover tests
```

## License

MIT
