import { RunDetail, CompareRow, ModelGroupSummary } from "./types";

export function getTargetLabel(target: string): string {
  return target.split("|")[0] || target;
}

export function averageScore(results: { score: number }[]): number {
  if (results.length === 0) return 0;
  return results.reduce((sum, item) => sum + item.score, 0) / results.length;
}

export function buildCompareRows(runDetails: RunDetail[]): CompareRow[] {
  const rows = new Map<string, CompareRow>();

  for (const run of runDetails) {
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

  return Array.from(rows.values())
    .map((row) => {
      const values = Object.values(row.scores).filter((value): value is number => typeof value === "number");
      const gap = values.length > 1 ? Math.max(...values) - Math.min(...values) : 0;
      return { ...row, gap };
    })
    .sort((a, b) => b.gap - a.gap || a.itemId.localeCompare(b.itemId));
}

export function buildModelGroupSummaries(runDetails: RunDetail[]): ModelGroupSummary[] {
  const groups = new Map<string, RunDetail[]>();

  for (const run of runDetails) {
    const key = getTargetLabel(run.target);
    const existing = groups.get(key) ?? [];
    existing.push(run);
    groups.set(key, existing);
  }

  return Array.from(groups.entries()).map(([key, groupedRuns]) => {
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
  }).sort((a, b) => a.label.localeCompare(b.label));
}
