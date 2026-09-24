# AI-Feedly-Curator

AI 驱动的 RSS 文章分析器，自动从 Feedly 获取未读文章，使用 LLM 进行内容分析评分，并生成总体摘要报告。

## 功能特性

- 📥 **Feedly 集成** - 自动从 Feedly 获取未读文章，统一 OAuth/PKCE 鉴权、自动刷新、429 退避重试与超时保护
- 🤖 **AI 多维度评分** - 基于相关性、信息量、深度等维度进行 1-5 分量化评分与版本化缓存
- ⚡ **并发网页预取** - 线程池并行提取网页正文，彻底消除串行网络 I/O 阻塞
- 🖥️ **全功能交互 TUI** - 交互式分类选择、文章审查（Review）、未读清理与报表导出
- 🚩 **负面特征检测** - 自动识别软文、标题党、AI 生成及过时信息
- 📊 **总体报告** - 生成包含趋势分析和高质量推荐的 Markdown 报告
- 🔄 **按任务切模型** - 共用一套 API Key / Base URL，按分析和总结切换不同模型
- 🧠 **Embedding 独立配置** - 向量检索可单独指定 provider / model，支持本地与 Docker HTTP 模式
- ⚡ **单请求 SSE 流式** - 本地服务支持 `/api/stream`，实时推送处理进度与事件
- 📦 **向量同步 Outbox** - SQLite 事务级写入 Outbox，断网与重试保障 Chroma 最终一致性
- ✅ **可选标记已读** - 默认不自动标记，支持渐进式与安全分批（100篇/批）标记已读

## 快速开始

### 1. 安装依赖

项目使用 [uv](https://github.com/astral-sh/uv) 进行依赖管理，要求 **Python 3.13+**。

建议为 WSL/Linux 与 Windows 分别配置独立的虚拟环境避免冲突：

```bash
# WSL / Linux (bash):
export UV_PROJECT_ENVIRONMENT=.venv-wsl
uv sync

# Windows (PowerShell):
$env:UV_PROJECT_ENVIRONMENT=".venv-win"
uv sync
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并填入你的 API 密钥：

```bash
cp .env.example .env
```

Feedly 凭据保存在 `feedly_config.json`。首次授权、检查和手动刷新统一使用：

```bash
uv run python feedly_token.py init
uv run python feedly_token.py check
uv run python feedly_token.py refresh
```

如需把凭据放在其他位置，设置 `FEEDLY_CONFIG_PATH`；如需代理，设置
`FEEDLY_PROXY_URL`。CLI 与运行时 Feedly 客户端共用同一套配置、代理和 token
刷新实现。

### 3. 运行

#### 交互式模式 (推荐)
项目提供了一个全功能的交互式终端界面，支持选择分类、过滤模式和分析配置：

```bash
uv run feedly_tui.py
```

#### 命令行模式
你也可以直接调用各组件独立命令：

```bash
# 从 Feedly 获取文章并分析
uv run python article_analyzer.py --refresh

# 过滤低分未读文章并渐进式标为已读
uv run python feedly_filter.py --threshold 2.5

# 分析已有的文章 JSON
uv run python article_analyzer.py --input output/unread_news.json

# 限制处理数量并标记已读（默认不标记，需显式开启）
uv run python article_analyzer.py --refresh --limit 50 --mark-read

# 从 SQLite 缓存重建活跃向量库
uv run python rebuild_vector_store.py
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
- `vector_store_state/` (Docker HTTP 模式) 或 `chroma_db/` (嵌入式模式)

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
- 这让 Chrome 扩展和本地 GUI/TUI 可以共享同一后端，而不是各自直连模型或宿主进程
- 普通调用使用 `POST /api/message`；耗时调用可使用 `POST /api/stream`，通过 SSE 在同一请求中持续接收进度和最终结果

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
- `vector_store_state/`（或本地 `chroma_db/`）下会记录 embedding 指纹；若你改了 embedding base URL 或 model，服务会警告需要重建向量库

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
├── feedly_tui.py           # 交互式 TUI 终端入口
├── article_analyzer.py     # 抓取、评分、分析 CLI 入口
├── rss_backend_service.py  # 本地 HTTP + SSE 服务入口
├── feedly_filter.py        # 未读文章过滤与渐进式标已读 CLI
├── feedly_token.py         # Feedly OAuth / PKCE 认证管理 CLI
├── rebuild_vector_store.py # 向量库重建与迁移 CLI
├── rss_analyzer/           # 核心领域模型与服务
│   ├── analysis_service.py # 统一文章分析与版本化缓存
│   ├── feedly_auth.py      # 统一 Feedly 认证逻辑
│   ├── feedly_client.py    # Feedly API 客户端
│   ├── vector_service.py   # 向量库生命周期与重建编排
│   ├── vector_store.py     # Chroma 读写适配（嵌入式 / HTTP）
│   ├── report_service.py   # 汇总报告与导出工作流
│   ├── feed_analysis_workflow.py # Feedly 刷新与分析工作流
│   ├── filter_workflows.py # 过滤与渐进式标已读工作流
│   ├── readflow_workflows.py # 分批分类与深度阅读工作流
│   ├── backend_service.py  # 共享调度 facade 与处理器注册
│   ├── http_service.py     # 本地 HTTP 与 SSE 服务封装
│   ├── *_handlers.py       # 传输层 Handler 注册表
│   └── tui/                # 终端界面拆分模块 (menus, review, reports...)
├── extension/              # Chrome Feedly 页面覆盖插件 (Manifest V3)
├── skills/feedly-readflow/ # 面向 Agent 的智能多代理阅读工作流
├── output/                 # 数据与摘要输出目录（按月归档）
├── docs/                   # 架构设计与覆盖率文档
└── tests/                  # 单元与集成测试套件 (185+ 测试)
```

## 测试

运行全量测试套件（185+ 测试）：

```bash
uv run pytest tests/
```

## License

MIT
