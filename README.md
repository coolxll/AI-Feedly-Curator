# RSS Article Analyzer

AI 驱动的 RSS 文章分析器，自动从 Feedly 获取未读文章，使用 LLM 进行内容分析评分，并生成总体摘要报告。

## 功能特性

- 📥 **Feedly 集成** - 自动从 Feedly 获取未读文章
- 🤖 **AI 分析** - 使用 LLM 对每篇文章进行评分和摘要
- 📊 **总体报告** - 生成包含趋势分析和推荐的 Markdown 报告
- 🔄 **多 Profile 支持** - 灵活切换不同的 API 服务商
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

# 限制处理数量
python article_analyzer.py --refresh --limit 50
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

支持配置多个 API 服务商并灵活切换，**Profile 使用大写命名**：

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

编辑 `src/config.py` 中的 `PROJ_CONFIG`：

```python
PROJ_CONFIG = {
    # ...
    "analysis_profile": "LOCAL_QWEN",   # 文章分析用本地模型
    "summary_profile": "DEEPSEEK",      # 总结生成用 DeepSeek
}
```

## 项目结构

```
rss-opml/
├── article_analyzer.py   # 主程序入口
├── src/                  # 源码目录
│   ├── __init__.py
│   ├── config.py         # 配置管理
│   ├── feedly_client.py  # Feedly API 客户端
│   ├── article_fetcher.py# 文章内容抓取
│   ├── llm_analyzer.py   # LLM 分析模块
│   └── utils.py          # 工具函数
├── .env                  # 环境变量 (不提交)
├── .env.example          # 环境变量模板
└── requirements.txt      # 依赖列表
```

## License

MIT
