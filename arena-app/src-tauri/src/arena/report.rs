use crate::models::{
    ComparisonResult, DisagreementItem, RunMetrics, RunRecord, RunReport, RunResultItem,
    ScoreResult, SpreadItem, StabilityMetrics,
};
use std::collections::HashMap;

/// 构建单次运行报告
pub fn build_report(rows: &[ScoreResult], source_file: &str, target_spec: &str) -> RunReport {
    let article_count = rows.len();
    let avg_score = if article_count > 0 {
        rows.iter().map(|r| r.overall_score).sum::<f64>() / article_count as f64
    } else {
        0.0
    };

    // 分数分布
    let mut score_bands = serde_json::json!({});
    let bands = [("4.2+", 4.2), ("3.6-4.1", 3.6), ("3.0-3.5", 3.0), ("2.0-2.9", 2.0), ("<2.0", 0.0)];
    for (label, threshold) in &bands {
        let count = rows
            .iter()
            .filter(|r| {
                if *label == "4.2+" {
                    r.overall_score >= *threshold
                } else if *label == "3.6-4.1" {
                    r.overall_score >= *threshold && r.overall_score < 4.2
                } else if *label == "3.0-3.5" {
                    r.overall_score >= *threshold && r.overall_score < 3.6
                } else if *label == "2.0-2.9" {
                    r.overall_score >= *threshold && r.overall_score < 3.0
                } else {
                    r.overall_score < 2.0
                }
            })
            .count();
        if let Some(obj) = score_bands.as_object_mut() {
            obj.insert(label.to_string(), serde_json::json!(count));
        }
    }

    // 文章类型分布
    let mut article_types: HashMap<String, usize> = HashMap::new();
    for row in rows {
        *article_types.entry(row.article_type.clone()).or_insert(0) += 1;
    }

    // 来源分布
    let mut origins: HashMap<String, usize> = HashMap::new();
    for row in rows {
        let origin = if row.origin.is_empty() {
            "Unknown"
        } else {
            &row.origin
        };
        *origins.entry(origin.to_string()).or_insert(0) += 1;
    }
    let mut top_origins: Vec<(String, usize)> = origins.into_iter().collect();
    top_origins.sort_by(|a, b| b.1.cmp(&a.1));
    top_origins.truncate(10);

    // 负面信号
    let mut negative_signals: HashMap<String, usize> = HashMap::new();
    for row in rows {
        for signal in &row.negative_signals {
            *negative_signals.entry(signal.clone()).or_insert(0) += 1;
        }
    }
    let mut top_negative_signals: Vec<(String, usize)> = negative_signals.into_iter().collect();
    top_negative_signals.sort_by(|a, b| b.1.cmp(&a.1));
    top_negative_signals.truncate(10);

    // Red flags
    let mut red_flags: HashMap<String, usize> = HashMap::new();
    for row in rows {
        for flag in &row.red_flags {
            *red_flags.entry(flag.clone()).or_insert(0) += 1;
        }
    }
    let mut top_red_flags: Vec<(String, usize)> = red_flags.into_iter().collect();
    top_red_flags.sort_by(|a, b| b.1.cmp(&a.1));
    top_red_flags.truncate(10);

    // 排序后的文章
    let mut sorted_rows = rows.to_vec();
    sorted_rows.sort_by(|a, b| b.overall_score.partial_cmp(&a.overall_score).unwrap());

    let top_articles: Vec<ScoreResult> = sorted_rows.iter().take(10).cloned().collect();
    let bottom_articles: Vec<ScoreResult> = sorted_rows.iter().rev().take(10).rev().cloned().collect();

    // 解析 target spec 获取 label, model, base_url
    let parts: Vec<&str> = target_spec.split('|').collect();
    let (label, model, base_url) = if parts.len() >= 3 {
        (parts[0].to_string(), parts[1].to_string(), parts[2].to_string())
    } else {
        ("unknown".to_string(), "unknown".to_string(), "".to_string())
    };

    RunReport {
        generated_at: chrono::Local::now().to_rfc3339(),
        source_file: source_file.to_string(),
        label,
        model,
        base_url,
        article_count,
        average_score: round_to_2(avg_score),
        score_bands,
        article_types: serde_json::to_value(article_types).unwrap_or_default(),
        top_origins: serde_json::to_value(top_origins.into_iter().collect::<HashMap<_, _>>())
            .unwrap_or_default(),
        negative_signals: serde_json::to_value(top_negative_signals.into_iter().collect::<HashMap<_, _>>())
            .unwrap_or_default(),
        red_flags: serde_json::to_value(top_red_flags.into_iter().collect::<HashMap<_, _>>())
            .unwrap_or_default(),
        top_articles,
        bottom_articles,
        rows: rows.to_vec(),
        repeat_count: None,
        run_reports: None,
        stability: None,
    }
}

/// 聚合多次运行报告
pub fn aggregate_repeat_reports(reports: &[RunReport], source_file: &str, target_spec: &str) -> RunReport {
    if reports.len() == 1 {
        let mut report = reports[0].clone();
        report.repeat_count = Some(1);
        report.run_reports = Some(reports.to_vec());
        report.stability = Some(StabilityMetrics {
            average_spread: 0.0,
            largest_spreads: vec![],
        });
        return report;
    }

    // 按文章 ID 分组
    let mut by_article: HashMap<String, Vec<&ScoreResult>> = HashMap::new();
    for report in reports {
        for row in &report.rows {
            by_article.entry(row.id.clone()).or_default().push(row);
        }
    }

    // 聚合每篇文章的分数
    let mut aggregated_rows = Vec::new();
    let mut spreads = Vec::new();

    for (article_id, samples) in &by_article {
        let scores: Vec<f64> = samples.iter().map(|s| s.overall_score).collect();
        let mean_score = scores.iter().sum::<f64>() / scores.len() as f64;
        let min_score = scores.iter().cloned().fold(f64::INFINITY, f64::min);
        let max_score = scores.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let spread = max_score - min_score;

        // 计算标准差
        let variance = scores
            .iter()
            .map(|s| (s - mean_score).powi(2))
            .sum::<f64>()
            / scores.len() as f64;
        let stddev = variance.sqrt();

        // 选择最接近均值的样本作为 representative，避免元数据来自离群高分样本
        let representative = samples
            .iter()
            .min_by(|a, b| {
                (a.overall_score - mean_score)
                    .abs()
                    .partial_cmp(&(b.overall_score - mean_score).abs())
                    .unwrap()
            })
            .unwrap();

        let mut aggregated = (*representative).clone();
        aggregated.overall_score = round_to_2(mean_score);
        aggregated.score_min = Some(round_to_2(min_score));
        aggregated.score_max = Some(round_to_2(max_score));
        aggregated.score_spread = Some(round_to_2(spread));
        aggregated.score_stddev = Some(round_to_3(stddev));
        aggregated.score_samples = Some(scores.clone());

        aggregated_rows.push(aggregated);

        spreads.push(SpreadItem {
            id: article_id.clone(),
            title: representative.title.clone(),
            origin: representative.origin.clone(),
            score_samples: scores,
            spread: round_to_2(spread),
            stddev: round_to_3(stddev),
        });
    }

    // 按 spread 排序
    spreads.sort_by(|a, b| b.spread.partial_cmp(&a.spread).unwrap());

    let mut aggregated = build_report(&aggregated_rows, source_file, target_spec);
    aggregated.repeat_count = Some(reports.len());
    aggregated.run_reports = Some(reports.to_vec());

    let avg_spread = if spreads.is_empty() {
        0.0
    } else {
        spreads.iter().map(|s| s.spread).sum::<f64>() / spreads.len() as f64
    };

    aggregated.stability = Some(StabilityMetrics {
        average_spread: round_to_3(avg_spread),
        largest_spreads: spreads.into_iter().take(15).collect(),
    });

    aggregated
}

/// 构建多模型对比
pub fn build_comparison(model_reports: &[RunReport]) -> ComparisonResult {
    let model_names: Vec<String> = model_reports.iter().map(|r| r.label.clone()).collect();

    // 构建每篇文章在各模型中的分数映射
    let mut rows_by_model: HashMap<String, HashMap<String, &ScoreResult>> = HashMap::new();
    for report in model_reports {
        let mut row_map = HashMap::new();
        for row in &report.rows {
            row_map.insert(row.id.clone(), row);
        }
        rows_by_model.insert(report.label.clone(), row_map);
    }

    // 找到所有模型都评分的文章
    let mut common_ids: Option<std::collections::HashSet<String>> = None;
    for (_model, rows) in &rows_by_model {
        let ids: std::collections::HashSet<String> = rows.keys().cloned().collect();
        common_ids = match common_ids {
            Some(existing) => Some(existing.intersection(&ids).cloned().collect()),
            None => Some(ids),
        };
    }

    let common_ids = common_ids.unwrap_or_default();

    // 构建对比行
    let mut comparison_rows = Vec::new();
    for article_id in &common_ids {
        let mut score_by_model: HashMap<String, f64> = HashMap::new();
        for (model, rows) in &rows_by_model {
            if let Some(row) = rows.get(article_id) {
                score_by_model.insert(model.clone(), row.overall_score);
            }
        }

        let scores: Vec<f64> = score_by_model.values().cloned().collect();
        let spread = if scores.len() >= 2 {
            let max = scores.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
            let min = scores.iter().cloned().fold(f64::INFINITY, f64::min);
            max - min
        } else {
            0.0
        };

        // 获取第一篇文章的信息（安全地处理缺失数据）
        let first_row = model_names
            .first()
            .and_then(|m| rows_by_model.get(m))
            .and_then(|rows| rows.get(article_id));

        let (title, origin) = match first_row {
            Some(row) => (row.title.clone(), row.origin.clone()),
            None => {
                // 如果找不到文章信息，跳过此项
                continue;
            }
        };

        comparison_rows.push(DisagreementItem {
            id: article_id.clone(),
            title,
            origin,
            score_by_model: serde_json::to_value(&score_by_model).unwrap_or_default(),
            spread: round_to_2(spread),
        });
    }

    // 按 spread 排序
    comparison_rows.sort_by(|a, b| b.spread.partial_cmp(&a.spread).unwrap());

    // 计算每个模型的平均分
    let mut avg_by_model: HashMap<String, f64> = HashMap::new();
    for report in model_reports {
        let avg = if report.rows.is_empty() {
            0.0
        } else {
            report.rows.iter().map(|r| r.overall_score).sum::<f64>() / report.rows.len() as f64
        };
        avg_by_model.insert(report.label.clone(), round_to_2(avg));
    }

    ComparisonResult {
        models: model_names,
        article_count: common_ids.len(),
        average_score_by_model: serde_json::to_value(avg_by_model).unwrap_or_default(),
        largest_disagreements: comparison_rows.into_iter().take(15).collect(),
    }
}

/// 生成运行记录 (最终落盘格式)
pub fn build_run_record(
    report: &RunReport,
    comparison: Option<&ComparisonResult>,
    dataset: &str,
    target_spec: &str,
    run_id: &str,
) -> RunRecord {
    let metrics = derive_metrics(report, comparison);

    let results: Vec<RunResultItem> = report
        .rows
        .iter()
        .map(|row| RunResultItem {
            item_id: row.id.clone(),
            title: row.title.clone(),
            score: row.overall_score,
            spread: row.score_spread.unwrap_or(0.0),
            reason: row.reason.clone(),
        })
        .collect();

    RunRecord {
        id: run_id.to_string(),
        dataset: dataset.to_string(),
        target: target_spec.to_string(),
        timestamp: report.generated_at.clone(),
        metrics,
        results,
    }
}

/// 派生运行指标
fn derive_metrics(report: &RunReport, comparison: Option<&ComparisonResult>) -> RunMetrics {
    let rows = &report.rows;
    let article_count = rows.len().max(1) as f64;

    // 高分文章比例
    let high_score_count = rows
        .iter()
        .filter(|r| r.overall_score >= 4.2)
        .count() as f64;

    // 负面信号存在比例
    let negative_signal_count = rows
        .iter()
        .filter(|r| !r.negative_signals.is_empty())
        .count() as f64;

    // 平均 spread 和最大 spread
    let (avg_spread, max_spread) = if let Some(ref stability) = report.stability {
        let avg = stability.average_spread;
        let max = stability
            .largest_spreads
            .iter()
            .map(|s| s.spread)
            .fold(0.0, f64::max);
        (avg, max)
    } else {
        (0.0, 0.0)
    };

    // cheap_vs_sota_gap
    let cheap_vs_sota_gap = comparison
        .and_then(|c| c.average_score_by_model.as_object())
        .map(|models| {
            let current = models
                .get(&report.label)
                .and_then(|v| v.as_f64())
                .unwrap_or(0.0);
            let mut max_gap = 0.0;
            for (other_label, score) in models {
                if other_label == &report.label {
                    continue;
                }
                if let Some(other) = score.as_f64() {
                    let gap = (current - other).abs();
                    if gap > max_gap {
                        max_gap = gap;
                    }
                }
            }
            max_gap
        })
        .unwrap_or(0.0);

    RunMetrics {
        average_spread: round_to_3(avg_spread),
        max_spread: round_to_2(max_spread),
        high_score_rate: round_to_2(high_score_count / article_count),
        negative_signal_presence_rate: round_to_2(negative_signal_count / article_count),
        cheap_vs_sota_gap: round_to_2(cheap_vs_sota_gap),
    }
}

fn round_to_2(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

fn round_to_3(value: f64) -> f64 {
    (value * 1000.0).round() / 1000.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_score_result(id: &str, score: f64) -> ScoreResult {
        ScoreResult {
            id: id.to_string(),
            title: format!("Article {}", id),
            origin: "Test".to_string(),
            link: "".to_string(),
            published: None,
            relevance_score: 4.0,
            informativeness_accuracy_score: 4.0,
            depth_opinion_score: 3.5,
            readability_score: 4.0,
            non_redundancy_score: 3.5,
            weighted_score: score,
            overall_score: score,
            verdict: "值得阅读".to_string(),
            reason: "Test reason".to_string(),
            why_not_higher: "".to_string(),
            article_type: "news".to_string(),
            red_flags: vec![],
            negative_signals: vec![],
            model: "gpt-4o".to_string(),
            label: "test".to_string(),
            base_url: "https://api.openai.com".to_string(),
            score_min: None,
            score_max: None,
            score_spread: None,
            score_stddev: None,
            score_samples: None,
        }
    }

    #[test]
    fn test_build_report() {
        let rows = vec![
            create_test_score_result("1", 4.5),
            create_test_score_result("2", 3.5),
            create_test_score_result("3", 2.5),
        ];

        let report = build_report(&rows, "test.json", "test|gpt-4o|https://api.openai.com|key");

        assert_eq!(report.article_count, 3);
        assert!(report.average_score > 0.0);
        assert!(!report.top_articles.is_empty());
    }

    #[test]
    fn test_aggregate_repeat_reports() {
        let rows1 = vec![create_test_score_result("1", 4.0), create_test_score_result("2", 3.0)];
        let rows2 = vec![create_test_score_result("1", 4.2), create_test_score_result("2", 3.1)];

        let report1 = build_report(&rows1, "test.json", "test|gpt-4o|https://api.openai.com|key");
        let report2 = build_report(&rows2, "test.json", "test|gpt-4o|https://api.openai.com|key");

        let aggregated = aggregate_repeat_reports(&[report1, report2], "test.json", "test|gpt-4o|https://api.openai.com|key");

        assert_eq!(aggregated.repeat_count, Some(2));
        assert!(aggregated.stability.is_some());
    }
}
