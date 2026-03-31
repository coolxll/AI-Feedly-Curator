# Datasets

这里放固定 benchmark 样本集。

## 结构约定

每个数据集文件使用同一层 schema：

- `dataset`
- `version`
- `created_at`
- `description`
- `source_files`
- `items`

每个 `item` 至少包含：

- `id`
- `title`
- `origin`
- `link`
- `published`
- `summary_excerpt`
- `category`
- `expected_band`
- `source_file`

## 首批数据集

- `rss_cnbeta_v1.json`
  - 面向 cnBeta / 快讯扩写 / 标题党式科技资讯
  - 重点考察高分通胀、标题诱导、模型稳定性
- `mixed_feed_v1.json`
  - 混合 V2EX、36氪、钛媒体、华尔街见闻、NYT、Solidot、集思录等来源
  - 同时覆盖高价值技术帖、边界新闻、明显噪音和低相关内容

## 原则

- 数据集应版本化
- 初始样本可以来自 `output/` 的导出文件，但固化后不再随运行产物漂移
- 每个数据集都要保留 `source_file` 便于回溯来源
- `expected_band` 先采用粗粒度 `high / mid / low`，后续再逐步细化
