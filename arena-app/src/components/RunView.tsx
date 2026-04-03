import { RunDetail } from "./types";
import { Lang, t } from "../i18n";
import { getTargetLabel, averageScore } from "./utils";

interface RunViewProps {
  run: RunDetail;
  lang: Lang;
  onBack: () => void;
}

export function RunView({ run, lang, onBack }: RunViewProps) {
  return (
    <section className="run-detail-view">
      <div className="back-link" onClick={onBack}>
        ← {t(lang, "backToList")}
      </div>
      <div className="section-head">
        <div>
          <p className="eyebrow">{t(lang, "runDetail")} · {run.id}</p>
          <h2>{getTargetLabel(run.target)}</h2>
          <p className="muted">{run.dataset} · {new Date(run.timestamp).toLocaleString()}</p>
        </div>
      </div>

      <article className="card">
        <p className="eyebrow" style={{ marginBottom: "1rem" }}>{t(lang, "metricsTitle")}</p>
        <div className="metrics-grid">
          <div className="metric-card">
            <span className="label">{t(lang, "compareAverageScore")}</span>
            <span className="value">{averageScore(run.results).toFixed(2)}</span>
          </div>
          <div className="metric-card">
            <span className="label">{t(lang, "avgSpread")}</span>
            <span className="value">{run.metrics.average_spread.toFixed(2)}</span>
          </div>
          <div className="metric-card">
            <span className="label">{t(lang, "maxSpread")}</span>
            <span className="value">{run.metrics.max_spread.toFixed(2)}</span>
          </div>
          <div className="metric-card">
            <span className="label">{t(lang, "highScoreRate")}</span>
            <span className="value">{(run.metrics.high_score_rate * 100).toFixed(0)}%</span>
          </div>
          <div className="metric-card">
            <span className="label">{t(lang, "negSignal")}</span>
            <span className="value">{(run.metrics.negative_signal_presence_rate * 100).toFixed(0)}%</span>
          </div>
          <div className="metric-card">
            <span className="label">{t(lang, "gap")}</span>
            <span className="value">{run.metrics.cheap_vs_sota_gap.toFixed(2)}</span>
          </div>
        </div>
      </article>

      <article className="results-table-container">
        <table className="results-table">
          <thead>
            <tr>
              <th style={{ width: "60px" }}>ID</th>
              <th>{t(lang, "colTitle")}</th>
              <th style={{ width: "100px" }}>{t(lang, "colScore")}</th>
              <th style={{ width: "90px" }}>{t(lang, "colSpread")}</th>
              <th>{t(lang, "colReason")}</th>
            </tr>
          </thead>
          <tbody>
            {run.results.map((res) => (
              <tr key={res.item_id}>
                <td>{res.item_id}</td>
                <td>{res.title}</td>
                <td>
                  <span className="score-pill">{res.score.toFixed(1)}</span>
                </td>
                <td>
                  <span className="spread-val">{res.spread.toFixed(2)}</span>
                </td>
                <td className="reason">{res.reason || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </section>
  );
}
