import { RunSummary, RunDetail, CompareRow, ModelGroupSummary } from "./types";
import { Lang, t } from "../i18n";
import { getTargetLabel, averageScore } from "./utils";

interface CompareViewProps {
  runs: RunSummary[];
  compareRuns: RunDetail[];
  selectedIds: string[];
  compareLoading: boolean;
  lang: Lang;
  onToggleRun: (id: string) => void;
}

export function CompareView({
  runs,
  compareRuns,
  selectedIds,
  compareLoading,
  lang,
  onToggleRun,
}: CompareViewProps) {
  const compareRows: CompareRow[] = [];
  const modelGroupSummaries: ModelGroupSummary[] = [];

  if (compareRuns.length >= 2) {
    // Build compare rows
    const rows = new Map<string, CompareRow>();
    for (const run of compareRuns) {
      for (const result of run.results) {
        const existing = rows.get(result.item_id) ?? {
          itemId: result.item_id,
          title: result.title,
          scores: {},
          reasonByRun: {},
          gap: 0,
        };
        existing.title = existing.title || result.title;
        existing.scores[run.id] = result.score;
        existing.reasonByRun[run.id] = result.reason;
        rows.set(result.item_id, existing);
      }
    }

    compareRows.push(...Array.from(rows.values())
      .map((row) => {
        const values = Object.values(row.scores).filter((value): value is number => typeof value === "number");
        const gap = values.length > 1 ? Math.max(...values) - Math.min(...values) : 0;
        return { ...row, gap };
      })
      .sort((a, b) => b.gap - a.gap || a.itemId.localeCompare(b.itemId)));

    // Build model group summaries
    const groups = new Map<string, RunDetail[]>();
    for (const run of compareRuns) {
      const key = getTargetLabel(run.target);
      const existing = groups.get(key) ?? [];
      existing.push(run);
      groups.set(key, existing);
    }

    modelGroupSummaries.push(...Array.from(groups.entries()).map(([key, groupedRuns]) => {
      const articleScores = new Map<string, number[]>();
      let high = 0;
      let mid = 0;
      let low = 0;
      let totalScore = 0;
      let totalCount = 0;
      let totalNegativeSignalRate = 0;

      for (const run of groupedRuns) {
        totalNegativeSignalRate += run.metrics.negative_signal_presence_rate;
        for (const result of run.results) {
          const scores = articleScores.get(result.item_id) ?? [];
          scores.push(result.score);
          articleScores.set(result.item_id, scores);
          totalScore += result.score;
          totalCount += 1;
          if (result.score >= 3.6) high += 1;
          else if (result.score >= 2.0) mid += 1;
          else low += 1;
        }
      }

      let spreadSum = 0;
      let spreadCount = 0;
      let maxSpread = 0;
      for (const scores of articleScores.values()) {
        if (scores.length < 2) {
          spreadCount += 1;
          continue;
        }
        const spread = Math.max(...scores) - Math.min(...scores);
        spreadSum += spread;
        spreadCount += 1;
        maxSpread = Math.max(maxSpread, spread);
      }

      return {
        key,
        label: key,
        runCount: groupedRuns.length,
        averageScore: totalCount === 0 ? 0 : totalScore / totalCount,
        negativeSignalRate: groupedRuns.length === 0 ? 0 : totalNegativeSignalRate / groupedRuns.length,
        averageSpread: spreadCount === 0 ? 0 : spreadSum / spreadCount,
        maxSpread,
        scoreBands: { high, mid, low },
      };
    }).sort((a, b) => a.label.localeCompare(b.label)));
  }

  const topGapRows = compareRows.slice(0, 8);

  return (
    <>
      <section className="card compare-header-card">
        <div className="section-head">
          <div>
            <p className="eyebrow">{t(lang, "compareTag")}</p>
            <h2>{t(lang, "compareWorkspace")}</h2>
            <p className="muted">{t(lang, "compareHint")}</p>
          </div>
          <span className="pill">{t(lang, "compareSelected", { count: selectedIds.length })}</span>
        </div>
        {selectedIds.length >= 2 ? (
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            {selectedIds.map((id) => {
              const run = runs.find((item) => item.id === id);
              return (
                <button key={id} className="secondary compare-chip" onClick={() => onToggleRun(id)}>
                  {run ? getTargetLabel(run.target) : id}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="muted">{t(lang, "compareNeedMore")}</p>
        )}
      </section>

      {compareLoading ? (
        <section className="card">
          <p className="muted">{t(lang, "compareLoading")}</p>
        </section>
      ) : compareRuns.length >= 2 ? (
        <>
          <section className="metrics-grid">
            {modelGroupSummaries.map((group) => (
              <article className="metric-card compare-group-card" key={group.key}>
                <span className="label">{group.label}</span>
                <span className="value">{group.averageSpread.toFixed(2)}</span>
                <p className="muted compare-summary-meta">{t(lang, "compareRunCount")}: {group.runCount}</p>
                <p className="muted compare-summary-meta">{t(lang, "compareAverageScore")}: {group.averageScore.toFixed(2)}</p>
                <p className="muted compare-summary-meta">{t(lang, "avgSpread")}: {group.averageSpread.toFixed(2)} / {t(lang, "maxSpread")}: {group.maxSpread.toFixed(2)}</p>
                <p className="muted compare-summary-meta">{t(lang, "compareDistribution")}: H {group.scoreBands.high} / M {group.scoreBands.mid} / L {group.scoreBands.low}</p>
              </article>
            ))}
          </section>

          <section className="metrics-grid">
            {compareRuns.map((run) => (
              <article className="metric-card compare-summary-card" key={run.id}>
                <span className="label">{getTargetLabel(run.target)}</span>
                <span className="value">{averageScore(run.results).toFixed(2)}</span>
                <p className="muted compare-summary-meta">{t(lang, "compareAverageScore")}: {averageScore(run.results).toFixed(2)}</p>
                <p className="muted compare-summary-meta">{t(lang, "negSignal")}: {(run.metrics.negative_signal_presence_rate * 100).toFixed(0)}%</p>
                <p className="muted compare-summary-meta">{t(lang, "avgSpread")}: {run.metrics.average_spread.toFixed(2)}</p>
              </article>
            ))}
          </section>

          <section className="grid two-up compare-sections">
            {compareRuns.map((run) => (
              <article className="card" key={run.id}>
                <div className="section-head">
                  <div>
                    <p className="eyebrow">{t(lang, "compareTopArticles")}</p>
                    <h3>{getTargetLabel(run.target)}</h3>
                  </div>
                </div>
                <div className="stack">
                  {run.results.slice().sort((a, b) => b.score - a.score).slice(0, 5).map((result) => (
                    <div className="compare-top-row" key={`${run.id}-${result.item_id}`}>
                      <div>
                        <strong>{result.title}</strong>
                        <p>{result.reason || "-"}</p>
                      </div>
                      <span className="score-pill">{result.score.toFixed(1)}</span>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </section>

          <section className="card">
            <div className="section-head">
              <div>
                <p className="eyebrow">{t(lang, "compareGapTitle")}</p>
                <h3>{t(lang, "compareGapSubtitle")}</h3>
              </div>
            </div>
            <div className="stack">
              {topGapRows.map((row) => (
                <div className="compare-gap-row" key={row.itemId}>
                  <div>
                    <strong>{row.title}</strong>
                    <p>{row.itemId}</p>
                  </div>
                  <span className="spread-val">{row.gap.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="results-table-container">
            <table className="results-table compare-table">
              <thead>
                <tr>
                  <th style={{ width: "90px" }}>ID</th>
                  <th>{t(lang, "colTitle")}</th>
                  {compareRuns.map((run) => (
                    <th key={run.id} style={{ width: "140px" }}>{getTargetLabel(run.target)}</th>
                  ))}
                  <th style={{ width: "100px" }}>{t(lang, "compareGapColumn")}</th>
                </tr>
              </thead>
              <tbody>
                {compareRows.map((row) => (
                  <tr key={row.itemId}>
                    <td>{row.itemId}</td>
                    <td>{row.title}</td>
                    {compareRuns.map((run) => {
                      const score = row.scores[run.id];
                      const reason = row.reasonByRun[run.id];
                      return (
                        <td key={`${row.itemId}-${run.id}`}>
                          <div className="compare-score-cell">
                            <span className="score-pill">{score == null ? "-" : score.toFixed(1)}</span>
                            <span className="compare-reason-preview">{reason || "-"}</span>
                          </div>
                        </td>
                      );
                    })}
                    <td>
                      <span className="spread-val">{row.gap.toFixed(2)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      ) : (
        <section className="card">
          <p className="muted">{t(lang, "compareNeedMore")}</p>
        </section>
      )}
    </>
  );
}
