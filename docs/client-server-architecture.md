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
- Feedly token refresh 与配置解析

### 2. Service

新增本地后端服务，负责暴露统一接口：

- 当前入口：`rss_backend_service.py`
- HTTP 封装：`rss_analyzer/http_service.py`
- 共享消息分发：`rss_analyzer/backend_service.py`

这层是唯一允许直接访问模型配置、数据库和向量库的地方。

### 3. Clients

客户端都应该变薄：

- Chrome 扩展：负责 Feedly 页面注入、交互、显示
- TUI：负责命令行交互
- Streamlit GUI：负责本地可视化界面
- 后续桌面 GUI：也应走同一服务接口

客户端不应该各自保存 AI 逻辑，不应该各自直连模型，不应该各自维护缓存副本。

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

## 后续建议

1. 把本地 GUI/Streamlit 中直接访问底层模块的地方，逐步收敛到同一套 service API。
2. 若后端接口继续增长，把消息分发从 `type`-switch 进一步整理成显式路由表。
3. Agent skills 继续作为薄客户端维护；若某个 skill 里的脚本变成通用能力，应迁回 `rss_analyzer/` 或项目 CLI。
4. 当确认没有人再使用 native host 后，可将 `native_host/` 降级为 legacy 或直接删除。

## 可恢复长任务

本地服务支持把耗时操作写入 SQLite 后台队列。客户端可以在原消息中加入
`"async": true`，适用于：

- `run_analysis`
- `generate_daily_digest`
- `process_stream`
- `rebuild_vector_store`
- `retry_vector_indexing`

提交后返回 `job.job_id`。使用 `get_job` 查询状态，使用 `retry_job` 重新提交失败任务。
相同操作和参数默认会生成相同的去重键；需要强制新建任务时传 `"force": true`。
服务重启后，执行中的任务会恢复为待执行状态。

评分结果以 SQLite 为主数据。向量写入通过 `vector_index_outbox` 异步完成，写入失败会保留
错误和重试次数。使用 `get_vector_index_queue` 查看积压，使用
`retry_vector_indexing` 重新处理失败项。
