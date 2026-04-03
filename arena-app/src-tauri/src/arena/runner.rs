use crate::arena::report::{aggregate_repeat_reports, build_comparison, build_report, build_run_record};
use crate::config::{get_runs_dir, AppConfig};
use crate::models::{Article, DatasetDetail, ProgressEvent, RunPhase, TargetConfig};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// 运行器状态
pub struct RunnerState {
    cancel_requested: AtomicBool,
    current_phase: std::sync::Mutex<RunPhase>,
    progress: std::sync::Mutex<(usize, usize)>, // (current, total)
}

impl RunnerState {
    pub fn new() -> Self {
        Self {
            cancel_requested: AtomicBool::new(false),
            current_phase: std::sync::Mutex::new(RunPhase::Prepare),
            progress: std::sync::Mutex::new((0, 0)),
        }
    }

    pub fn request_cancel(&self) {
        self.cancel_requested.store(true, Ordering::Relaxed);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancel_requested.load(Ordering::Relaxed)
    }

    pub fn set_phase(&self, phase: RunPhase) {
        if let Ok(mut p) = self.current_phase.lock() {
            *p = phase;
        }
    }

    pub fn set_progress(&self, current: usize, total: usize) {
        if let Ok(mut p) = self.progress.lock() {
            *p = (current, total);
        }
    }
}

impl Default for RunnerState {
    fn default() -> Self {
        Self::new()
    }
}

/// 运行 benchmark
pub async fn run_benchmark<F>(
    dataset: &DatasetDetail,
    targets: &[TargetConfig],
    repeat: usize,
    state: Arc<RunnerState>,
    mut progress_callback: F,
) -> Result<Vec<String>, String>
where
    F: FnMut(ProgressEvent),
{
    let runs_dir = get_runs_dir()?;
    println!("[DEBUG] Runs directory: {:?}", runs_dir);
    std::fs::create_dir_all(&runs_dir)
        .map_err(|e| format!("Failed to create runs directory: {}", e))?;

    let timestamp = chrono::Local::now().format("%Y%m%d-%H%M%S").to_string();

    // 准备文章列表
    let articles: Vec<Article> = dataset
        .items
        .iter()
        .map(|item| Article::from_dataset_item(item))
        .collect();

    let item_count = articles.len();
    let total_targets = targets.len();
    let total_items = item_count * total_targets * repeat;

    if item_count == 0 || total_items == 0 {
        return Err("Selected dataset has no articles to score".to_string());
    }

    state.set_progress(0, total_items);

    // 准备阶段
    state.set_phase(RunPhase::Prepare);
    emit_progress(
        &mut progress_callback,
        "prepare",
        0,
        total_items,
        format!("Preparing benchmark for {} articles", item_count),
        None,
    );

    if state.is_cancelled() {
        return Err("Run cancelled".to_string());
    }

    let _config = AppConfig::default();
    let scorer = crate::scoring::Scorer::new();

    let mut all_reports = Vec::new();

    // 对每个 target 运行
    for (target_idx, target) in targets.iter().enumerate() {
        if state.is_cancelled() {
            return finalize_partial_runs(
                &runs_dir,
                &timestamp,
                dataset,
                targets,
                &all_reports,
            );
        }

        state.set_phase(RunPhase::TargetStart {
            label: target.label.clone(),
            index: target_idx,
        });

        // 只存储标签和环境变量名，绝不存储原始 API key
        let target_spec = format!(
            "{}|{}|{}|{}",
            target.label,
            target.model,
            target.base_url,
            target.api_key_env.as_deref().unwrap_or("(raw)")
        );

        // 重复运行
        let mut target_reports = Vec::new();

        for run_idx in 0..repeat {
            if state.is_cancelled() {
                return finalize_partial_runs(
                    &runs_dir,
                    &timestamp,
                    dataset,
                    targets,
                    &all_reports,
                );
            }

            let progress_base = target_idx * item_count * repeat + run_idx * item_count;

            emit_progress(
                &mut progress_callback,
                "target",
                progress_base,
                total_items,
                format!(
                    "Running target {}/{}: {} (run {}/{})",
                    target_idx + 1,
                    total_targets,
                    target.label,
                    run_idx + 1,
                    repeat
                ),
                Some(target.label.clone()),
            );

            // 批量评分
            let cancel_check = || state.is_cancelled();
            let progress_base_for_callback = progress_base;
            let total_items_for_callback = total_items;
            let target_label_for_callback = target.label.clone();
            let mut last_percent = -1.0f64; // 初始为 -1，确保第一个事件能触发

            let scoring_progress_callback = |event: ProgressEvent| {
                // 计算整体进度百分比
                let scoring_percent = event.percent / 100.0;
                let overall_percent = ((progress_base_for_callback as f64) / (total_items_for_callback as f64) * 100.0
                    + scoring_percent * (item_count as f64 / total_items_for_callback as f64) * 100.0)
                    .min(100.0);

                // 只在进度变化超过 1% 时发送更新，避免过于频繁
                // 或者 event.done 为 true 时也发送
                if (overall_percent - last_percent).abs() > 1.0 || event.done {
                    last_percent = overall_percent;

                    let current = ((overall_percent / 100.0) * total_items_for_callback as f64) as usize;
                    state.set_progress(current, total_items_for_callback);

                    emit_progress_with_percent(
                        &mut progress_callback,
                        &format!("scoring_{}", event.phase),
                        current,
                        total_items_for_callback,
                        overall_percent,
                        event.message,
                        Some(target_label_for_callback.clone()),
                    );
                }
            };

            match scorer
                .score_articles_batch(&articles, target, cancel_check, scoring_progress_callback)
                .await
            {
                Ok(results) => {
                    // 更新最终进度
                    let final_progress = progress_base + item_count;
                    state.set_progress(final_progress, total_items);

                    emit_progress(
                        &mut progress_callback,
                        "batch_done",
                        final_progress,
                        total_items,
                        format!("Scored {} items for {}", item_count, target.label),
                        Some(target.label.clone()),
                    );

                    let report = build_report(&results, &dataset.dataset, &target_spec);
                    target_reports.push(report);
                }
                Err(e) => {
                    return Err(format!(
                        "Scoring failed for target {} run {}: {}",
                        target.label,
                        run_idx + 1,
                        e
                    ));
                }
            }
        }

        // 聚合重复运行的报告
        let aggregated_report =
            aggregate_repeat_reports(&target_reports, &dataset.dataset, &target_spec);
        all_reports.push(aggregated_report);
    }

    if state.is_cancelled() {
        return finalize_partial_runs(&runs_dir, &timestamp, dataset, targets, &all_reports);
    }

    // 生成对比报告
    let comparison = if all_reports.len() > 1 {
        Some(build_comparison(&all_reports))
    } else {
        None
    };

    // 最终化阶段
    state.set_phase(RunPhase::Finalize);
    emit_progress_with_percent(
        &mut progress_callback,
        "finalize",
        total_items.saturating_sub(1),
        total_items,
        99.0,
        "Writing run records...".to_string(),
        None,
    );

    let created_run_ids = persist_reports(
        &runs_dir,
        &timestamp,
        dataset,
        targets,
        &all_reports,
        comparison.as_ref(),
    )?;

    // 完成
    state.set_phase(RunPhase::Done);
    emit_progress(
        &mut progress_callback,
        "done",
        total_items,
        total_items,
        format!("Created {} run record(s)", created_run_ids.len()),
        None,
    );

    Ok(created_run_ids)
}

fn finalize_partial_runs(
    runs_dir: &std::path::Path,
    timestamp: &str,
    dataset: &DatasetDetail,
    targets: &[TargetConfig],
    all_reports: &[crate::models::RunReport],
) -> Result<Vec<String>, String> {
    if all_reports.is_empty() {
        return Err("Run cancelled".to_string());
    }

    let comparison = if all_reports.len() > 1 {
        Some(build_comparison(all_reports))
    } else {
        None
    };

    let created_ids = persist_reports(
        runs_dir,
        timestamp,
        dataset,
        targets,
        all_reports,
        comparison.as_ref(),
    )?;

    Err(format!(
        "Run cancelled after saving {} partial run(s): {}",
        created_ids.len(),
        created_ids.join(", ")
    ))
}

fn persist_reports(
    runs_dir: &std::path::Path,
    timestamp: &str,
    dataset: &DatasetDetail,
    targets: &[TargetConfig],
    reports: &[crate::models::RunReport],
    comparison: Option<&crate::models::ComparisonResult>,
) -> Result<Vec<String>, String> {
    let mut created_run_ids = Vec::new();

    for (idx, report) in reports.iter().enumerate() {
        let target_spec = format!(
            "{}|{}|{}|{}",
            report.label,
            report.model,
            report.base_url,
            targets[idx].api_key_env.as_deref().unwrap_or("(raw)")
        );

        let run_id = if reports.len() == 1 {
            format!("run-{}", timestamp)
        } else {
            format!("run-{}-{}", timestamp, idx + 1)
        };

        let run_record =
            build_run_record(report, comparison, &dataset.dataset, &target_spec, &run_id);

        let run_json = serde_json::to_string_pretty(&run_record)
            .map_err(|e| format!("Failed to serialize run record: {}", e))?;

        std::fs::write(runs_dir.join(format!("{}.json", run_id)), run_json)
            .map_err(|e| format!("Failed to write run record: {}", e))?;

        created_run_ids.push(run_id);
    }

    Ok(created_run_ids)
}

fn emit_progress<F>(
    callback: &mut F,
    phase: &str,
    current: usize,
    total: usize,
    message: String,
    target: Option<String>,
) where
    F: FnMut(ProgressEvent),
{
    let safe_total = total.max(1);
    let percent = ((current as f64 / safe_total as f64) * 100.0).clamp(0.0, 100.0);

    emit_progress_with_percent(
        callback,
        phase,
        current,
        safe_total,
        percent,
        message,
        target,
    );
}

fn emit_progress_with_percent<F>(
    callback: &mut F,
    phase: &str,
    current: usize,
    total: usize,
    percent: f64,
    message: String,
    target: Option<String>,
) where
    F: FnMut(ProgressEvent),
{
    let safe_total = total.max(1);
    let safe_percent = percent.clamp(0.0, 100.0);

    callback(ProgressEvent {
        phase: phase.to_string(),
        current,
        total: safe_total,
        percent: safe_percent,
        message,
        target,
        mode: "real".to_string(),
        done: phase == "done",
        error: false,
    });
}
