use crate::models::{DimensionWeights, ScoringWeights};
use directories::ProjectDirs;
use std::path::PathBuf;

/// 默认相关性阈值
pub const RELEVANCE_THRESHOLD: f64 = 2.5;

/// 默认分数锚点
pub const DEFAULT_SCORE_ANCHOR: f64 = 3.0;

/// 高分阈值
pub const HIGH_SCORE_THRESHOLD: f64 = 4.2;

/// 推荐阈值
pub const RECOMMENDED_SCORE_THRESHOLD: f64 = 3.6;

/// 负面信号惩罚
pub const NEGATIVE_SIGNAL_PENALTY: f64 = 0.35;

/// Hard red flags
#[allow(dead_code)]
pub const HARD_RED_FLAGS: &[&str] = &["ai_generated"];

/// 评分 Persona
pub const SCORING_PERSONA: &str = r#"你是一名关注广泛的资深程序员。
你的核心身份是：
1. **技术专家**：关注测试开发、DevOps、AI 编程、Vibe Coding 等前沿技术。

除了技术，你还有两个重要的兴趣领域：
2. **投资理财 (P1)**：对市场动态、宏观经济、投资策略非常敏感。
3. **国际政治 (P2)**：关注地缘政治、国际关系等大局势新闻。

打分时，请根据**这三个维度的综合价值**来评估。如果文章主要讲技术，按技术标准评；如果讲投资或政治，按其深度和价值评。
"#;

/// 应用配置
#[derive(Debug, Clone)]
pub struct AppConfig {
    pub scoring_weights: ScoringWeights,
    pub relevance_threshold: f64,
    pub scoring_persona: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            scoring_weights: ScoringWeights::default(),
            relevance_threshold: RELEVANCE_THRESHOLD,
            scoring_persona: SCORING_PERSONA.to_string(),
        }
    }
}

impl AppConfig {
    /// 获取指定类型的权重
    pub fn get_weights(&self, article_type: &str) -> &DimensionWeights {
        match article_type {
            "news" => &self.scoring_weights.news,
            "tutorial" => &self.scoring_weights.tutorial,
            "opinion" => &self.scoring_weights.opinion,
            _ => &self.scoring_weights.default,
        }
    }
}

/// 从 targets.json 加载 target 配置（保留原始字符串，包括格式错误的）
pub fn load_targets() -> Result<Vec<String>, String> {
    let config_path = get_targets_config_path()?;

    if !config_path.exists() {
        return Ok(Vec::new());
    }

    let content =
        std::fs::read_to_string(&config_path).map_err(|e| format!("Failed to read targets.json: {}", e))?;

    let json: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse targets.json: {}", e))?;

    let targets = json
        .get("targets")
        .and_then(|v| v.as_array())
        .ok_or("targets.json missing 'targets' array")?;

    // 保留原始字符串，包括格式错误的，让用户可以在 UI 中修复
    let mut specs = Vec::new();
    for target in targets {
        if let Some(spec) = target.as_str() {
            specs.push(spec.to_string());
        }
    }

    Ok(specs)
}

/// 保存 target 配置
pub fn save_targets(targets: &[String]) -> Result<(), String> {
    let config_path = get_targets_config_path()?;

    // 确保目录存在
    if let Some(parent) = config_path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create config directory: {}", e))?;
    }

    let json = serde_json::json!({ "targets": targets });
    let content = serde_json::to_string_pretty(&json)
        .map_err(|e| format!("Failed to serialize targets: {}", e))?;

    std::fs::write(&config_path, content)
        .map_err(|e| format!("Failed to write targets.json: {}", e))?;

    Ok(())
}

/// 获取 targets.json 路径
fn get_targets_config_path() -> Result<PathBuf, String> {
    Ok(get_configs_dir()?.join("targets.json"))
}

/// 获取应用数据根目录
fn get_storage_root() -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("ARENA_APP_DATA_DIR") {
        let root = PathBuf::from(path);
        ensure_storage_layout(&root)?;
        migrate_legacy_repo_data_if_needed(&root)?;
        return Ok(root);
    }

    let dirs = ProjectDirs::from("com", "coolx", "arena-app")
        .ok_or("Failed to resolve application data directory")?;
    let root = dirs.data_local_dir().join("scoring");

    ensure_storage_layout(&root)?;
    migrate_legacy_repo_data_if_needed(&root)?;

    Ok(root)
}

fn ensure_storage_layout(root: &std::path::Path) -> Result<(), String> {
    std::fs::create_dir_all(root.join("datasets"))
        .map_err(|e| format!("Failed to create datasets directory: {}", e))?;
    std::fs::create_dir_all(root.join("runs"))
        .map_err(|e| format!("Failed to create runs directory: {}", e))?;
    std::fs::create_dir_all(root.join("configs"))
        .map_err(|e| format!("Failed to create configs directory: {}", e))?;
    Ok(())
}

fn migrate_legacy_repo_data_if_needed(root: &std::path::Path) -> Result<(), String> {
    if has_any_storage_content(root) {
        return Ok(());
    }

    let Some(legacy_root) = find_legacy_repo_storage() else {
        return Ok(());
    };

    copy_dir_if_present(&legacy_root.join("datasets"), &root.join("datasets"))?;
    copy_dir_if_present(&legacy_root.join("runs"), &root.join("runs"))?;
    copy_dir_if_present(&legacy_root.join("configs"), &root.join("configs"))?;

    Ok(())
}

fn has_any_storage_content(root: &std::path::Path) -> bool {
    ["datasets", "runs", "configs"].iter().any(|name| {
        let dir = root.join(name);
        dir.exists()
            && std::fs::read_dir(dir)
                .ok()
                .map(|mut entries| entries.next().is_some())
                .unwrap_or(false)
    })
}

fn find_legacy_repo_storage() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    find_legacy_repo_storage_from(&cwd).or_else(|| {
        let exe_dir = std::env::current_exe().ok()?;
        let parent = exe_dir.parent()?;
        find_legacy_repo_storage_from(parent)
    })
}

fn find_legacy_repo_storage_from(start: &std::path::Path) -> Option<PathBuf> {
    let mut path = start;
    loop {
        let candidate = path.join("arena").join("scoring");
        if candidate.exists() {
            return Some(candidate);
        }

        path = path.parent()?;
    }
}

fn copy_dir_if_present(from: &std::path::Path, to: &std::path::Path) -> Result<(), String> {
    if !from.exists() {
        return Ok(());
    }

    std::fs::create_dir_all(to)
        .map_err(|e| format!("Failed to create migration directory {}: {}", to.display(), e))?;

    for entry in std::fs::read_dir(from)
        .map_err(|e| format!("Failed to read legacy directory {}: {}", from.display(), e))?
    {
        let entry = entry.map_err(|e| format!("Failed to read legacy entry: {}", e))?;
        let path = entry.path();
        let dest = to.join(entry.file_name());

        if path.is_dir() {
            copy_dir_if_present(&path, &dest)?;
        } else if !dest.exists() {
            std::fs::copy(&path, &dest).map_err(|e| {
                format!(
                    "Failed to migrate {} to {}: {}",
                    path.display(),
                    dest.display(),
                    e
                )
            })?;
        }
    }

    Ok(())
}

/// 获取数据集目录
pub fn get_datasets_dir() -> Result<PathBuf, String> {
    Ok(get_storage_root()?.join("datasets"))
}

/// 获取运行记录目录
pub fn get_runs_dir() -> Result<PathBuf, String> {
    Ok(get_storage_root()?.join("runs"))
}

/// 获取配置目录
#[allow(dead_code)]
pub fn get_configs_dir() -> Result<PathBuf, String> {
    Ok(get_storage_root()?.join("configs"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::TargetConfig;

    #[test]
    fn test_target_config_from_spec_with_env() {
        // 设置测试环境变量
        std::env::set_var("TEST_API_KEY", "test_key_from_env");

        let spec = "gpt-4o|gpt-4o-mini|https://api.openai.com/v1/|TEST_API_KEY";
        let config = TargetConfig::from_spec(spec).unwrap();

        assert_eq!(config.label, "gpt-4o");
        assert_eq!(config.model, "gpt-4o-mini");
        assert_eq!(config.base_url, "https://api.openai.com/v1/");
        assert_eq!(config.api_key, "test_key_from_env");
        assert_eq!(config.api_key_env, Some("TEST_API_KEY".to_string()));
    }

    #[test]
    fn test_target_config_from_spec_with_plain_key() {
        let spec = "qwen|qwen-turbo|https://dashscope.aliyuncs.com/v1/|sk-plain-key";
        let config = TargetConfig::from_spec(spec).unwrap();

        assert_eq!(config.label, "qwen");
        assert_eq!(config.model, "qwen-turbo");
        assert_eq!(config.base_url, "https://dashscope.aliyuncs.com/v1/");
        assert_eq!(config.api_key, "sk-plain-key");
        assert_eq!(config.api_key_env, None);
    }

    #[test]
    fn test_target_config_invalid_format() {
        let spec = "invalid|spec";
        assert!(TargetConfig::from_spec(spec).is_err());
    }

    #[test]
    fn test_app_config_get_weights() {
        let config = AppConfig::default();

        let news_weights = config.get_weights("news");
        assert_eq!(news_weights.relevance, 0.40);

        let tutorial_weights = config.get_weights("tutorial");
        assert_eq!(tutorial_weights.relevance, 0.35);

        let unknown_weights = config.get_weights("unknown");
        assert_eq!(unknown_weights.relevance, 0.35); // default
    }
}
