#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tauri::Manager;
use chrono;

#[derive(Debug, Serialize, Deserialize)]
pub struct DatasetInfo {
    pub name: String,
    pub version: String,
    pub created_at: String,
    pub description: String,
    pub item_count: usize,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DatasetDetail {
    pub dataset: String,
    pub version: String,
    pub created_at: String,
    pub description: String,
    pub source_files: Vec<String>,
    pub items: Vec<serde_json::Value>,
}

fn get_datasets_dir() -> PathBuf {
    let datasets_path = PathBuf::from("arena").join("scoring").join("datasets");
    
    // 1. 当前工作目录（开发环境：从项目根目录运行）
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let cwd_path = cwd.join(&datasets_path);
    if cwd_path.exists() {
        return cwd_path;
    }
    
    // 2. 从 exe 向上逐层查找项目根目录（通过检测 arena/scoring/datasets 目录）
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(mut path) = exe_path.parent() {
            loop {
                let test_path = path.join(&datasets_path);
                if test_path.exists() {
                    return test_path;
                }
                match path.parent() {
                    Some(parent) => path = parent,
                    None => break,
                }
            }
        }
    }
    
    // 3. 默认返回当前目录下的路径（用于错误提示）
    cwd.join(&datasets_path)
}

fn get_configs_dir() -> PathBuf {
    let configs_path = PathBuf::from("arena").join("scoring").join("configs");
    
    // 1. 当前工作目录
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let cwd_path = cwd.join(&configs_path);
    if cwd_path.exists() {
        return cwd_path;
    }
    
    // 2. 从 exe 向上逐层查找
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(mut path) = exe_path.parent() {
            loop {
                let test_path = path.join(&configs_path);
                if test_path.exists() {
                    return test_path;
                }
                match path.parent() {
                    Some(parent) => path = parent,
                    None => break,
                }
            }
        }
    }
    
    cwd.join(&configs_path)
}

fn get_runs_dir() -> PathBuf {
    let runs_path = PathBuf::from("arena").join("scoring").join("runs");
    
    // 1. 当前工作目录
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let cwd_path = cwd.join(&runs_path);
    if cwd_path.exists() {
        return cwd_path;
    }
    
    // 2. 从 exe 向上逐层查找
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(mut path) = exe_path.parent() {
            loop {
                let test_path = path.join(&runs_path);
                if test_path.exists() {
                    return test_path;
                }
                match path.parent() {
                    Some(parent) => path = parent,
                    None => break,
                }
            }
        }
    }
    
    cwd.join(&runs_path)
}

#[tauri::command]
fn app_health() -> String {
    "arena-app-shell-ready".to_string()
}

#[tauri::command]
fn list_runs() -> Result<Vec<serde_json::Value>, String> {
    let runs_dir = get_runs_dir();
    
    if !runs_dir.exists() {
        return Ok(Vec::new());
    }
    
    let mut runs = Vec::new();
    let entries = fs::read_dir(&runs_dir)
        .map_err(|e| format!("Failed to read runs directory: {}", e))?;
    
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map(|e| e == "json").unwrap_or(false) {
            let filename = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if filename == "targets.json" || filename == "datasets.json" || filename == ".gitkeep" {
                continue;
            }
            
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
                    runs.push(json);
                }
            }
        }
    }
    
    // 按时间戳降序排序
    runs.sort_by(|a, b| {
        let ta = a.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        let tb = b.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        tb.cmp(ta)
    });
    
    Ok(runs)
}

#[tauri::command]
fn get_run_detail(id: String) -> Result<serde_json::Value, String> {
    let runs_dir = get_runs_dir();
    let file_path = runs_dir.join(format!("{}.json", id));
    
    if !file_path.exists() {
        return Err(format!("Run record not found: {}", id));
    }
    
    let content = fs::read_to_string(&file_path)
        .map_err(|e| format!("Failed to read run record: {}", e))?;
    
    let json: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse run record JSON: {}", e))?;
    
    Ok(json)
}

#[tauri::command]
fn load_targets() -> Result<Vec<String>, String> {
    let configs_dir = get_configs_dir();
    let file_path = configs_dir.join("targets.json");
    
    if !file_path.exists() {
        return Ok(Vec::new());
    }
    
    let content = fs::read_to_string(&file_path)
        .map_err(|e| format!("Failed to read targets.json: {}", e))?;
    
    let json: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse targets.json: {}", e))?;
    
    let targets = json.get("targets")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    
    Ok(targets)
}

#[tauri::command]
fn save_targets(targets: Vec<String>) -> Result<(), String> {
    let configs_dir = get_configs_dir();
    if !configs_dir.exists() {
        fs::create_dir_all(&configs_dir).map_err(|e| format!("Failed to create configs directory: {}", e))?;
    }
    
    let file_path = configs_dir.join("targets.json");
    let json = serde_json::json!({ "targets": targets });
    let content = serde_json::to_string_pretty(&json)
        .map_err(|e| format!("Failed to serialize targets: {}", e))?;
    
    fs::write(file_path, content)
        .map_err(|e| format!("Failed to write targets.json: {}", e))?;
    
    Ok(())
}

#[tauri::command]
fn start_run(dataset: String, targets: Vec<String>) -> Result<String, String> {
    let runs_dir = get_runs_dir();
    if !runs_dir.exists() {
        fs::create_dir_all(&runs_dir).map_err(|e| format!("Failed to create runs directory: {}", e))?;
    }

    let now = chrono::Local::now();
    let timestamp = now.format("%Y%m%d-%H%M%S").to_string();
    let run_id = format!("run-{}", timestamp);
    let file_path = runs_dir.join(format!("{}.json", run_id));

    // 生成模拟结果供 UI 使用
    let target_name = targets.first().cloned().unwrap_or_else(|| "unknown".to_string());
    let sample_result = serde_json::json!({
        "id": run_id,
        "dataset": dataset,
        "target": target_name,
        "timestamp": now.to_rfc3339(),
        "metrics": {
            "average_spread": 0.45,
            "max_spread": 1.2,
            "high_score_rate": 0.12,
            "negative_signal_presence_rate": 0.95,
            "cheap_vs_sota_gap": 0.08
        },
        "results": [
            { "item_id": "01", "title": "Example Item 1", "score": 8, "spread": 0.1, "reason": "Consistent high quality content." },
            { "item_id": "02", "title": "Example Item 2", "score": 3, "spread": 0.5, "reason": "Slightly ambiguous signal." },
            { "item_id": "03", "title": "Example Item 3", "score": 7, "spread": 0.2, "reason": "Good depth but could be sharper." }
        ]
    });

    let content = serde_json::to_string_pretty(&sample_result)
        .map_err(|e| format!("Failed to serialize result: {}", e))?;
    
    fs::write(file_path, content)
        .map_err(|e| format!("Failed to write run record: {}", e))?;

    Ok(format!("Started run {} for {}", run_id, dataset))
}

#[tauri::command]
fn list_datasets() -> Result<Vec<DatasetInfo>, String> {
    let datasets_dir = get_datasets_dir();
    
    if !datasets_dir.exists() {
        return Err(format!("Datasets directory not found: {:?}", datasets_dir));
    }
    
    let mut datasets = Vec::new();
    
    let entries = fs::read_dir(&datasets_dir)
        .map_err(|e| format!("Failed to read datasets directory: {}", e))?;
    
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map(|e| e == "json").unwrap_or(false) {
            if let Ok(content) = fs::read_to_string(&path) {
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
    
    // 按名称排序
    datasets.sort_by(|a, b| a.name.cmp(&b.name));
    
    Ok(datasets)
}

#[tauri::command]
fn get_dataset(name: String) -> Result<DatasetDetail, String> {
    let datasets_dir = get_datasets_dir();
    let file_path = datasets_dir.join(format!("{}.json", name));
    
    if !file_path.exists() {
        return Err(format!("Dataset not found: {}", name));
    }
    
    let content = fs::read_to_string(&file_path)
        .map_err(|e| format!("Failed to read dataset file: {}", e))?;
    
    let json: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse dataset JSON: {}", e))?;
    
    let dataset = DatasetDetail {
        dataset: json.get("dataset").and_then(|v| v.as_str()).unwrap_or(&name).to_string(),
        version: json.get("version").and_then(|v| v.as_str()).unwrap_or("unknown").to_string(),
        created_at: json.get("created_at").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        description: json.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        source_files: json.get("source_files")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default(),
        items: json.get("items")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default(),
    };
    
    Ok(dataset)
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            app_health,
            list_datasets,
            get_dataset,
            load_targets,
            save_targets,
            start_run,
            list_runs,
            get_run_detail
        ])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                window.set_title("Scoring Arena").ok();
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running arena-app");
}
