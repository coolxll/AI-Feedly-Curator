import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Lang, t } from "./i18n";
import {
  DatasetInfo,
  DatasetDetail,
  RunSummary,
  RunDetail,
  RunProgress,
} from "./components/types";
import {
  DatasetView,
  RunView,
  TargetsEditor,
  CompareView,
  RunDashboard,
} from "./components";

export function App() {
  const [lang, setLang] = useState<Lang>(() => {
    const saved = localStorage.getItem("arena-lang");
    return saved === "en" || saved === "zh" ? saved : "zh";
  });
  const [activeNav, setActiveNav] = useState("Datasets");
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [targets, setTargets] = useState<string[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<DatasetDetail | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [selectedCompareRunIds, setSelectedCompareRunIds] = useState<string[]>([]);
  const [compareRuns, setCompareRuns] = useState<RunDetail[]>([]);
  const [compareLoading, setCompareLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [runProgress, setRunProgress] = useState<RunProgress | null>(null);

  const [runDataset, setRunDataset] = useState("");
  const [runTargets, setRunTargets] = useState<string[]>([]);
  const [runRepeat, setRunRepeat] = useState(1);
  const [logs, setLogs] = useState<string[]>([]);

  useEffect(() => {
    localStorage.setItem("arena-lang", lang);
  }, [lang]);

  useEffect(() => {
    const unlistenLog = listen<string>("run-log", (event) => {
      setLogs((prev) => [...prev, event.payload]);
    });
    const unlistenProgress = listen<RunProgress>("run-progress", (event) => {
      setRunProgress(event.payload);
      if (event.payload.done || event.payload.error) {
        setIsRunning(false);
        void loadRuns();
      }
    });
    return () => {
      unlistenLog.then((f) => f());
      unlistenProgress.then((f) => f());
    };
  }, []);

  useEffect(() => {
    loadDatasets();
    loadTargets();
    loadRuns();
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadCompareRuns() {
      if (selectedCompareRunIds.length < 2) {
        setCompareRuns([]);
        setCompareLoading(false);
        return;
      }
      try {
        setCompareLoading(true);
        const result = await Promise.all(
          selectedCompareRunIds.map((id) => invoke<RunDetail>("get_run_detail", { id })),
        );
        if (!cancelled) {
          setCompareRuns(result);
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e));
        }
      } finally {
        if (!cancelled) {
          setCompareLoading(false);
        }
      }
    }

    void loadCompareRuns();
    return () => {
      cancelled = true;
    };
  }, [selectedCompareRunIds]);

  async function loadDatasets() {
    try {
      setLoading(true);
      const result = await invoke<DatasetInfo[]>("list_datasets");
      setDatasets(result);
      if (result.length > 0) setRunDataset((current) => current || result[0].name);
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
      if (import.meta.env.DEV) {
        console.error("Failed to load targets:", e);
      }
    }
  }

  async function loadRuns() {
    try {
      const result = await invoke<RunSummary[]>("list_runs");
      setRuns(result);
    } catch (e) {
      if (import.meta.env.DEV) {
        console.error("Failed to load runs:", e);
      }
    }
  }

  async function saveTargets(newTargets: string[]) {
    try {
      await invoke("save_targets", { targets: newTargets });
      setTargets(newTargets);
      setRunTargets((current) => current.filter((target) => newTargets.includes(target)));
    } catch (e) {
      setError(String(e));
    }
  }

  async function startRun() {
    if (!runDataset || runTargets.length === 0 || isRunning) return;
    try {
      setError(null);
      setRunMsg(null);
      setIsRunning(true);
      setLogs([`[INFO] Queueing real benchmark for dataset ${runDataset}`]);
      setRunProgress({
        phase: "queued",
        current: 0,
        total: 1,
        percent: 0,
        message: `Queueing real benchmark for dataset ${runDataset} (repeat ${runRepeat})`,
        mode: "real",
        done: false,
        error: false,
      });
      const msg = await invoke<string>("start_run", { dataset: runDataset, targets: runTargets, repeat: runRepeat });
      setRunMsg(msg);
      setTimeout(() => setRunMsg(null), 4000);
    } catch (e) {
      setIsRunning(false);
      setError(String(e));
    }
  }

  async function stopRun() {
    if (!isRunning) return;
    try {
      const msg = await invoke<string>("stop_run");
      setRunMsg(msg);
      setRunProgress((current) => current ? {
        ...current,
        phase: "stopping",
        message: msg,
      } : {
        phase: "stopping",
        current: 0,
        total: 1,
        percent: 0,
        message: msg,
        mode: "real",
        done: false,
        error: false,
      });
      setTimeout(() => setRunMsg(null), 4000);
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

  function toggleCompareRun(id: string) {
    setSelectedCompareRunIds((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  function openCompare() {
    setActiveNav("Compare");
    setSelectedDataset(null);
    setSelectedRun(null);
  }

  const navItems = [
    { key: "Datasets", label: t(lang, "navDatasets") },
    { key: "Runs", label: t(lang, "navRuns") },
    { key: "Compare", label: t(lang, "navCompare") },
    { key: "Targets", label: t(lang, "navTargets") },
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
              {loading ? "..." : error ? "Error" : isRunning ? t(lang, "progressRunning") : "Ready"}
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
          <RunView run={selectedRun} lang={lang} onBack={() => setSelectedRun(null)} />
        ) : selectedDataset ? (
          <DatasetView dataset={selectedDataset} lang={lang} onBack={() => setSelectedDataset(null)} />
        ) : activeNav === "Targets" ? (
          <TargetsEditor
            targets={targets}
            lang={lang}
            onChange={setTargets}
            onSave={saveTargets}
          />
        ) : activeNav === "Compare" ? (
          <CompareView
            runs={runs}
            compareRuns={compareRuns}
            selectedIds={selectedCompareRunIds}
            compareLoading={compareLoading}
            lang={lang}
            onToggleRun={toggleCompareRun}
          />
        ) : (
          <RunDashboard
            datasets={datasets}
            targets={targets}
            runs={runs}
            runDataset={runDataset}
            runTargets={runTargets}
            runRepeat={runRepeat}
            isRunning={isRunning}
            runProgress={runProgress}
            runMsg={runMsg}
            logs={logs}
            loading={loading}
            error={error}
            selectedCompareRunIds={selectedCompareRunIds}
            lang={lang}
            onRunDatasetChange={setRunDataset}
            onRunTargetsChange={setRunTargets}
            onRunRepeatChange={setRunRepeat}
            onStartRun={startRun}
            onStopRun={stopRun}
            onClearLogs={() => setLogs([])}
            onViewDataset={viewDataset}
            onViewRun={viewRun}
            onToggleCompareRun={toggleCompareRun}
            onOpenCompare={openCompare}
          />
        )}
      </main>
    </div>
  );
}
