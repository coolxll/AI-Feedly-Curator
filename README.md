# AI-Feedly-Curator

AI 驱动的 RSS 文章分析器，自动从 Feedly 获取未读文章，使用 LLM 进行内容分析评分，并生成总体摘要报告。

## 功能特性

- 📥 **Feedly 集成** - 自动从 Feedly 获取未读文章
- 🤖 **AI 多维度评分** - 基于相关性、信息量、深度等维度进行 1-5 分量化评分
- 🚩 **负面特征检测** - 自动识别软文、标题党、AI 生成及过时信息
- 📊 **总体报告** - 生成包含趋势分析和高质量推荐的 Markdown 报告
- 🔄 **按任务切模型** - 共用一套 API Key / Base URL，按分析和总结切换不同模型
- 🧠 **Embedding 独立配置** - 向量检索可单独指定 provider / model，并对变更给出重建提示
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
python article_analyzer.py --input output/unread_news.json

# 限制处理数量并标记已读（默认不标记，需显式开启）
python article_analyzer.py --refresh --limit 50 --mark-read

# 重新生成总体摘要（基于已分析的文章，不重新调用 API 评分）
python regenerate_summary.py

# 从 SQLite 缓存重建本地向量库
python rebuild_vector_store.py
```

### 4. Feedly Web UI AI 覆盖（Chrome 扩展 + 本地 HTTP 服务）

#### 4.1 启动本地服务

```bash
# 使用 uv 运行（推荐）
uv run python rss_backend_service.py --host 127.0.0.1 --port 8765

# 或者直接运行
python rss_backend_service.py --host 127.0.0.1 --port 8765
```

注意：
- 如果你本机全局 Python 安装过不一致版本的 `opentelemetry-*` / `chromadb`，直接用 `python` 可能触发导入失败
- 这类问题优先用 `uv run python ...` 或项目 `.venv` 解释器规避，不要依赖全局 Python 环境

服务默认共享仓库根目录下的：
- `rss_scores.db`
- `chroma_db/`

如需覆盖路径，可设置环境变量：
- `RSS_SCORES_DB`
- `RSS_VECTOR_DB_DIR`
- `RSS_VECTOR_BACKEND`
- `RSS_VECTOR_HTTP_URL`
- `RSS_VECTOR_STATE_DIR`

#### 4.2 加载扩展

1. 打开 `chrome://extensions`，启用开发者模式
2. 选择“加载已解压的扩展”，选择 `extension/` 目录
3. 打开扩展设置页，确认 `Server Base URL` 指向本地服务，例如 `http://127.0.0.1:8765`
4. 点击 `Test Backend` 验证连通性

#### 4.3 使用

打开 Feedly Web：
- `https://feedly.com/*`
- `https://cloud.feedly.com/*`

列表与详情中会展示评分与摘要覆盖层。

#### 4.4 架构说明

- Chrome 扩展现在只负责 UI 注入、页面内容提取和交互展示
- AI 分析、摘要生成、缓存和向量检索统一由本地 Python 服务处理
- 这让 Chrome 扩展和本地 GUI/TUI/Streamlit 可以共享同一后端，而不是各自直连模型或宿主进程

详细边界设计见 [docs/client-server-architecture.md](docs/client-server-architecture.md)。

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input` | 输入 JSON 文件 | `output/unread_news.json` |
| `--limit` | 处理文章数量 | `100` |
| `--refresh` | 从 Feedly 刷新文章 | `False` |
| `--mark-read` | 标记已读 | `False` |
| `--debug` | 启用调试模式 | `False` |

## 按任务配置模型

当前配置推荐只保留两个 task：`analysis` 和 `summary`。

### 在 `.env` 中按任务定义

```env
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=http://127.0.0.1:8045/v1

ANALYSIS_OPENAI_MODEL=qwen-flash

SUMMARY_OPENAI_MODEL=deepseek-v3.2

EMBEDDING_API_KEY=sk-embedding-xxx
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3
```

### 配置优先级

1. 环境变量中的 task model，例如 `SUMMARY_OPENAI_MODEL`
2. 普通环境变量，例如 `OPENAI_MODEL`
3. 通用 `OPENAI_API_KEY` / `OPENAI_BASE_URL`

### Embedding 配置

- 向量检索不再回退到 `OPENAI_BASE_URL`，避免聊天 provider 变更误伤 embedding
- 推荐显式配置 `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL`
- 若未显式配置，embedding 仍会兼容已有 DashScope / Aliyun 环境变量，并默认使用 `text-embedding-v3`
- `chroma_db/` 下会记录 embedding 指纹；若你改了 embedding base URL 或 model，服务会警告需要重建向量库

### Vector Store 后端

支持两种 Chroma 模式：

- `RSS_VECTOR_BACKEND=embedded`
  - 默认模式
  - 使用本地 `chroma_db/`
  - Windows 上若本地索引损坏，启动时会自动隔离到 `chroma_db_quarantine_*`
- `RSS_VECTOR_BACKEND=http`
  - 使用 Docker / 自托管 Chroma HTTP 服务
  - 本地仅保留 `vector_store_state/` 下的 embedding 指纹文件
  - 连接地址由 `RSS_VECTOR_HTTP_URL` 控制，例如 `http://127.0.0.1:8000`

切换到 Docker Chroma：

```env
RSS_VECTOR_BACKEND=http
RSS_VECTOR_HTTP_URL=http://127.0.0.1:8000
RSS_VECTOR_STATE_DIR=vector_store_state
```

### 重建向量库

当以下情况出现时，建议重建本地向量库：
- 你切换了 `EMBEDDING_MODEL`
- 你切换了 `EMBEDDING_BASE_URL` 或 embedding provider
- 你怀疑历史向量和当前缓存数据不一致

可直接运行：

```bash
uv run python rebuild_vector_store.py
```

该命令会：
- 清空当前 Chroma collection
- 用当前 embedding 配置刷新指纹
- 从 `rss_scores.db` 中的缓存文章重新写入向量

如果你刚从 embedded 迁到 Docker HTTP 模式，先启动容器并设置：

```env
RSS_VECTOR_BACKEND=http
RSS_VECTOR_HTTP_URL=http://127.0.0.1:8000
```

然后执行同一个命令：

```bash
uv run python rebuild_vector_store.py
```

这会把 SQLite 缓存中的文章重新写入 Docker 上的 Chroma collection。

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
│   ├── unread_news.json
│   ├── analyzed_articles_latest.json
│   └── summary_latest.md
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


