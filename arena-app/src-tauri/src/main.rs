#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod arena;
mod config;
mod models;
mod scoring;

use arena::runner::{run_benchmark, RunnerState};
use models::{DatasetDetail, DatasetInfo};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{Emitter, Manager, State, Window};

// 进度事件结构 (用于前端通信)
#[derive(Debug, Clone, serde::Serialize)]
struct RunProgress {
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

// 运行控制器
#[derive(Default)]
struct RunController {
    active: AtomicBool,
    cancel_requested: AtomicBool,
    session_label: Mutex<Option<String>>,
    runner_state: Mutex<Option<Arc<RunnerState>>>,
}

impl RunController {
    fn is_active(&self) -> bool {
        self.active.load(Ordering::Relaxed)
    }

    fn set_active(&self, active: bool) {
        self.active.store(active, Ordering::Relaxed);
    }

    fn request_cancel(&self) {
        self.cancel_requested.store(true, Ordering::Relaxed);
        if let Ok(state) = self.runner_state.lock() {
            if let Some(ref state) = *state {
                state.request_cancel();
            }
        }
    }

    fn is_cancelled(&self) -> bool {
        self.cancel_requested.load(Ordering::Relaxed)
    }

    fn clear_cancel(&self) {
        self.cancel_requested.store(false, Ordering::Relaxed);
    }

    fn set_session_label(&self, label: String) {
        if let Ok(mut l) = self.session_label.lock() {
            *l = Some(label);
        }
    }

    fn get_session_label(&self) -> Option<String> {
        self.session_label.lock().ok().and_then(|l| l.clone())
    }

    fn set_runner_state(&self, state: Arc<RunnerState>) {
        if let Ok(mut s) = self.runner_state.lock() {
            *s = Some(state);
        }
    }

    fn clear_runner_state(&self) {
        if let Ok(mut s) = self.runner_state.lock() {
            *s = None;
        }
    }

    fn clear_session_label(&self) {
        if let Ok(mut l) = self.session_label.lock() {
            *l = None;
        }
    }
}

// Health check
#[tauri::command]
fn app_health() -> String {
    "arena-app-shell-ready".to_string()
}

// List datasets
#[tauri::command]
fn list_datasets() -> Result<Vec<DatasetInfo>, String> {
    arena::list_datasets()
}

// Get dataset
#[tauri::command]
fn get_dataset(name: String) -> Result<DatasetDetail, String> {
    arena::get_dataset(&name)
}

// Load targets
#[tauri::command]
fn load_targets() -> Result<Vec<String>, String> {
    config::load_targets()
}

// Save targets
#[tauri::command]
fn save_targets(targets: Vec<String>) -> Result<(), String> {
    config::save_targets(&targets)
}

// List runs
#[tauri::command]
fn list_runs() -> Result<Vec<serde_json::Value>, String> {
    arena::list_runs()
}

// Get run detail
#[tauri::command]
fn get_run_detail(id: String) -> Result<serde_json::Value, String> {
    arena::get_run_detail(&id)
}

// Start run
#[tauri::command]
fn start_run(
    window: Window,
    run_controller: State<'_, Arc<RunController>>,
    dataset: String,
    targets: Vec<String>,
    repeat: usize,
) -> Result<String, String> {
    if run_controller.is_active() {
        return Err(format!(
            "Another run is already active: {}",
            run_controller
                .get_session_label()
                .unwrap_or_else(|| "current run".to_string())
        ));
    }

    if targets.is_empty() {
        return Err("No targets selected".to_string());
    }

    // 限制 repeat 参数范围，防止滥用
    const MAX_REPEAT: usize = 10;
    const MIN_REPEAT: usize = 1;
    let repeat_clamped = repeat.clamp(MIN_REPEAT, MAX_REPEAT);
    if repeat != repeat_clamped {
        eprintln!(
            "[WARN] repeat value {} clamped to {}",
            repeat, repeat_clamped
        );
    }

    // Parse targets
    let target_configs: Vec<models::TargetConfig> = targets
        .iter()
        .map(|t| models::TargetConfig::from_spec(t))
        .collect::<Result<Vec<_>, _>>()?;

    let repeat_safe = repeat_clamped;
    let session_label = format!(
        "{} [{} target(s), repeat {}]",
        dataset,
        targets.len(),
        repeat_safe
    );

    eprintln!("[START_RUN] dataset={}, targets={}, repeat={}", dataset, targets.len(), repeat_safe);
    run_controller.set_active(true);
    run_controller.clear_cancel();
    run_controller.set_session_label(session_label.clone());

    // Get dataset - 如果失败需要重置控制器状态
    let dataset_detail = match get_dataset(dataset.clone()) {
        Ok(d) => d,
        Err(e) => {
            run_controller.set_active(false);
            run_controller.clear_cancel();
            run_controller.clear_runner_state();
            run_controller.clear_session_label();
            return Err(e);
        }
    };

    if dataset_detail.items.is_empty() {
        run_controller.set_active(false);
        run_controller.clear_cancel();
        run_controller.clear_runner_state();
        run_controller.clear_session_label();
        return Err(format!("Dataset '{}' has no items to score", dataset));
    }

    // Create runner state
    let runner_state = Arc::new(RunnerState::new());
    run_controller.set_runner_state(runner_state.clone());

    // Spawn async task in a dedicated thread with its own Tokio runtime
    // 注意：使用 thread::spawn 而不是 tauri::async_runtime::spawn，因为 run_benchmark 使用了非 Send 类型
    let worker_window = window.clone();
    let controller = Arc::clone(&run_controller);
    let target_configs_clone = target_configs.clone();
    let dataset_detail_clone = dataset_detail.clone();

    thread::spawn(move || {
        eprintln!("[RUNNER] Thread started for dataset={}", dataset_detail.dataset);
        let runtime = tokio::runtime::Runtime::new().expect("Failed to create Tokio runtime");

        let result = runtime.block_on(async {
            let progress_callback = |event: models::ProgressEvent| {
                let progress = RunProgress {
                    phase: event.phase.clone(),
                    current: event.current,
                    total: event.total,
                    percent: event.percent,
                    message: event.message.clone(),
                    target: event.target.clone(),
                    mode: event.mode,
                    done: event.done,
                    error: event.error,
                };

                if let Err(e) = worker_window.emit("run-progress", &progress) {
                    eprintln!("[EMIT FAIL] run-progress: {}", e);
                }

                // 只发送关键阶段的日志，避免控制台过于冗长
                let important_phases = [
                    "prepare", "target", "batch_done", "finalize", "done",
                    "rate_limit", "api_error", "fallback", "complete", "cancelled", "error"
                ];
                if important_phases.iter().any(|p| event.phase.contains(p)) || event.done || event.error {
                    let log_msg = format!("[{}] {}", event.phase, event.message);
                    eprintln!("[RUNNER LOG] {}", log_msg);
                    if let Err(e) = worker_window.emit("run-log", &log_msg) {
                        eprintln!("[EMIT FAIL] run-log: {}", e);
                    }
                }
            };

            eprintln!("[RUNNER] Calling run_benchmark...");
            let bench_result = run_benchmark(
                &dataset_detail_clone,
                &target_configs_clone,
                repeat_safe,
                runner_state.clone(),
                progress_callback,
            )
            .await;
            eprintln!("[RUNNER] run_benchmark returned: {:?}", bench_result.as_ref().map(|ids| ids.len()));
            bench_result
        });

        eprintln!("[RUNNER] Processing result...");
        match result {
            Ok(run_ids) => {
                let msg = format!("[SUCCESS] Run completed. Created: {}", run_ids.join(", "));
                eprintln!("[RUNNER] {}", msg);
                let _ = worker_window.emit("run-log", &msg);
                let _ = worker_window.emit("run-log", "[DONE] Task sequence completed.");
                let _ = worker_window.emit(
                    "run-progress",
                    RunProgress {
                        phase: "complete".to_string(),
                        current: 0,
                        total: 0,
                        percent: 100.0,
                        message: "Run completed successfully".to_string(),
                        target: None,
                        mode: "idle".to_string(),
                        done: true,
                        error: false,
                    },
                );
            }
            Err(e) => {
                let is_cancelled = controller.is_cancelled();
                if is_cancelled {
                    eprintln!("[RUNNER] Run cancelled by user");
                    let _ = worker_window.emit("run-log", "[DONE] Run cancelled by user.");
                } else {
                    eprintln!("[RUNNER] ERROR: {}", e);
                    let _ = worker_window.emit("run-log", format!("[ERROR] {}", e));
                }
                let _ = worker_window.emit(
                    "run-progress",
                    RunProgress {
                        phase: if is_cancelled { "cancelled" } else { "error" }.to_string(),
                        current: 0,
                        total: 0,
                        percent: 0.0,
                        message: if is_cancelled {
                            "Run cancelled by user".to_string()
                        } else {
                            e.to_string()
                        },
                        target: None,
                        mode: "idle".to_string(),
                        done: true,
                        error: !is_cancelled,
                    },
                );
            }
        }

        eprintln!("[RUNNER] Cleaning up controller state");
        controller.set_active(false);
        controller.clear_cancel();
        controller.clear_runner_state();
        controller.clear_session_label();
    });

    Ok(format!("Started run for {}", session_label))
}

// Stop run
#[tauri::command]
fn stop_run(
    window: Window,
    run_controller: State<'_, Arc<RunController>>,
) -> Result<String, String> {
    if !run_controller.is_active() {
        return Err("No run is currently active".to_string());
    }

    let label = run_controller
        .get_session_label()
        .unwrap_or_else(|| "current run".to_string());

    run_controller.request_cancel();

    let _ = window.emit("run-log", format!("[INFO] Stop requested for {}", label));
    Ok(format!("Stop requested for {}", label))
}

fn main() {
    tauri::Builder::default()
        .manage(Arc::new(RunController::default()))
        .invoke_handler(tauri::generate_handler![
            app_health,
            list_datasets,
            get_dataset,
            load_targets,
            save_targets,
            start_run,
            stop_run,
            list_runs,
            get_run_detail,
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
