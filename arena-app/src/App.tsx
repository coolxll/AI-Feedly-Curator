import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Lang, t } from "./i18n";

interface DatasetInfo {
  name: string;
  version: string;
  created_at: string;
  description: string;
  item_count: number;
}

interface DatasetItem {
  id: string;
  title: string;
  origin: string;
  link: string;
  published: number;
  summary_excerpt: string;
  category: string;
  expected_band: string;
}

interface DatasetDetail {
  dataset: string;
  version: string;
  created_at: string;
  description: string;
  source_files: string[];
  items: DatasetItem[];
}

interface RunSummary {
  id: string;
  dataset: string;
  target: string;
  timestamp: string;
  metrics: {
    average_spread: number;
    max_spread: number;
    high_score_rate: number;
    negative_signal_presence_rate: number;
    cheap_vs_sota_gap: number;
  };
}

interface RunDetail extends RunSummary {
  results: Array<{
    item_id: string;
    title: string;
    score: number;
    spread: number;
    reason: string;
  }>;
}

export function App() {
  const [lang, setLang] = useState<Lang>(() => {
    const saved = localStorage.getItem("arena-lang");
    return (saved === "en" || saved === "zh") ? saved : "zh";
  });
  const [activeNav, setActiveNav] = useState("Datasets");
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [targets, setTargets] = useState<string[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<DatasetDetail | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);

  // Run Configuration State
  const [runDataset, setRunDataset] = useState("");
  const [runTargets, setRunTargets] = useState<string[]>([]);

  useEffect(() => {
    localStorage.setItem("arena-lang", lang);
  }, [lang]);

  useEffect(() => {
    loadDatasets();
    loadTargets();
    loadRuns();
  }, []);

  async function loadDatasets() {
    try {
      setLoading(true);
      const result = await invoke<DatasetInfo[]>("list_datasets");
      setDatasets(result);
      if (result.length > 0) setRunDataset(result[0].name);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadTargets() {
    try {
      const result = await invoke<string[]>("load_targets");
      setTargets(result);
      setRunTargets(result);
    } catch (e) {
      console.error(e);
    }
  }

  async function loadRuns() {
    try {
      const result = await invoke<RunSummary[]>("list_runs");
      setRuns(result);
    } catch (e) {
      console.error(e);
    }
  }

  async function saveTargets(newTargets: string[]) {
    try {
      await invoke("save_targets", { targets: newTargets });
      setTargets(newTargets);
    } catch (e) {
      setError(String(e));
    }
  }

  async function startRun() {
    if (!runDataset || runTargets.length === 0) return;
    try {
      setRunMsg(null);
      const msg = await invoke<string>("start_run", { dataset: runDataset, targets: runTargets });
      setRunMsg(msg);
      loadRuns(); // Refresh runs list
      setTimeout(() => setRunMsg(null), 3000);
    } catch (e) {
      setError(String(e));
    }
  }

  async function viewDataset(name: string) {
    try {
      const result = await invoke<DatasetDetail>("get_dataset", { name });
      setSelectedDataset(result);
    } catch (e) {
      setError(String(e));
    }
  }

  async function viewRun(id: string) {
    try {
      const result = await invoke<RunDetail>("get_run_detail", { id });
      setSelectedRun(result);
    } catch (e) {
      setError(String(e));
    }
  }

  const navItems = [
    { key: "Datasets", label: t(lang, "navDatasets") },
    { key: "Runs", label: t(lang, "navRuns") },
    { key: "Compare", label: t(lang, "navCompare") },
    { key: "Targets", label: t(lang, "navTargets") },
  ];

  const metrics = [
    { key: "metricAvgSpread", label: t(lang, "metricAvgSpread") },
    { key: "metricMaxSpread", label: t(lang, "metricMaxSpread") },
    { key: "metricHighScore", label: t(lang, "metricHighScore") },
    { key: "metricNegSignal", label: t(lang, "metricNegSignal") },
    { key: "metricCheapGap", label: t(lang, "metricCheapGap") },
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-content">
          <div>
            <p className="eyebrow">{t(lang, "arena")}</p>
            <h1>{t(lang, "title")}</h1>
            <p className="muted">{t(lang, "subtitle")}</p>
          </div>
          <nav className="nav">
            {navItems.map((item) => (
              <button
                key={item.key}
                className={item.key === activeNav ? "nav-item active" : "nav-item"}
                onClick={() => {
                  setActiveNav(item.key);
                  setSelectedDataset(null);
                  setSelectedRun(null);
                }}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
        
        <div className="sidebar-footer">
          <div className="status-item">
            <span className="status-dot" style={{ backgroundColor: error ? "#ef4444" : "#245b4b", boxShadow: error ? "0 0 0 6px rgba(239, 68, 68, 0.12)" : "0 0 0 6px rgba(36, 91, 75, 0.12)" }} />
            <span className="muted" style={{ fontSize: "12px", marginLeft: "8px" }}>
              {loading ? "..." : error ? "Error" : "Ready"}
            </span>
          </div>
          <button
            className="lang-toggle"
            onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            title={lang === "zh" ? "Switch to English" : "切换到中文"}
          >
            {lang === "zh" ? "EN" : "中"}
          </button>
        </div>
      </aside>

      <main className="content">
        {selectedRun ? (
          <section className="run-detail-view">
             <div className="back-link" onClick={() => setSelectedRun(null)}>
               ← {t(lang, "backToList")}
             </div>
             <div className="section-head">
               <div>
                 <p className="eyebrow">{t(lang, "runDetail")} · {selectedRun.id}</p>
                 <h2>{selectedRun.target}</h2>
                 <p className="muted">{selectedRun.dataset} · {new Date(selectedRun.timestamp).toLocaleString()}</p>
               </div>
             </div>

             <article className="card">
                <p className="eyebrow" style={{ marginBottom: "1rem" }}>{t(lang, "metricsTitle")}</p>
                <div className="metrics-grid">
                  <div className="metric-card">
                    <span className="label">{t(lang, "avgSpread")}</span>
                    <span className="value">{selectedRun.metrics.average_spread.toFixed(2)}</span>
                  </div>
                  <div className="metric-card">
                    <span className="label">{t(lang, "maxSpread")}</span>
                    <span className="value">{selectedRun.metrics.max_spread.toFixed(1)}</span>
                  </div>
                  <div className="metric-card">
                    <span className="label">{t(lang, "highScoreRate")}</span>
                    <span className="value">{(selectedRun.metrics.high_score_rate * 100).toFixed(0)}%</span>
                  </div>
                  <div className="metric-card">
                    <span className="label">{t(lang, "negSignal")}</span>
                    <span className="value">{(selectedRun.metrics.negative_signal_presence_rate * 100).toFixed(0)}%</span>
                  </div>
                  <div className="metric-card">
                    <span className="label">{t(lang, "gap")}</span>
                    <span className="value">{selectedRun.metrics.cheap_vs_sota_gap.toFixed(2)}</span>
                  </div>
                </div>
             </article>

             <article className="results-table-container">
               <table className="results-table">
                 <thead>
                   <tr>
                     <th style={{ width: "60px" }}>ID</th>
                     <th>{t(lang, "colTitle")}</th>
                     <th style={{ width: "80px" }}>{t(lang, "colScore")}</th>
                     <th style={{ width: "80px" }}>{t(lang, "colSpread")}</th>
                     <th>{t(lang, "colReason")}</th>
                   </tr>
                 </thead>
                 <tbody>
                   {selectedRun.results.map((res) => (
                     <tr key={res.item_id}>
                       <td>{res.item_id}</td>
                       <td>{res.title}</td>
                       <td>
                        <span className="score-pill">{res.score}</span>
                       </td>
                       <td>
                        <span className="spread-val">+{res.spread.toFixed(1)}</span>
                       </td>
                       <td className="reason">{res.reason}</td>
                     </tr>
                   ))}
                 </tbody>
               </table>
             </article>
          </section>
        ) : selectedDataset ? (
          <section className="card">
            <div className="section-head">
              <div>
                <p className="eyebrow">{t(lang, "datasetsTag")}</p>
                <h2>{selectedDataset.dataset}</h2>
              </div>
              <button className="secondary" onClick={() => setSelectedDataset(null)}>
                {t(lang, "backToList")}
              </button>
            </div>
            <p className="muted">{selectedDataset.description}</p>
            <p className="meta" style={{ marginBottom: "1rem" }}>
              {t(lang, "items", { count: selectedDataset.items.length })} · {selectedDataset.version} · {selectedDataset.created_at}
            </p>
            <div className="stack">
              {selectedDataset.items.map((item: DatasetItem) => (
                <div key={item.id} className="list-row">
                  <div style={{ flex: 1 }}>
                    <strong>{item.title}</strong>
                    <p style={{ color: "#64748b", fontSize: "0.875rem" }}>
                      {item.origin} · {item.category} · {t(lang, "expected")}: {item.expected_band}
                    </p>
                    {item.summary_excerpt && (
                      <p style={{ color: "#94a3b8", fontSize: "0.8rem", marginTop: "0.25rem" }}>
                        {item.summary_excerpt.slice(0, 150)}...
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : activeNav === "Targets" ? (
          <section className="card">
            <div className="section-head">
              <div>
                <p className="eyebrow">{t(lang, "navTargets")}</p>
                <h2>{t(lang, "targetsTitle")}</h2>
              </div>
              <div style={{ display: "flex", gap: "10px" }}>
                <button className="secondary" onClick={() => {
                  const newTargets = [...targets, "name|model|url|key"];
                  setTargets(newTargets);
                }}>{t(lang, "addTarget")}</button>
                <button className="primary" onClick={() => saveTargets(targets)}>{t(lang, "saveTargets")}</button>
              </div>
            </div>
            <div className="stack">
              {targets.map((target, idx) => {
                const parts = target.split("|");
                return (
                  <div key={idx} className="target-row">
                    <input 
                      className="target-input" 
                      placeholder={t(lang, "targetName")}
                      value={parts[0] || ""} 
                      onChange={(e) => {
                        const next = [...targets];
                        parts[0] = e.target.value;
                        next[idx] = parts.join("|");
                        setTargets(next);
                      }}
                    />
                    <input 
                      className="target-input" 
                      placeholder={t(lang, "targetModel")}
                      value={parts[1] || ""} 
                      onChange={(e) => {
                        const next = [...targets];
                        parts[1] = e.target.value;
                        next[idx] = parts.join("|");
                        setTargets(next);
                      }}
                    />
                    <input 
                      className="target-input" 
                      placeholder={t(lang, "targetBaseUrl")}
                      value={parts[2] || ""} 
                      onChange={(e) => {
                        const next = [...targets];
                        parts[2] = e.target.value;
                        next[idx] = parts.join("|");
                        setTargets(next);
                      }}
                    />
                    <input 
                      className="target-input" 
                      placeholder={t(lang, "targetEnvKey")}
                      value={parts[3] || ""} 
                      onChange={(e) => {
                        const next = [...targets];
                        parts[3] = e.target.value;
                        next[idx] = parts.join("|");
                        setTargets(next);
                      }}
                    />
                    <button className="btn-icon" onClick={() => {
                      const next = targets.filter((_, i) => i !== idx);
                      setTargets(next);
                    }}>×</button>
                  </div>
                )
              })}
            </div>
          </section>
        ) : (
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
                      <select value={runDataset} onChange={(e) => setRunDataset(e.target.value)}>
                        {datasets.map(ds => <option key={ds.name} value={ds.name}>{ds.name}</option>)}
                      </select>
                    </div>
                    <div className="run-selector">
                      <label className="eyebrow" style={{ color: "var(--muted)" }}>{t(lang, "navTargets")}</label>
                      <div className="checkbox-group">
                        {targets.map(t_str => {
                          const name = t_str.split("|")[0];
                          const isChecked = runTargets.includes(t_str);
                          return (
                            <div 
                              key={t_str} 
                              className={isChecked ? "checkbox-item checked" : "checkbox-item"}
                              onClick={() => {
                                if (isChecked) setRunTargets(runTargets.filter(x => x !== t_str));
                                else setRunTargets([...runTargets, t_str]);
                              }}
                            >
                              {name}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "20px", marginTop: "10px" }}>
                    <button className="primary" onClick={startRun} disabled={!runDataset || runTargets.length === 0}>
                      {t(lang, "btnCreateRun")}
                    </button>
                    {runMsg && <span style={{ color: "var(--brand)", fontSize: "0.875rem" }}>{runMsg}</span>}
                  </div>
                </div>
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
                        onClick={() => viewDataset(ds.name)}
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
              </article>
            </section>
            
            <section className="card" style={{ display: activeNav === "Runs" ? "block" : "none" }}>
              <div className="section-head">
                <div>
                  <p className="eyebrow">{t(lang, "runsTag")}</p>
                  <h3>{t(lang, "runsTitle")}</h3>
                </div>
              </div>
              <div className="stack">
                {runs.length === 0 ? (
                  <p className="muted">{t(lang, "noRuns")}</p>
                ) : (
                  runs.map((run) => (
                    <div key={run.id} className="run-item" onClick={() => viewRun(run.id)}>
                      <div className="info">
                        <strong>{run.target.split("|")[0]}</strong>
                        <p className="muted" style={{ fontSize: "13px" }}>{run.dataset}</p>
                        <span className="timestamp">{new Date(run.timestamp).toLocaleString()}</span>
                      </div>
                      <div className="meta" style={{ textAlign: "right" }}>
                        <div style={{ fontWeight: 600, color: "var(--accent)" }}>
                          {run.metrics.average_spread.toFixed(2)}
                        </div>
                        <div style={{ fontSize: "11px", textTransform: "uppercase" }}>{t(lang, "avgSpread")}</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
