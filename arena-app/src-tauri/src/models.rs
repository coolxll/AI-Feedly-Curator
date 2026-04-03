use serde::{Deserialize, Serialize};

/// 文章数据结构
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Article {
    pub id: String,
    pub title: String,
    pub origin: String,
    pub link: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub published: Option<serde_json::Value>,
    pub summary: String,
    pub content: String,
}

impl Article {
    /// 从数据集项创建文章
    pub fn from_dataset_item(item: &serde_json::Value) -> Self {
        let summary = item
            .get("summary_excerpt")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        Self {
            id: item
                .get("id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            title: item
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            origin: item
                .get("origin")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            link: item
                .get("link")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            published: item.get("published").cloned(),
            summary: summary.clone(),
            content: summary,
        }
    }
}

/// 评分维度分数
#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default)]
pub struct DimensionScores {
    pub relevance: f64,
    pub informativeness_accuracy: f64,
    pub depth_opinion: f64,
    pub readability: f64,
    pub non_redundancy: f64,
}

/// 评分结果
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScoreResult {
    pub id: String,
    pub title: String,
    pub origin: String,
    pub link: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub published: Option<serde_json::Value>,

    // 维度分数
    pub relevance_score: f64,
    pub informativeness_accuracy_score: f64,
    pub depth_opinion_score: f64,
    pub readability_score: f64,
    pub non_redundancy_score: f64,

    // 计算分数
    pub weighted_score: f64,
    pub overall_score: f64,

    // 评价
    pub verdict: String,
    pub reason: String,
    pub why_not_higher: String,

    // 分类和标记
    pub article_type: String,
    pub red_flags: Vec<String>,
    pub negative_signals: Vec<String>,

    // 元数据
    pub model: String,
    pub label: String,
    pub base_url: String,

    // 多次运行统计
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score_min: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score_max: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score_spread: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score_stddev: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score_samples: Option<Vec<f64>>,
}

impl ScoreResult {
    /// 从评分数据创建结果
    pub fn from_scoring_data(
        article: &Article,
        data: &ScoringResponseData,
        target: &TargetConfig,
    ) -> Self {
        Self {
            id: article.id.clone(),
            title: article.title.clone(),
            origin: article.origin.clone(),
            link: article.link.clone(),
            published: article.published.clone(),
            relevance_score: data.scores.relevance,
            informativeness_accuracy_score: data.scores.informativeness_accuracy,
            depth_opinion_score: data.scores.depth_opinion,
            readability_score: data.scores.readability,
            non_redundancy_score: data.scores.non_redundancy,
            weighted_score: 0.0, // 由 calculator 填充
            overall_score: 0.0,  // 由 calculator 填充
            verdict: String::new(), // 由 calculator 填充
            reason: data.analysis.clone(),
            why_not_higher: data.why_not_higher.clone(),
            article_type: data.article_type.clone(),
            red_flags: data.red_flags.clone(),
            negative_signals: data.negative_signals.clone(),
            model: target.model.clone(),
            label: target.label.clone(),
            base_url: target.base_url.clone(),
            score_min: None,
            score_max: None,
            score_spread: None,
            score_stddev: None,
            score_samples: None,
        }
    }

    /// 创建错误结果
    pub fn error_result(article: &Article, error_msg: &str, target: &TargetConfig) -> Self {
        Self {
            id: article.id.clone(),
            title: article.title.clone(),
            origin: article.origin.clone(),
            link: article.link.clone(),
            published: article.published.clone(),
            relevance_score: 0.0,
            informativeness_accuracy_score: 0.0,
            depth_opinion_score: 0.0,
            readability_score: 0.0,
            non_redundancy_score: 0.0,
            weighted_score: 0.0,
            overall_score: 0.0,
            verdict: "解析错误".to_string(),
            reason: error_msg.to_string(),
            why_not_higher: String::new(),
            article_type: "default".to_string(),
            red_flags: vec![],
            negative_signals: vec![],
            model: target.model.clone(),
            label: target.label.clone(),
            base_url: target.base_url.clone(),
            score_min: None,
            score_max: None,
            score_spread: None,
            score_stddev: None,
            score_samples: None,
        }
    }
}

/// LLM 评分响应数据结构
#[derive(Debug, Clone, Deserialize)]
pub struct ScoringResponseData {
    pub analysis: String,
    pub why_not_higher: String,
    pub article_type: String,
    pub red_flags: Vec<String>,
    pub negative_signals: Vec<String>,
    pub scores: DimensionScores,
}

/// 批量评分响应项
#[derive(Debug, Clone, Deserialize)]
pub struct BatchScoringItem {
    pub index: usize,
    #[serde(flatten)]
    pub data: ScoringResponseData,
}

/// Target 配置
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TargetConfig {
    pub label: String,
    pub model: String,
    pub base_url: String,
    pub api_key_env: Option<String>,
    #[serde(skip_serializing)]
    pub api_key: String,
}

impl TargetConfig {
    /// 从 target spec 字符串解析
    /// 格式: label|model|base_url|api_key_token
    pub fn from_spec(spec: &str) -> Result<Self, String> {
        let parts: Vec<&str> = spec.split('|').collect();
        if parts.len() != 4 {
            return Err(format!(
                "Invalid target spec format. Expected: label|model|base_url|api_key_token, got: {}",
                spec
            ));
        }

        let label = parts[0].trim().to_string();
        let model = parts[1].trim().to_string();
        let base_url = parts[2].trim().to_string();
        let api_key_token = parts[3].trim().to_string();

        if label.is_empty() || model.is_empty() || base_url.is_empty() || api_key_token.is_empty() {
            return Err("All parts of target spec must be non-empty".to_string());
        }

        // 解析 api_key: 先尝试作为环境变量名读取，不存在则直接使用
        let (api_key, api_key_env) = match std::env::var(&api_key_token) {
            Ok(key) => (key, Some(api_key_token)),
            Err(_) => (api_key_token, None),
        };

        Ok(Self {
            label,
            model,
            base_url,
            api_key_env,
            api_key,
        })
    }
}

/// 维度权重配置
#[derive(Debug, Clone, Copy)]
pub struct DimensionWeights {
    pub relevance: f64,
    pub informativeness_accuracy: f64,
    pub depth_opinion: f64,
    pub readability: f64,
    pub non_redundancy: f64,
}

/// 文章类型权重配置
#[derive(Debug, Clone)]
pub struct ScoringWeights {
    pub news: DimensionWeights,
    pub tutorial: DimensionWeights,
    pub opinion: DimensionWeights,
    pub default: DimensionWeights,
}

impl Default for ScoringWeights {
    fn default() -> Self {
        Self {
            news: DimensionWeights {
                relevance: 0.40,
                informativeness_accuracy: 0.35,
                depth_opinion: 0.05,
                readability: 0.15,
                non_redundancy: 0.05,
            },
            tutorial: DimensionWeights {
                relevance: 0.35,
                informativeness_accuracy: 0.25,
                depth_opinion: 0.10,
                readability: 0.20,
                non_redundancy: 0.10,
            },
            opinion: DimensionWeights {
                relevance: 0.30,
                informativeness_accuracy: 0.20,
                depth_opinion: 0.35,
                readability: 0.10,
                non_redundancy: 0.05,
            },
            default: DimensionWeights {
                relevance: 0.35,
                informativeness_accuracy: 0.25,
                depth_opinion: 0.20,
                readability: 0.15,
                non_redundancy: 0.05,
            },
        }
    }
}

/// 运行报告
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunReport {
    pub generated_at: String,
    pub source_file: String,
    pub label: String,
    pub model: String,
    pub base_url: String,
    pub article_count: usize,
    pub average_score: f64,
    pub score_bands: serde_json::Value,
    pub article_types: serde_json::Value,
    pub top_origins: serde_json::Value,
    pub negative_signals: serde_json::Value,
    pub red_flags: serde_json::Value,
    pub top_articles: Vec<ScoreResult>,
    pub bottom_articles: Vec<ScoreResult>,
    pub rows: Vec<ScoreResult>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub repeat_count: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub run_reports: Option<Vec<RunReport>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stability: Option<StabilityMetrics>,
}

/// 稳定性指标
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StabilityMetrics {
    pub average_spread: f64,
    pub largest_spreads: Vec<SpreadItem>,
}

/// 分数波动项
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpreadItem {
    pub id: String,
    pub title: String,
    pub origin: String,
    pub score_samples: Vec<f64>,
    pub spread: f64,
    pub stddev: f64,
}

/// 多模型对比结果
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComparisonResult {
    pub models: Vec<String>,
    pub article_count: usize,
    pub average_score_by_model: serde_json::Value,
    pub largest_disagreements: Vec<DisagreementItem>,
}

/// 分歧项
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DisagreementItem {
    pub id: String,
    pub title: String,
    pub origin: String,
    pub score_by_model: serde_json::Value,
    pub spread: f64,
}

/// 运行记录 (最终落盘格式)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunRecord {
    pub id: String,
    pub dataset: String,
    pub target: String,
    pub timestamp: String,
    pub metrics: RunMetrics,
    pub results: Vec<RunResultItem>,
}

/// 运行指标
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunMetrics {
    pub average_spread: f64,
    pub max_spread: f64,
    pub high_score_rate: f64,
    pub negative_signal_presence_rate: f64,
    pub cheap_vs_sota_gap: f64,
}

/// 运行结果项
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunResultItem {
    pub item_id: String,
    pub title: String,
    pub score: f64,
    pub spread: f64,
    pub reason: String,
}

/// 数据集信息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatasetInfo {
    pub name: String,
    pub version: String,
    pub created_at: String,
    pub description: String,
    pub item_count: usize,
}

/// 数据集详情
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatasetDetail {
    pub dataset: String,
    pub version: String,
    pub created_at: String,
    pub description: String,
    pub source_files: Vec<String>,
    pub items: Vec<serde_json::Value>,
}

/// 进度事件
#[derive(Debug, Clone, Serialize)]
pub struct ProgressEvent {
    pub phase: String,
    pub current: usize,
    pub total: usize,
    pub percent: f64,
    pub message: String,
    pub target: Option<String>,
    pub mode: String,
    pub done: bool,
    pub error: bool,
}

/// 运行阶段
#[derive(Debug, Clone)]
pub enum RunPhase {
    Prepare,
    TargetStart {
        #[allow(dead_code)]
        label: String,
        #[allow(dead_code)]
        index: usize,
    },
    #[allow(dead_code)]
    BatchProgress {
        label: String,
        processed: usize,
        total: usize,
    },
    Finalize,
    Done,
    #[allow(dead_code)]
    Cancelled,
    #[allow(dead_code)]
    Error(String),
}
