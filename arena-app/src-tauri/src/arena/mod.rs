pub mod report;
pub mod runner;

use crate::models::{DatasetDetail, DatasetInfo};
use crate::config::{get_datasets_dir, get_runs_dir};

/// 加载数据集列表
pub fn list_datasets() -> Result<Vec<DatasetInfo>, String> {
    let datasets_dir = get_datasets_dir()?;

    if !datasets_dir.exists() {
        return Ok(Vec::new());
    }

    let mut datasets = Vec::new();
    let entries = std::fs::read_dir(&datasets_dir)
        .map_err(|e| format!("Failed to read datasets directory: {}", e))?;

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map(|e| e == "json").unwrap_or(false) {
            if let Ok(content) = std::fs::read_to_string(&path) {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
                    if let (Some(dataset), Some(version), Some(created_at), Some(description), Some(items)) = (
                        json.get("dataset").and_then(|v| v.as_str()),
                        json.get("version").and_then(|v| v.as_str()),
                        json.get("created_at").and_then(|v| v.as_str()),
                        json.get("description").and_then(|v| v.as_str()),
                        json.get("items").and_then(|v| v.as_array()),
                    ) {
                        datasets.push(DatasetInfo {
                            name: dataset.to_string(),
                            version: version.to_string(),
                            created_at: created_at.to_string(),
                            description: description.to_string(),
                            item_count: items.len(),
                        });
                    }
                }
            }
        }
    }

    datasets.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(datasets)
}

/// 获取数据集详情
pub fn get_dataset(name: &str) -> Result<DatasetDetail, String> {
    let datasets_dir = get_datasets_dir()?;
    let file_path = datasets_dir.join(format!("{}.json", name));

    if !file_path.exists() {
        return Err(format!("Dataset not found: {}", name));
    }

    let content = std::fs::read_to_string(&file_path)
        .map_err(|e| format!("Failed to read dataset file: {}", e))?;

    let json: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse dataset JSON: {}", e))?;

    Ok(DatasetDetail {
        dataset: json
            .get("dataset")
            .and_then(|v| v.as_str())
            .unwrap_or(name)
            .to_string(),
        version: json
            .get("version")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        created_at: json
            .get("created_at")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        description: json
            .get("description")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        source_files: json
            .get("source_files")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default(),
        items: json
            .get("items")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default(),
    })
}

/// 列出运行记录
pub fn list_runs() -> Result<Vec<serde_json::Value>, String> {
    let runs_dir = get_runs_dir()?;

    if !runs_dir.exists() {
        return Ok(Vec::new());
    }

    let mut runs = Vec::new();
    let entries = std::fs::read_dir(&runs_dir)
        .map_err(|e| format!("Failed to read runs directory: {}", e))?;

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map(|e| e == "json").unwrap_or(false) {
            let filename = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if filename == "targets.json" || filename == "datasets.json" || filename == ".gitkeep" {
                continue;
            }

            if let Ok(content) = std::fs::read_to_string(&path) {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
                    runs.push(json);
                }
            }
        }
    }

    runs.sort_by(|a, b| {
        let ta = a.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        let tb = b.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        tb.cmp(ta)
    });

    Ok(runs)
}

/// 获取运行详情
pub fn get_run_detail(id: &str) -> Result<serde_json::Value, String> {
    let runs_dir = get_runs_dir()?;
    let file_path = runs_dir.join(format!("{}.json", id));

    if !file_path.exists() {
        return Err(format!("Run record not found: {}", id));
    }

    let content = std::fs::read_to_string(&file_path)
        .map_err(|e| format!("Failed to read run record: {}", e))?;

    let json: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse run record JSON: {}", e))?;

    Ok(json)
}
