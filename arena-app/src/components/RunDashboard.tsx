import { useRef } from "react";
import { DatasetInfo, RunSummary, RunProgress } from "./types";
import { Lang, t } from "../i18n";
import { getTargetLabel } from "./utils";

interface RunDashboardProps {
  datasets: DatasetInfo[];
  targets: string[];
  runs: RunSummary[];
  runDataset: string;
  runTargets: string[];
  runRepeat: number;
  isRunning: boolean;
  runProgress: RunProgress | null;
  runMsg: string | null;
  logs: string[];
  loading: boolean;
  error: string | null;
  selectedCompareRunIds: string[];
  lang: Lang;
  onRunDatasetChange: (dataset: string) => void;
  onRunTargetsChange: (targets: string[]) => void;
  onRunRepeatChange: (repeat: number) => void;
  onStartRun: () => void;
  onStopRun: () => void;
  onClearLogs: () => void;
  onViewDataset: (name: string) => void;
  onViewRun: (id: string) => void;
  onToggleCompareRun: (id: string) => void;
  onOpenCompare: () => void;
}

export function RunDashboard({
  datasets,
  targets,
  runs,
  runDataset,
  runTargets,
  runRepeat,
  isRunning,
  runProgress,
  runMsg,
  logs,
  loading,
  error,
  selectedCompareRunIds,
  lang,
  onRunDatasetChange,
  onRunTargetsChange,
  onRunRepeatChange,
  onStartRun,
  onStopRun,
  onClearLogs,
  onViewDataset,
  onViewRun,
  onToggleCompareRun,
  onOpenCompare,
}: RunDashboardProps) {
  const consoleRef = useRef<HTMLDivElement>(null);

  const rawProgressPercent = Math.max(0, Math.min(100, runProgress?.percent ?? 0));
  const progressPercent = rawProgressPercent > 0 && rawProgressPercent < 1
    ? rawProgressPercent.toFixed(1)
    : String(Math.round(rawProgressPercent));
  const progressStatus = runProgress?.phase === "stopping"
    ? t(lang, "progressStopping")
    : isRunning
      ? t(lang, "progressRunning")
      : t(lang, "progressFinished");

  const metrics = [
    { key: "metricAvgSpread", label: t(lang, "metricAvgSpread") },
    { key: "metricMaxSpread", label: t(lang, "metricMaxSpread") },
    { key: "metricHighScore", label: t(lang, "metricHighScore") },
    { key: "metricNegSignal", label: t(lang, "metricNegSignal") },
    { key: "metricCheapGap", label: t(lang, "metricCheapGap") },
  ];

  return (
    <>
      <section className="hero card">
        <div style={{ display: "flex", flex: 1, flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p className="eyebrow">{t(lang, "heroTag")}</p>
              <h2>{t(lang, "heroTitle")}</h2>
              <p style={{ marginTop: "8px" }}>{t(lang, "heroDesc")}</p>
            </div>
          </div>

          <div className="run-controls">
            <div className="grid two-up" style={{ gridTemplateColumns: "1fr 2fr" }}>
              <div className="run-selector">
                <label className="eyebrow" style={{ color: "var(--muted)" }}>{t(lang, "navDatasets")}</label>
                <select value={runDataset} onChange={(e) => onRunDatasetChange(e.target.value)} disabled={isRunning}>
                  {datasets.map((ds) => <option key={ds.name} value={ds.name}>{ds.name}</option>)}
                </select>
              </div>
              <div className="run-selector">
                <label className="eyebrow" style={{ color: "var(--muted)" }}>{t(lang, "navTargets")}</label>
                <div className="checkbox-group">
                  {targets.map((tStr) => {
                    const name = tStr.split("|")[0];
                    const isChecked = runTargets.includes(tStr);
                    return (
                      <div
                        key={tStr}
                        className={isChecked ? "checkbox-item checked" : "checkbox-item"}
                        onClick={() => {
                          if (isRunning) return;
                          if (isChecked) onRunTargetsChange(runTargets.filter((x) => x !== tStr));
                          else onRunTargetsChange([...runTargets, tStr]);
                        }}
                      >
                        {name}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="run-extras">
              <label className="run-repeat-control">
                <span className="eyebrow" style={{ color: "var(--muted)", marginBottom: 0 }}>{t(lang, "repeatLabel")}</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={runRepeat}
                  disabled={isRunning}
                  onChange={(e) => onRunRepeatChange(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                />
              </label>
              <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
                <button className="primary" onClick={onStartRun} disabled={!runDataset || runTargets.length === 0 || isRunning}>
                  {isRunning ? t(lang, "progressRunning") : t(lang, "btnCreateRun")}
                </button>
                <button
                  className="secondary"
                  onClick={onStopRun}
                  disabled={!isRunning || runProgress?.phase === "stopping"}
                >
                  {runProgress?.phase === "stopping" ? t(lang, "progressStopping") : t(lang, "btnStopRun")}
                </button>
                {runMsg && <span style={{ color: "var(--brand)", fontSize: "0.875rem" }}>{runMsg}</span>}
              </div>
            </div>
          </div>

          {(isRunning || runProgress) && (
            <div className="progress-card">
              <div className="progress-head">
                <div>
                  <p className="eyebrow">{t(lang, "progressTitle")}</p>
                  <h3>{runProgress?.message || t(lang, "progressQueued")}</h3>
                </div>
                <span className="pill">{runProgress?.mode === "real" ? t(lang, "progressModeReal") : runProgress?.mode || "-"}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${rawProgressPercent}%` }} />
              </div>
              <div className="progress-meta">
                <span>{progressStatus}</span>
                <span>{progressPercent}%</span>
                {runProgress?.target && <span>{runProgress.target}</span>}
              </div>
            </div>
          )}

          {(logs.length > 0 || isRunning) && (
            <div className="console-container">
              <div className="console-header">
                <h3>{t(lang, "consoleTitle")}</h3>
                <button className="btn-clear" onClick={onClearLogs}>{t(lang, "clearLogs")}</button>
              </div>
              <div className="console-body" ref={consoleRef}>
                {logs.map((log, i) => {
                  const type = log.startsWith("[SUCCESS]") ? "SUCCESS"
                    : log.startsWith("[ERROR]") ? "ERROR"
                    : log.startsWith("[ERR]") ? "ERROR"
                    : log.startsWith("[DEBUG]") ? "DEBUG"
                    : log.startsWith("[DONE]") ? "DONE"
                    : "INFO";
                  return (
                    <div key={i} className="log-line" data-type={type}>
                      {log}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="grid two-up">
        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">{t(lang, "datasetsTag")}</p>
              <h3>{t(lang, "datasetsTitle")}</h3>
            </div>
            <span className="pill">{t(lang, "datasetsLoaded", { count: datasets.length })}</span>
          </div>
          {loading ? (
            <p className="muted">{t(lang, "statusLoading")}</p>
          ) : error ? (
            <p className="muted" style={{ color: "#ef4444" }}>{error}</p>
          ) : (
            <div className="stack">
              {datasets.map((ds) => (
                <div
                  key={ds.name}
                  className="list-row clickable"
                  onClick={() => onViewDataset(ds.name)}
                  style={{ cursor: "pointer" }}
                >
                  <div>
                    <strong>{ds.name}</strong>
                    <p>{ds.description}</p>
                  </div>
                  <span className="meta">{t(lang, "items", { count: ds.item_count })}</span>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="card accent-card">
          <div className="section-head">
            <div>
              <p className="eyebrow">{t(lang, "compareTag")}</p>
              <h3>{t(lang, "compareTitle")}</h3>
            </div>
            <span className="pill">{t(lang, "metricsV1")}</span>
          </div>
          <ul className="metric-list">
            {metrics.map((m) => (
              <li key={m.key}>{m.label}</li>
            ))}
          </ul>
          <div style={{ marginTop: "16px" }}>
            <button className="secondary" onClick={onOpenCompare} disabled={selectedCompareRunIds.length < 2}>{t(lang, "compareOpen")}</button>
          </div>
        </article>
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <p className="eyebrow">{t(lang, "runsTag")}</p>
            <h3>{t(lang, "runsTitle")}</h3>
          </div>
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <span className="pill">{t(lang, "compareSelected", { count: selectedCompareRunIds.length })}</span>
            <button className="secondary" onClick={onOpenCompare} disabled={selectedCompareRunIds.length < 2}>{t(lang, "compareOpen")}</button>
          </div>
        </div>
        <div className="stack">
          {runs.length === 0 ? (
            <p className="muted">{t(lang, "noRuns")}</p>
          ) : (
            runs.map((run) => {
              const checked = selectedCompareRunIds.includes(run.id);
              return (
                <div key={run.id} className={checked ? "run-item selected" : "run-item"} onClick={() => onViewRun(run.id)}>
                  <div className="run-select-wrap" onClick={(event) => event.stopPropagation()}>
                    <label className="run-select">
                      <input type="checkbox" checked={checked} onChange={() => onToggleCompareRun(run.id)} />
                      <span>{t(lang, "compareSelectRun")}</span>
                    </label>
                  </div>
                  <div className="info">
                    <strong>{getTargetLabel(run.target)}</strong>
                    <p className="muted" style={{ fontSize: "13px" }}>{run.dataset}</p>
                    <span className="timestamp">{new Date(run.timestamp).toLocaleString()}</span>
                  </div>
                  <div className="meta run-item-metrics">
                    <div style={{ fontWeight: 600, color: "var(--accent)" }}>
                      -
                    </div>
                    <div style={{ fontSize: "11px", textTransform: "uppercase" }}>{t(lang, "compareAverageScore")}</div>
                    <div style={{ marginTop: "6px" }}>
                      {(run.metrics.negative_signal_presence_rate * 100).toFixed(0)}%
                    </div>
                    <div style={{ fontSize: "11px", textTransform: "uppercase" }}>{t(lang, "negSignal")}</div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </>
  );
}
