# TODO List

## Feedly Integration

### 目标
在 SKILLS 中添加直接从 Feedly 获取未读新闻的能力，并且与 Feedly 进行同步，避免单个去获取 RSS 的麻烦。

### 功能需求

#### 认证与连接
- [x] 实现 Feedly API OAuth 认证流程 ✅ (使用 Access Token)
- [x] 支持使用访问令牌（Access Token）进行认证 ✅ (已实现)
- [x] 安全存储和管理认证凭据 ✅ (存储在 `.claude/skills/rss_reader/feedly_config.json`)

#### 获取文章
- [x] 从用户的 Feedly 流（streams）中获取未读文章 ✅ (已实现 `feedly_fetch_unread`)
- [x] 支持按分类（categories）筛选文章 ✅ (通过 `stream_id` 参数)
- [ ] 支持按标签（tags）筛选文章
- [x] 实现分页和批量获取以提高性能 ✅ (支持 `limit` 参数)

#### 同步功能
- [x] 标记文章为已读/未读 ✅ (已实现 `feedly_mark_read`)
- [x] 双向同步阅读状态（本地工具 ↔ Feedly） ✅ (处理后自动标记)
- [ ] 支持保存文章到 Feedly
- [ ] 支持为文章添加标签

#### 工具集成
- [x] 在 `rss_analyzer` 包中添加 Feedly 相关功能 ✅ (`feedly_client.py`)
- [ ] 更新 SKILL.md 文档说明新功能
- [x] 添加使用示例和最佳实践 ✅ (README.md 中有说明)

### 预期优势

✅ **集中管理**：通过 Feedly 统一管理所有 RSS 订阅源  
✅ **自动同步**：阅读状态自动在工具和 Feedly 之间同步  
✅ **简化流程**：无需手动管理和维护单个 RSS 源 URL  
✅ **增强功能**：利用 Feedly 的源发现、分类和推荐功能  
✅ **跨平台**：在多个设备和应用间保持一致的阅读体验

### 技术参考

#### 技术实现方案对比

根据调研和最佳实践，主要有两种推荐的实施路径：

**方案 A：使用官方客户端（推荐快速上手/个人工具）**
直接使用 `feedly/python-api-client`。
- **优点**：封装了 RefreshToken、Streams 处理、标记已读等复杂逻辑。
- **安装**：强烈建议直接安装 GitHub 最新版（PyPI 版本可能过旧）。
  ```bash
  pip install git+https://github.com/feedly/python-api-client.git
  ```
- **代码示例**:
  ```python
  from feedly.api_client.session import FeedlySession
  
  # 1. 使用 Developer Token (登录 Feedly 网页版 -> Console -> prompt('feedlyToken') 获取)
  token = "YOUR_ACCESS_TOKEN"
  user_id = "user/UUID" 
  
  # 2. 初始化 Session
  session = FeedlySession(auth_token=token, user_id=user_id)
  
  # 3. 获取文章
  stream_id = 'user/USER_ID/category/global.must'
  for article in session.user.get_stream(stream_id).contents:
      print(article['title'])
  ```

**方案 B：自建轻量级封装（推荐生产环境/长期项目）**
直接使用 `requests` 库调用 Feedly API。
- **优点**：
  - 完全可控，零第三方依赖（除了 requests）。
  - 避免因官方库不更新导致在 Python 3.11+ 上出现兼容性问题（如 collections DeprecationWarning）。
  - 适合长期稳定运行的服务。
- **实现示例**:
  ```python
  import requests
  
  class SimpleFeedly:
      def __init__(self, token):
          self.base_url = "https://cloud.feedly.com/v3"
          self.headers = {"Authorization": f"OAuth {token}"}
      
      def get_stream_contents(self, stream_id, count=20):
          params = {"streamId": stream_id, "count": count}
          resp = requests.get(f"{self.base_url}/streams/contents", headers=self.headers, params=params)
          resp.raise_for_status()
          return resp.json()
  ```

#### 总结建议
- **初学者/个人脚本**：选用 **方案 A**。它是目前唯一活跃的封装库，能快速满足需求。
- **长期项目/生产环境**：选用 **方案 B**。API 调用逻辑简单，自己维护那几十行代码比依赖外部库更稳健。

#### API 文档
- Feedly API 官方文档: https://developer.feedly.com/
- 认证方式: OAuth 2.0 或 Developer Access Token

#### 其他依赖
- `requests` - HTTP 请求
- `feedparser` - RSS 解析 (本项目已有)

#### API 文档
- Feedly API 官方文档: https://developer.feedly.com/
- 认证方式: OAuth 2.0 或 Developer Access Token

#### 其他依赖
- `requests` - HTTP 请求（如果不使用现成库）
- `feedparser` - RSS 解析（已有）

### 优先级
🔴 高优先级 - 可以显著提升用户体验和工作效率

### 完成情况
✅ **核心功能已完成** (9/13 项)
- ✅ Feedly 认证和连接
- ✅ 获取未读文章
- ✅ 按分类筛选
- ✅ 批量获取
- ✅ 标记已读
- ✅ 代码模块化
- ✅ 单元测试

🚧 **待完成功能** (4/13 项)
- ⏳ 按标签筛选文章
- ⏳ 保存文章到 Feedly
- ⏳ 为文章添加标签
- ⏳ SKILL.md 文档更新
