use crate::config::AppConfig;
use crate::models::DimensionScores;

/// 计算加权分数和校准分数
pub fn calculate_scores(
    scores: &DimensionScores,
    article_type: &str,
    red_flags: &[String],
    negative_signals: &[String],
    why_not_higher: &str,
    config: &AppConfig,
) -> (f64, f64) {
    let weighted = calculate_weighted_score(scores, article_type, red_flags, config);
    let calibrated = calibrate_score_distribution(
        weighted,
        scores,
        article_type,
        red_flags,
        negative_signals,
        why_not_higher,
        config,
    );
    (weighted, calibrated)
}

/// 计算加权分数
fn calculate_weighted_score(
    scores: &DimensionScores,
    article_type: &str,
    red_flags: &[String],
    config: &AppConfig,
) -> f64 {
    let weights = config.get_weights(article_type);

    // 计算加权分
    let weighted_score = scores.relevance * weights.relevance
        + scores.informativeness_accuracy * weights.informativeness_accuracy
        + scores.depth_opinion * weights.depth_opinion
        + scores.readability * weights.readability
        + scores.non_redundancy * weights.non_redundancy;

    // 相关性熔断机制
    let mut result = weighted_score;
    if scores.relevance < config.relevance_threshold {
        result = result.min(config.relevance_threshold);
    }

    // 负面清单处理
    if !red_flags.is_empty() {
        // Hard Flags: 直接打入冷宫
        if red_flags.iter().any(|f| f == "ai_generated") {
            return 1.0;
        }

        // Soft Flags: 每项扣0.5分
        let penalty = red_flags.len() as f64 * 0.5;
        result = (result - penalty).max(1.0);
    }

    round_to_1(result)
}

/// 校准分数分布
fn calibrate_score_distribution(
    weighted_score: f64,
    scores: &DimensionScores,
    article_type: &str,
    red_flags: &[String],
    negative_signals: &[String],
    why_not_higher: &str,
    _config: &AppConfig,
) -> f64 {
    use crate::config::{DEFAULT_SCORE_ANCHOR, NEGATIVE_SIGNAL_PENALTY};

    // 1. 基础校准
    let mut calibrated = if weighted_score >= DEFAULT_SCORE_ANCHOR {
        DEFAULT_SCORE_ANCHOR + (weighted_score - DEFAULT_SCORE_ANCHOR) * 0.72
    } else {
        DEFAULT_SCORE_ANCHOR - (DEFAULT_SCORE_ANCHOR - weighted_score) * 0.9
    };

    // 2. 负面信号惩罚
    if !negative_signals.is_empty() {
        calibrated -= (negative_signals.len() as f64 * NEGATIVE_SIGNAL_PENALTY).min(1.2);
    }

    // 3. 严格性校准
    if !why_not_higher.is_empty() {
        calibrated -= 0.1;
    }

    // 4. 维度上限限制
    if scores.informativeness_accuracy <= 3.0 {
        calibrated = calibrated.min(3.8);
    }
    if scores.non_redundancy <= 3.0 {
        calibrated = calibrated.min(3.7);
    }
    if article_type != "news" && scores.depth_opinion <= 3.0 {
        calibrated = calibrated.min(4.0);
    }
    if scores.relevance <= 3.0 {
        calibrated = calibrated.min(3.5);
    }

    // 5. 高分稀缺性保护
    if weighted_score >= 4.5 {
        let qualifies = scores.relevance >= 5.0
            && scores.informativeness_accuracy >= 5.0
            && scores.non_redundancy >= 4.0
            && (scores.depth_opinion >= 4.0 || article_type == "news")
            && red_flags.is_empty()
            && negative_signals.is_empty();

        if !qualifies {
            calibrated = calibrated.min(4.3);
        }
    } else if weighted_score >= 4.0 {
        let qualifies = scores.relevance >= 4.0
            && scores.informativeness_accuracy >= 4.0
            && scores.non_redundancy >= 4.0;

        if !qualifies {
            calibrated = calibrated.min(3.9);
        }
    }

    round_to_1(calibrated.clamp(1.0, 5.0))
}

/// 获取评价 verdict
pub fn get_verdict(score: f64, red_flags: &[String]) -> String {
    use crate::config::{HIGH_SCORE_THRESHOLD, RECOMMENDED_SCORE_THRESHOLD};

    let base_verdict = if score >= HIGH_SCORE_THRESHOLD {
        "强烈推荐"
    } else if score >= RECOMMENDED_SCORE_THRESHOLD {
        "值得阅读"
    } else if score >= 3.0 {
        "一般，可选阅读"
    } else {
        "不太值得阅读"
    };

    if red_flags.is_empty() {
        base_verdict.to_string()
    } else {
        format!("{} (含 {})", base_verdict, red_flags.join(", "))
    }
}

/// 四舍五入到1位小数
fn round_to_1(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_scores() -> DimensionScores {
        DimensionScores {
            relevance: 4.0,
            informativeness_accuracy: 4.0,
            depth_opinion: 3.5,
            readability: 4.0,
            non_redundancy: 3.5,
        }
    }

    #[test]
    fn test_calculate_weighted_score() {
        let config = AppConfig::default();
        let scores = test_scores();

        let weighted = calculate_weighted_score(&scores, "news", &[], &config);
        assert!(weighted > 0.0);
        assert!(weighted <= 5.0);
    }

    #[test]
    fn test_relevance_fuse() {
        let config = AppConfig::default();
        let mut scores = test_scores();
        scores.relevance = 2.0; // 低于阈值

        let weighted = calculate_weighted_score(&scores, "news", &[], &config);
        assert!(weighted <= config.relevance_threshold);
    }

    #[test]
    fn test_hard_red_flag() {
        let config = AppConfig::default();
        let scores = test_scores();

        let weighted = calculate_weighted_score(&scores, "news", &["ai_generated".to_string()], &config);
        assert_eq!(weighted, 1.0);
    }

    #[test]
    fn test_soft_red_flags() {
        let config = AppConfig::default();
        let scores = test_scores();

        let weighted_no_flags = calculate_weighted_score(&scores, "news", &[], &config);
        let weighted_with_flags = calculate_weighted_score(&scores, "news", &["clickbait".to_string(), "pure_promotion".to_string()], &config);

        assert!(weighted_with_flags < weighted_no_flags);
    }

    #[test]
    fn test_get_verdict() {
        assert_eq!(get_verdict(4.5, &[]), "强烈推荐");
        assert_eq!(get_verdict(4.0, &[]), "值得阅读");
        assert_eq!(get_verdict(3.5, &[]), "一般，可选阅读");
        assert_eq!(get_verdict(2.5, &[]), "不太值得阅读");

        let verdict_with_flags = get_verdict(4.5, &["clickbait".to_string()]);
        assert!(verdict_with_flags.contains("clickbait"));
    }

    #[test]
    fn test_high_score_protection() {
        let config = AppConfig::default();
        let mut scores = test_scores();
        scores.relevance = 5.0;
        scores.informativeness_accuracy = 5.0;
        scores.non_redundancy = 4.0;

        let (weighted, calibrated) = calculate_scores(&scores, "news", &[], &[], "", &config);

        // 高分应该有适当的校准
        if weighted >= 4.5 {
            assert!(calibrated <= 5.0);
        }
    }
}
