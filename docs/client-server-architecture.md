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
3. 当确认没有人再使用 native host 后，可将 `native_host/` 降级为 legacy 或直接删除。
