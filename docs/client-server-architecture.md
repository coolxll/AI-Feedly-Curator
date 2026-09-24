# Client-Server Architecture

## 结论

这不是两个独立项目。

更准确的定义是：**一个业务项目，多个可独立运行的应用组件**。仓库应该按 monorepo 心智来维护，而不是把 Chrome 扩展和本地 GUI 当成两套彼此复制逻辑的系统。

## 推荐边界

### 1. Core

共享业务能力，继续放在 `rss_analyzer/`：

- 文章抓取与正文提取
- 评分与摘要
- SQLite 缓存
- Chroma 向量检索
- Feedly 相关数据处理
- Feedly token refresh、PKCE 与配置解析（统一位于 `rss_analyzer/feedly_auth.py`）

### 2. Service

新增本地后端服务，负责暴露统一接口：

- 当前入口：`rss_backend_service.py`
- HTTP 封装：`rss_analyzer/http_service.py`
- 稳定 facade 与共享消息分发：`rss_analyzer/backend_service.py`
- Feedly 抓取、评分与汇总工作流：`rss_analyzer/feed_analysis_workflow.py`
- Feedly 领域兼容 facade：`rss_analyzer/feedly_workflows.py`
- Feedly 未读过滤与 mark-as-read 工作流：`rss_analyzer/filter_workflows.py`
- Stream overview、batch triage 与 P2 深读工作流：`rss_analyzer/readflow_workflows.py`
- Feedly 消息与 SSE adapters：`rss_analyzer/feedly_handlers.py`
- 文章级评分与摘要 handlers：`rss_analyzer/analysis_handlers.py`
- 报告、日报与导出：`rss_analyzer/report_service.py`、`rss_analyzer/report_handlers.py`
- Vector/search handlers：`rss_analyzer/vector_handlers.py`
- Vector 生命周期与重建：`rss_analyzer/vector_service.py`

这层是唯一允许直接访问模型配置、数据库和向量库的地方。

### 3. Clients

客户端都应该变薄：

- Chrome 扩展：负责 Feedly 页面注入、交互、显示
- TUI：负责命令行交互
- Streamlit GUI：负责本地可视化界面
- 后续桌面 GUI：也应走同一服务接口

客户端不应该各自保存 AI 逻辑，不应该各自直连模型，不应该各自维护缓存副本。

TUI 的共享配置解析、路径和数据筛选 helper 位于 `rss_analyzer/tui/support.py`；
Feedly stream 选择交互位于 `rss_analyzer/tui/stream_selection.py`；
stream overview 与 batch reading 交互位于 `rss_analyzer/tui/review.py`；
根目录的 `feedly_tui.py` 保留可执行入口与交互编排。

### 4. Agent Skills

Hermes/Codex/Claude skills 也按客户端处理，而不是新的业务边界：

- skills 可以负责编排、提示词、日报格式、投递和人工偏好
- skills 不应复制 Feedly API、token refresh、缓存、评分等核心逻辑
- 需要读写 Feedly 状态时，优先调用本仓库的 CLI、service 或 `rss_analyzer/` 能力
- Agent 专用临时文件可以继续放在 `/tmp/`，但数据来源和状态变更应由 core 提供

## 为什么不是拆成两个 repo

- 业务对象完全相同，都是“同一批 RSS 文章的分析与消费”
- 底层依赖完全相同，都是同一个 SQLite、同一个向量库、同一套 LLM 配置
- 拆 repo 只会把 transport 边界误当成系统边界，导致重复实现和发布复杂度上升

真正需要拆开的不是仓库，而是**运行时职责**：

- 服务端负责能力
- 客户端负责交互

## 当前迁移结果

已经完成的收敛：

- 原本塞在 `native_host/feedly_native_host.py` 的业务处理已抽到共享后端
- 新增本地 HTTP 服务，接口入口为：
  - `GET /health`
  - `POST /api/message`
- Chrome 扩展已改为通过本地 HTTP 服务调用后端
- 扩展内原先那套“直接配置 OpenAI API Key/Model/Prompt”的逻辑已移除
- 普通消息和 SSE 特殊操作已使用显式 handler registry，新增操作不再扩展条件分支链
- `backend_service.py` 已收敛为稳定 facade/dispatcher；Feedly、分析、报告和向量领域逻辑分别位于各自的 service/workflow 与 handler 模块

## 后续建议

1. 把本地 GUI/Streamlit 中直接访问底层模块的地方，逐步收敛到同一套 service API。
2. Agent skills 继续作为薄客户端维护；若某个 skill 里的脚本变成通用能力，应迁回 `rss_analyzer/` 或项目 CLI。
3. 当确认没有人再使用 native host 后，可将 `native_host/` 降级为 legacy 或直接删除。

## SSE 流式请求

耗时操作通过 `POST /api/stream` 在当前 HTTP 请求中执行，响应类型为
`text/event-stream`。服务会依次发送 `accepted`、`phase`、`progress`、文章级事件，
最后发送 `complete` 或 `error`。Chrome 扩展应使用 `fetch()` 读取响应流；由于请求为
POST，不使用浏览器的 `EventSource`。

服务会在模型调用等静默阶段定期发送 SSE 注释心跳，避免长连接被中间层当作空闲连接
关闭。心跳不代表后台任务：工作仍属于当前请求，最终结果也只通过同一个响应返回。

当前提供细粒度进度的操作包括 `run_analysis`、`generate_daily_digest`、
`process_stream` 和 `rebuild_vector_store`。其他消息也可通过流式端点调用，但只会收到
开始和最终结果事件。连接断开会通知处理流程在下一次进度回调时退出；已经进入的单次
模型/API 调用无法由 Python 线程强制中断，只能等待该调用返回或自身超时。

评分结果以 SQLite 为主数据。向量写入通过 `vector_index_outbox` 异步完成，写入失败会保留
错误和重试次数。使用 `get_vector_index_queue` 查看积压，使用
`retry_vector_indexing` 重新处理失败项。
