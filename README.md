# AI-Feedly-Curator

AI 驱动的 RSS 文章分析器，自动从 Feedly 获取未读文章，使用 LLM 进行内容分析评分，并生成总体摘要报告。

## 功能特性

- 📥 **Feedly 集成** - 自动从 Feedly 获取未读文章
- 🤖 **AI 多维度评分** - 基于相关性、信息量、深度等维度进行 1-5 分量化评分
- 🚩 **负面特征检测** - 自动识别软文、标题党、AI 生成及过时信息
- 📊 **总体报告** - 生成包含趋势分析和高质量推荐的 Markdown 报告
- 🔄 **按任务配置模型** - 支持为分析和总结分别指定不同的 API 地址与模型
- ✅ **可选标记已读** - 默认不自动标记，需显式开启

## 快速开始

### 1. 安装依赖

推荐使用 [uv](https://github.com/astral-sh/uv) 进行极速安装：

```bash
# 使用 uv (推荐)
uv pip install -r requirements.txt
uv pip install rich questionary prompt-toolkit

# 或者使用标准 pip
pip install -r requirements.txt
pip install rich questionary prompt-toolkit
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并填入你的 API 密钥：

```bash
cp .env.example .env
```

### 3. 运行

#### 交互式模式 (推荐)
项目提供了一个全功能的交互式终端界面，支持选择分类、过滤模式和分析配置：

```bash
# 使用 uv 运行
uv run feedly_tui.py

# 或者直接运行
python feedly_tui.py
```

#### 命令行模式
你也可以直接调用各组件脚本：

```bash
# 从 Feedly 获取文章并分析
python article_analyzer.py --refresh

# 分析已有的文章
python article_analyzer.py --input unread_news.json

# 限制处理数量并标记已读（默认不标记，需显式开启）
python article_analyzer.py --refresh --limit 50 --mark-read

# 重新生成总体摘要（基于已分析的文章，不重新调用 API 评分）
python regenerate_summary.py
```

### 4. Feedly Web UI AI 覆盖（Chrome 扩展 + Native Messaging）

#### 4.1 Native Host 安装（一次性）

```powershell
# 1) 修改 native_host/feedly_ai_overlay.json
#    - path: Python 可执行路径
#    - arguments: feedly_native_host.py 绝对路径
#    - allowed_origins: 你的 Chrome 扩展 ID

# 2) 注册 native host
powershell -ExecutionPolicy Bypass -File .\scripts\install_native_host.ps1
```

可选：如需指定数据库路径，设置环境变量 `RSS_SCORES_DB` 指向 `rss_scores.db`。

#### 4.2 加载扩展

1. 打开 `chrome://extensions`，启用开发者模式
2. 选择“加载已解压的扩展”，选择 `extension/` 目录
3. 复制扩展 ID 并填入 `native_host/feedly_ai_overlay.json` 的 `allowed_origins`

#### 4.3 使用

打开 Feedly Web：
- `https://feedly.com/*`
- `https://cloud.feedly.com/*`

列表与详情中会展示评分与摘要覆盖层。

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input` | 输入 JSON 文件 | `unread_news.json` |
| `--limit` | 处理文章数量 | `100` |
| `--refresh` | 从 Feedly 刷新文章 | `False` |
| `--mark-read` | 标记已读 | `False` |
| `--debug` | 启用调试模式 | `False` |

## 按任务配置模型

当前配置只保留 task-based 路径：`analysis` 和 `summary`。

### 在 `.env` 中按任务定义

```env
ANALYSIS_OPENAI_API_KEY=sk-xxx
ANALYSIS_OPENAI_BASE_URL=http://127.0.0.1:8045/v1
ANALYSIS_OPENAI_MODEL=qwen-flash

SUMMARY_OPENAI_API_KEY=sk-xxx
SUMMARY_OPENAI_BASE_URL=https://api.deepseek.com/v1
SUMMARY_OPENAI_MODEL=deepseek-v3.2
```

### 可选的 `ai_config.json`

也可以在仓库根目录放一个本地配置文件：

```json
{
  "ANALYSIS_OPENAI_MODEL": "qwen3-coder-plus",
  "SUMMARY_OPENAI_MODEL": "deepseek-v3.2"
}
```

### 配置优先级

1. `ai_config.json` 中的 task 键，例如 `ANALYSIS_OPENAI_MODEL`
2. `ai_config.json` 中的普通键，例如 `OPENAI_MODEL`
3. 环境变量中的 task 键，例如 `SUMMARY_OPENAI_API_KEY`
4. 普通环境变量，例如 `OPENAI_API_KEY`

## 评分系统

系统使用结构化 Prompt 进行评估，包含：
- **Persona 偏好**：可自定义关注点（如测试开发、DevOps 等）
- **动态权重**：根据文章类型（新闻、教程、观点）自动调整评分权重
- **惩罚机制**：发现 Red Flags（如 `clickbait`）时自动降低评分

## 项目结构与输出

```
AI-Feedly-Curator/
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

## Streamlit 可视化界面

项目还提供了 Streamlit Web 应用，用于可视化浏览和分析 RSS 文章数据。

### 启动 Streamlit 应用

```bash
# 使用 uv 运行 (推荐)
uv run streamlit run rss_analyzer/streamlit_app.py

# 或者直接运行
streamlit run rss_analyzer/streamlit_app.py
```

### 功能特性

- 📈 **数据概览** - 显示文章总数、评分分布、时间趋势等统计信息
- 🔍 **交互式搜索** - 支持按标题、内容、评分范围等条件搜索文章
- 📊 **可视化图表** - 评分分布直方图、时间趋势图、标签词云等
- 📋 **文章列表** - 分页显示文章列表，支持排序和筛选
- 🎯 **个性化推荐** - 基于评分和标签的智能推荐

## 测试

运行所有测试：

```bash
python -m unittest discover tests
```

## License

MIT


