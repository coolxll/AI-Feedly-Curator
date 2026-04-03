export interface DatasetInfo {
  name: string;
  version: string;
  created_at: string;
  description: string;
  item_count: number;
}

export interface DatasetItem {
  id: string;
  title: string;
  origin: string;
  link: string;
  published: number;
  summary_excerpt: string;
  category: string;
  expected_band: string;
}

export interface DatasetDetail {
  dataset: string;
  version: string;
  created_at: string;
  description: string;
  source_files: string[];
  items: DatasetItem[];
}

export interface RunSummary {
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

export interface RunResult {
  item_id: string;
  title: string;
  score: number;
  spread: number;
  reason: string;
}

export interface RunDetail extends RunSummary {
  results: RunResult[];
}

export interface CompareRow {
  itemId: string;
  title: string;
  scores: Record<string, number | null>;
  reasonByRun: Record<string, string>;
  gap: number;
}

export interface ModelGroupSummary {
  key: string;
  label: string;
  runCount: number;
  averageScore: number;
  negativeSignalRate: number;
  averageSpread: number;
  maxSpread: number;
  scoreBands: { high: number; mid: number; low: number };
}

export interface RunProgress {
  phase: string;
  current: number;
  total: number;
  percent: number;
  message: string;
  target?: string | null;
  mode: string;
  done: boolean;
  error: boolean;
}
