# Scoring Arena

独立于主业务流程的评分评测子项目。

目标：

- 比较不同模型 / provider / prompt 在 RSS 评分任务上的表现
- 关注稳定性、严格性、指令遵循性，而不只看单次分数
- 为主项目选择 cheap / sota 模型提供依据

## 目录

- `SPEC.md`
  - 评测目标、指标和设计边界
- `configs/`
  - target、dataset、run profile 示例配置
- `datasets/`
  - 固定 benchmark 样本集
- `scripts/`
  - 运行评测、对比 run、构建数据集的脚本入口
- `runs/`
  - 原始 run 结果
- `reports/`
  - 汇总后的报告或 leaderboard

## 当前状态

当前已经完成：

1. arena 目录骨架
2. 首批 benchmark 数据集
   - `datasets/rss_cnbeta_v1.json`
   - `datasets/mixed_feed_v1.json`

下一步建议：

1. 把现有 `scripts/backtest_scoring.py` 迁移或包装到 `arena/scoring/scripts/run_backtest.py`
2. 让 run 脚本直接消费上述数据集 schema
3. 把稳定性和指令遵循性指标正式接入 run 输出
