use crate::config::AppConfig;
use crate::models::{Article, BatchScoringItem, ProgressEvent, ScoreResult, TargetConfig};
use crate::scoring::parser;
use crate::scoring::prompt;
use crate::scoring::ScoringError;
use reqwest::Client;
use serde_json::json;
use std::time::Duration;

/// OpenAI API 客户端
pub struct OpenAIClient {
    client: Client,
}

impl OpenAIClient {
    /// 创建新的客户端
    pub fn new() -> Self {
        Self {
            client: Client::builder()
                .timeout(Duration::from_secs(120))
                .build()
                .expect("Failed to create HTTP client"),
        }
    }

    /// 发送聊天完成请求（支持取消检查）
    pub async fn chat_completion(
        &self,
        target: &TargetConfig,
        prompt: &str,
        cancel_check: &dyn Fn() -> bool,
    ) -> Result<String, ScoringError> {
        let url = format!("{}/chat/completions", target.base_url.trim_end_matches('/'));

        let body = json!({
            "model": target.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 16000
        });

        // 发送请求前检查取消
        if cancel_check() {
            return Err(ScoringError::Cancelled);
        }

        let request = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", target.api_key))
            .header("Content-Type", "application/json")
            .json(&body)
            .send();
        tokio::pin!(request);

        let response = loop {
            tokio::select! {
                result = &mut request => {
                    break result.map_err(|e| ScoringError::NetworkError(e.to_string()))?;
                }
                _ = tokio::time::sleep(Duration::from_millis(200)) => {
                    if cancel_check() {
                        return Err(ScoringError::Cancelled);
                    }
                }
            }
        };

        // 响应返回后检查取消（允许中止后续处理）
        if cancel_check() {
            return Err(ScoringError::Cancelled);
        }

        if !response.status().is_success() {
            let status = response.status();
            // 只记录错误状态码，不记录响应内容以避免泄露敏感信息
            eprintln!("[ERROR] API request failed with HTTP {}", status);
            return Err(ScoringError::ApiError(format!(
                "HTTP {}: Request failed", status
            )));
        }

        let json: serde_json::Value = response
            .json()
            .await
            .map_err(|e| ScoringError::ParseError(format!("Failed to parse response: {}", e)))?;

        let content = json
            .get("choices")
            .and_then(|c| c.get(0))
            .and_then(|c| c.get("message"))
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .ok_or_else(|| ScoringError::InvalidResponse)?;

        Ok(content.to_string())
    }
}

impl Default for OpenAIClient {
    fn default() -> Self {
        Self::new()
    }
}

/// 批量评分文章（带进度回调）
pub async fn score_articles_batch<F>(
    articles: &[Article],
    target: &TargetConfig,
    config: &AppConfig,
    client: &OpenAIClient,
    cancel_check: impl Fn() -> bool,
    progress_callback: &mut F,
) -> Result<Vec<ScoreResult>, ScoringError>
where
    F: FnMut(ProgressEvent),
{
    const MAX_RETRIES: usize = 3;
    let total_articles = articles.len();

    // 发送开始评分进度
    progress_callback(ProgressEvent {
        phase: "scoring".to_string(),
        current: 0,
        total: total_articles,
        percent: 0.0,
        message: format!("Preparing batch prompt for {} articles...", total_articles),
        target: Some(target.label.clone()),
        mode: "real".to_string(),
        done: false,
        error: false,
    });

    // 准备批量 prompt
    let articles_for_prompt: Vec<(String, String, String)> = articles
        .iter()
        .map(|a| (a.title.clone(), a.summary.clone(), a.content.clone()))
        .collect();

    let prompt = prompt::build_batch_scoring_prompt(&articles_for_prompt, &config.scoring_persona);

    // 重试循环
    for attempt in 0..MAX_RETRIES {
        // 检查取消
        if cancel_check() {
            return Err(ScoringError::Cancelled);
        }

        // 发送 API 请求进度
        progress_callback(ProgressEvent {
            phase: "api_request".to_string(),
            current: 0,
            total: total_articles,
            percent: 5.0 + (attempt as f64 * 2.0),
            message: format!(
                "Requesting LLM scores from {} (attempt {}/{})...",
                target.label,
                attempt + 1,
                MAX_RETRIES
            ),
            target: Some(target.label.clone()),
            mode: "real".to_string(),
            done: false,
            error: false,
        });

        log::info!("Batch scoring attempt {}/{}...", attempt + 1, MAX_RETRIES);

        match client.chat_completion(target, &prompt, &cancel_check).await {
            Ok(response_text) => {
                if response_text.is_empty() {
                    log::warn!("Batch attempt {} failed: Empty response", attempt + 1);
                    
                    progress_callback(ProgressEvent {
                        phase: "retry".to_string(),
                        current: 0,
                        total: total_articles,
                        percent: 10.0,
                        message: format!("Empty response, retrying... (attempt {}/{})", attempt + 1, MAX_RETRIES),
                        target: Some(target.label.clone()),
                        mode: "real".to_string(),
                        done: false,
                        error: false,
                    });
                    continue;
                }

                // 发送解析进度
                progress_callback(ProgressEvent {
                    phase: "parsing".to_string(),
                    current: 0,
                    total: total_articles,
                    percent: 30.0,
                    message: format!("Parsing batch response from {}...", target.label),
                    target: Some(target.label.clone()),
                    mode: "real".to_string(),
                    done: false,
                    error: false,
                });

                // 解析批量响应
                match parse_batch_response(&response_text, articles.len()) {
                    Some(batch_results) => {
                        // 检查是否有缺失项
                        let missing_indices: Vec<usize> = batch_results
                            .iter()
                            .enumerate()
                            .filter(|(_, r)| r.is_none())
                            .map(|(i, _)| i)
                            .collect();

                        // 为所有成功的结果添加模型信息并计算分数
                        let mut results: Vec<ScoreResult> = batch_results
                            .into_iter()
                            .enumerate()
                            .map(|(i, data)| {
                                if let Some(data) = data {
                                    let mut result =
                                        ScoreResult::from_scoring_data(&articles[i], &data, target);

                                    let (weighted, overall) = crate::scoring::calculator::calculate_scores(
                                        &data.scores,
                                        &data.article_type,
                                        &data.red_flags,
                                        &data.negative_signals,
                                        &data.why_not_higher,
                                        config,
                                    );

                                    result.weighted_score = weighted;
                                    result.overall_score = overall;
                                    result.verdict = crate::scoring::calculator::get_verdict(
                                        overall,
                                        &data.red_flags,
                                    );

                                    result
                                } else {
                                    // 占位，稍后补全
                                    ScoreResult::error_result(&articles[i], "Pending fill", target)
                                }
                            })
                            .collect();

                        if missing_indices.is_empty() {
                            // 发送完成进度
                            progress_callback(ProgressEvent {
                                phase: "scored".to_string(),
                                current: total_articles,
                                total: total_articles,
                                percent: 100.0,
                                message: format!("Scored all {} articles for {}", total_articles, target.label),
                                target: Some(target.label.clone()),
                                mode: "real".to_string(),
                                done: true,
                                error: false,
                            });
                            return Ok(results);
                        }

                        log::warn!(
                            "Batch attempt {} partial success. Missing indices: {:?}. Filling gaps...",
                            attempt + 1,
                            missing_indices
                        );

                        // 补全缺失项（单篇调用）
                        let missing_count = missing_indices.len();
                        for (gap_idx, &i) in missing_indices.iter().enumerate() {
                            if cancel_check() {
                                return Err(ScoringError::Cancelled);
                            }

                            // 发送补全进度
                            progress_callback(ProgressEvent {
                                phase: "fill_gap".to_string(),
                                current: gap_idx + 1,
                                total: missing_count,
                                percent: 50.0 + ((gap_idx + 1) as f64 / missing_count as f64 * 40.0),
                                message: format!(
                                    "Filling gap {} of {} for {}...",
                                    gap_idx + 1,
                                    missing_count,
                                    target.label
                                ),
                                target: Some(target.label.clone()),
                                mode: "real".to_string(),
                                done: false,
                                error: false,
                            });

                            log::info!("Filling gap for article {} (single mode)...", i);

                            match score_single_article(&articles[i], target, config, client, &cancel_check).await {
                                Ok(result) => {
                                    results[i] = result;
                                }
                                Err(e) => {
                                    log::error!("Failed to fill gap for article {}: {}", i, e);
                                    results[i] = ScoreResult::error_result(
                                        &articles[i],
                                        &format!("Fill gap failed: {}", e),
                                        target,
                                    );
                                }
                            }
                        }

                        // 发送完成进度
                        progress_callback(ProgressEvent {
                            phase: "scored".to_string(),
                            current: total_articles,
                            total: total_articles,
                            percent: 100.0,
                            message: format!("Scored all {} articles for {} (with {} gap fills)", total_articles, target.label, missing_count),
                            target: Some(target.label.clone()),
                            mode: "real".to_string(),
                            done: true,
                            error: false,
                        });

                        return Ok(results);
                    }
                    None => {
                        log::warn!(
                            "Batch attempt {} failed: Parse error or no valid objects found",
                            attempt + 1
                        );
                        log::warn!("Response length: {} chars", response_text.len());
                        log::warn!(
                            "Response starts with: {}",
                            &response_text[..response_text.len().min(200)]
                        );

                        progress_callback(ProgressEvent {
                            phase: "parse_error".to_string(),
                            current: 0,
                            total: total_articles,
                            percent: 15.0,
                            message: format!("Parse error, retrying... (attempt {}/{})", attempt + 1, MAX_RETRIES),
                            target: Some(target.label.clone()),
                            mode: "real".to_string(),
                            done: false,
                            error: false,
                        });
                    }
                }
            }
            Err(e) => {
                let is_rate_limit = e.to_string().contains("429");

                if is_rate_limit {
                    let delay = (2_u64.pow(attempt as u32)) * 1500 + (rand::random::<u64>() % 1000);
                    log::warn!(
                        "Batch attempt {} hit Rate Limit (429). Cooling down for {}ms...",
                        attempt + 1,
                        delay
                    );

                    progress_callback(ProgressEvent {
                        phase: "rate_limit".to_string(),
                        current: 0,
                        total: total_articles,
                        percent: 10.0,
                        message: format!("Rate limit hit, cooling down for {}s...", delay / 1000),
                        target: Some(target.label.clone()),
                        mode: "real".to_string(),
                        done: false,
                        error: false,
                    });
                    tokio::time::sleep(Duration::from_millis(delay)).await;
                } else {
                    log::warn!("Batch attempt {} exception: {}", attempt + 1, e);

                    progress_callback(ProgressEvent {
                        phase: "api_error".to_string(),
                        current: 0,
                        total: total_articles,
                        percent: 10.0,
                        message: format!("API error: {}, retrying...", e),
                        target: Some(target.label.clone()),
                        mode: "real".to_string(),
                        done: false,
                        error: false,
                    });
                    tokio::time::sleep(Duration::from_secs(1)).await;
                }
            }
        }
    }

    // 所有重试都失败了，回退到单篇评分
    log::error!("All batch scoring attempts failed. Falling back to single mode...");

    progress_callback(ProgressEvent {
        phase: "fallback".to_string(),
        current: 0,
        total: total_articles,
        percent: 20.0,
        message: format!("Batch failed, falling back to single article mode for {}...", target.label),
        target: Some(target.label.clone()),
        mode: "real".to_string(),
        done: false,
        error: false,
    });

    let mut results = Vec::with_capacity(articles.len());
    for (idx, article) in articles.iter().enumerate() {
        if cancel_check() {
            return Err(ScoringError::Cancelled);
        }

        // 发送单篇评分进度
        progress_callback(ProgressEvent {
            phase: "single_scoring".to_string(),
            current: idx + 1,
            total: total_articles,
            percent: 20.0 + ((idx + 1) as f64 / total_articles as f64 * 80.0),
            message: format!("Scoring article {} of {} for {}...", idx + 1, total_articles, target.label),
            target: Some(target.label.clone()),
            mode: "real".to_string(),
            done: false,
            error: false,
        });

        match score_single_article(article, target, config, client, &cancel_check).await {
            Ok(result) => results.push(result),
            Err(e) => {
                results.push(ScoreResult::error_result(article, &e.to_string(), target));
            }
        }
    }

    // 发送完成进度
    progress_callback(ProgressEvent {
        phase: "scored".to_string(),
        current: total_articles,
        total: total_articles,
        percent: 100.0,
        message: format!("Completed scoring {} articles for {} (fallback mode)", total_articles, target.label),
        target: Some(target.label.clone()),
        mode: "real".to_string(),
        done: true,
        error: false,
    });

    Ok(results)
}

/// 解析批量评分响应
fn parse_batch_response(
    response_text: &str,
    expected_count: usize,
) -> Option<Vec<Option<crate::models::ScoringResponseData>>> {
    let data: Vec<BatchScoringItem> =
        if let Some(json_str) = parser::extract_json_array_from_response(response_text) {
            match serde_json::from_str::<Vec<BatchScoringItem>>(&json_str) {
                Ok(items) if !items.is_empty() => items,
                _ => parser::robust_parse_objects(response_text)
                    .into_iter()
                    .filter_map(|obj| serde_json::from_value(obj).ok())
                    .collect(),
            }
        } else {
            parser::robust_parse_objects(response_text)
                .into_iter()
                .filter_map(|obj| serde_json::from_value(obj).ok())
                .collect()
        };

    if data.is_empty() {
        return None;
    }

    // 按索引组织结果
    let mut results_by_index: std::collections::HashMap<usize, crate::models::ScoringResponseData> =
        std::collections::HashMap::new();

    for item in data {
        results_by_index.insert(item.index, item.data);
    }

    // 构造有序列表（包含 None 占位符）
    let mut ordered = Vec::with_capacity(expected_count);
    let mut valid_count = 0;

    for i in 0..expected_count {
        if let Some(data) = results_by_index.get(&i) {
            ordered.push(Some(data.clone()));
            valid_count += 1;
        } else {
            ordered.push(None);
        }
    }

    if valid_count == 0 {
        return None;
    }

    Some(ordered)
}

/// 单篇文章评分
async fn score_single_article(
    article: &Article,
    target: &TargetConfig,
    config: &AppConfig,
    client: &OpenAIClient,
    cancel_check: &dyn Fn() -> bool,
) -> Result<ScoreResult, ScoringError> {
    let prompt = prompt::build_scoring_prompt(
        &article.title,
        &article.summary,
        &article.content,
        &config.scoring_persona,
    );

    let response = client.chat_completion(target, &prompt, cancel_check).await?;

    let data = parser::extract_json_from_response(&response)
        .ok_or_else(|| ScoringError::ParseError("Failed to extract JSON from response".to_string()))?;

    let scoring_data: crate::models::ScoringResponseData = serde_json::from_str(&data)
        .map_err(|e| ScoringError::ParseError(format!("Failed to parse scoring data: {}", e)))?;

    let mut result = ScoreResult::from_scoring_data(article, &scoring_data, target);

    let (weighted, overall) = crate::scoring::calculator::calculate_scores(
        &scoring_data.scores,
        &scoring_data.article_type,
        &scoring_data.red_flags,
        &scoring_data.negative_signals,
        &scoring_data.why_not_higher,
        config,
    );

    result.weighted_score = weighted;
    result.overall_score = overall;
    result.verdict = crate::scoring::calculator::get_verdict(overall, &scoring_data.red_flags);

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::parse_batch_response;

    #[test]
    fn test_parse_batch_response_recovers_truncated_array() {
        let response = r#"
        [
          {"index":0,"analysis":"ok","why_not_higher":"n/a","article_type":"news","red_flags":[],"negative_signals":[],"scores":{"relevance":4,"informativeness_accuracy":4,"depth_opinion":3,"readability":4,"non_redundancy":4}},
          {"index":1,"analysis":"partial"
        "#;

        let parsed = parse_batch_response(response, 2).expect("should recover partial objects");
        assert!(parsed[0].is_some());
        assert!(parsed[1].is_none());
    }
}
