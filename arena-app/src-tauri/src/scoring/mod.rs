pub mod calculator;
pub mod client;
pub mod parser;
pub mod prompt;

use crate::models::{ProgressEvent, ScoreResult, TargetConfig};
use crate::config::AppConfig;

/// 评分错误类型
#[derive(Debug, thiserror::Error)]
pub enum ScoringError {
    #[error("API request failed: {0}")]
    ApiError(String),
    #[error("JSON parse error: {0}")]
    ParseError(String),
    #[error("Invalid response format")]
    InvalidResponse,
    #[error("Network error: {0}")]
    NetworkError(String),
    #[error("Cancelled")]
    Cancelled,
}

/// 评分器
pub struct Scorer {
    config: AppConfig,
    client: client::OpenAIClient,
}

impl Scorer {
    /// 创建新的评分器（使用全局配置）
    pub fn new() -> Self {
        Self::with_config(AppConfig::default())
    }

    /// 使用指定配置创建评分器
    pub fn with_config(config: AppConfig) -> Self {
        Self {
            config,
            client: client::OpenAIClient::new(),
        }
    }

    /// 单篇文章评分
    #[allow(dead_code)]
    pub async fn score_article(
        &self,
        title: &str,
        summary: &str,
        content: &str,
        target: &TargetConfig,
    ) -> Result<ScoreResult, ScoringError> {
        let prompt = prompt::build_scoring_prompt(
            title,
            summary,
            content,
            &self.config.scoring_persona,
        );

        let response = self.client.chat_completion(target, &prompt, &|| false).await?;
        let data = parser::extract_json_from_response(&response)
            .ok_or_else(|| ScoringError::ParseError("Failed to extract JSON from response".to_string()))?;

        let scoring_data: crate::models::ScoringResponseData = serde_json::from_str(&data)
            .map_err(|e| ScoringError::ParseError(format!("Failed to parse scoring data: {}", e)))?;

        let article = crate::models::Article {
            id: String::new(),
            title: title.to_string(),
            origin: String::new(),
            link: String::new(),
            published: None,
            summary: summary.to_string(),
            content: content.to_string(),
        };

        let mut result = ScoreResult::from_scoring_data(&article, &scoring_data, target);

        // 计算加权分数和校准分数
        let (weighted_score, overall_score) = calculator::calculate_scores(
            &scoring_data.scores,
            &scoring_data.article_type,
            &scoring_data.red_flags,
            &scoring_data.negative_signals,
            &scoring_data.why_not_higher,
            &self.config,
        );

        result.weighted_score = weighted_score;
        result.overall_score = overall_score;
        result.verdict = calculator::get_verdict(overall_score, &scoring_data.red_flags);

        Ok(result)
    }

    /// 批量文章评分（带进度回调）
    pub async fn score_articles_batch<F>(
        &self,
        articles: &[crate::models::Article],
        target: &TargetConfig,
        cancel_check: impl Fn() -> bool,
        mut progress_callback: F,
    ) -> Result<Vec<ScoreResult>, ScoringError>
    where
        F: FnMut(ProgressEvent),
    {
        client::score_articles_batch(
            articles,
            target,
            &self.config,
            &self.client,
            cancel_check,
            &mut progress_callback,
        ).await
    }
}

impl Default for Scorer {
    fn default() -> Self {
        Self::new()
    }
}
