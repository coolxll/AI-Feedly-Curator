# Scoring Arena Spec

## Summary

这是一个独立于 RSS 主流程的模型评测子项目，用于比较不同模型在“文章评分与筛选”任务上的表现。

核心不是测谁更会写，而是测谁更适合当稳定、严格、可解释的评分器。

## Primary Metrics

- `average_spread`
  - 同一文章重复评分后的平均漂移幅度
- `max_spread`
  - 最大单篇漂移幅度
- `high_score_rate`
  - 高分膨胀程度
- `why_not_higher_presence_rate`
  - 是否稳定输出反向解释
- `negative_signal_presence_rate`
  - 是否稳定输出负面信号
- `cheap_vs_sota_gap`
  - cheap 和 sota 的平均分差异

## Principles

- 主项目负责生产评分，arena 负责评测与选型
- arena 可以调用主项目评分逻辑，但主项目不依赖 arena
- benchmark 数据集应固定，不直接依赖运行时产物
- 模型评测优先看稳定性与严格性，而不是单次高分

## Initial Roadmap

1. 建立固定 benchmark 数据集
2. 迁移回测脚本到 arena 目录
3. 统一 run 输出结构
4. 增加 run 对比和 leaderboard
