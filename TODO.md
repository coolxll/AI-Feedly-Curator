# Future Roadmap

## 🚀 架构演进 (Architecture Evolution)

- [ ] **集成本地向量数据库 (Local Vector DB Integration)**
    - **目标**: 引入 ChromaDB 作为嵌入式向量库。
    - **用途**:
        1. **语义去重**: 替代现有的 URL/标题匹配，识别内容高度相似的"洗稿"文章。
        2. **RAG 增强**: 生成 Summary 时检索历史相似文章，进行趋势对比（如"对比上个月的 Dev tools 进展"）。
        3. **个性化知识库**: 长期存储高质量文章 Embedding，支持语义搜索（"帮我找找以前关于 Prompt Engineering 的文章"）。
    - **技术栈**:
        - **向量库**: ChromaDB (Embedded/Persistent 模式)
        - **Embedding**: 阿里云 DashScope `text-embedding-v3` (1024 维)
        - **架构**: SQLite (主数据源) + ChromaDB (语义索引)
    - **实施步骤**:
        - [ ] 安装依赖: `pip install chromadb dashscope`
        - [ ] 在 `rss_analyzer` 下创建 `vector_store.py` 模块
        - [ ] 实现 DashScope Embedding Function
        - [ ] 在 `save_cached_score` 时同步写入向量库
        - [ ] 创建历史文章索引重建脚本
        - [ ] 在 Native Host 添加 `semantic_search` 消息处理
        - [ ] Chrome Extension UI 添加语义搜索框
        - [ ] 测试中英文混合搜索效果

- [ ] **智能抓取策略优化**
    - [ ] 基于向量相似度判断是否需要全量抓取（如果是重复内容则跳过）。

## 💡 功能增强

- [ ] **多模态分析**: 支持从文章中的图片提取信息（针对 info-graphic 类文章）。
- [ ] **自动标签系统**: 基于聚类算法自动生成 Topic Tags，而非依赖预设分类。
