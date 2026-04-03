export type Lang = "en" | "zh";

export const translations = {
  en: {
    // Sidebar
    arena: "Arena",
    title: "Scoring Arena",
    subtitle: "A desktop workbench for benchmark datasets, repeatability, and model-to-model scoring drift.",
    navDatasets: "Datasets",
    navRuns: "Runs",
    navCompare: "Compare",
    navTargets: "Targets",
    statusLoading: "Loading...",
    statusError: "Error",
    statusLoaded: "{{count}} datasets loaded",
    statusConnected: "UI shell connected to Tauri backend.",

    // Hero
    heroTag: "Desktop Scoring Lab",
    heroTitle: "Stability-first benchmark arena for RSS article scoring",
    heroDesc: "Compare cheap and strong models on fixed datasets, inspect score spread, and track instruction adherence instead of only looking at one-off scores.",
    btnCreateRun: "Create Run",
    btnStopRun: "Stop Run",
    btnImport: "Import Existing Results",
    repeatLabel: "Repeat",

    // Datasets
    datasetsTag: "Datasets",
    datasetsTitle: "Fixed Benchmarks",
    datasetsLoaded: "{{count}} loaded",
    datasetsSeeded: "{{count}} seeded",
    backToList: "Back to list",
    items: "{{count}} items",

    // Compare
    compareTag: "Compare",
    compareTitle: "What matters here",
    metricsV1: "v1 metrics",
    metricAvgSpread: "average_spread",
    metricMaxSpread: "max_spread",
    metricHighScore: "high_score_rate",
    metricNegSignal: "negative_signal_presence_rate",
    metricCheapGap: "cheap_vs_sota_gap",

    // Targets
    targetsTitle: "Model Configurations",
    addTarget: "Add Target",
    saveTargets: "Save Configurations",
    targetName: "Alias Name",
    targetModel: "Model ID",
    targetBaseUrl: "API Base URL",
    targetEnvKey: "API Key Env Var",

    // Runs
    runsTag: "Runs",
    runsTitle: "Recent Evaluations",
    runsPlaceholder: "placeholder data",
    expected: "expected",
    runSuccess: "Run started successfully",
    runError: "Failed to start run",
    runDetail: "Run Details",
    metricsTitle: "Performance Metrics",
    resultsTable: "Item-level Results",
    colTitle: "Title",
    colScore: "Score",
    colSpread: "Spread",
    colReason: "Reason",
    noRuns: "No run history found.",
    avgSpread: "Avg Spread",
    maxSpread: "Max Spread",
    highScoreRate: "Inflation",
    negSignal: "Neg Signal Rate",
    gap: "Gap",
    consoleTitle: "Execution Console",
    clearLogs: "Clear",
    progressTitle: "Run Progress",
    progressQueued: "Queued real benchmark",
    progressRunning: "Running",
    progressStopping: "Stopping",
    progressFinished: "Finished",
    progressModeReal: "real run",
    compareOpen: "Open Compare",
    compareWorkspace: "Run Comparison",
    compareHint: "Select two or more runs in the Runs tab to compare their scoring behavior.",
    compareSelected: "{{count}} selected",
    compareNeedMore: "Select at least two runs to start comparing.",
    compareLoading: "Loading selected runs...",
    compareSelectRun: "Compare",
    compareAverageScore: "Average Score",
    compareTopArticles: "Top Articles",
    compareGapTitle: "Largest Gaps",
    compareGapSubtitle: "Articles with the biggest score disagreement across selected runs",
    compareGapColumn: "Gap",
    compareRunCount: "Runs",
    compareDistribution: "Distribution",

    // Errors
    errDatasetsDir: "Datasets directory not found",
    errReadDir: "Failed to read datasets directory",
  },
  zh: {
    // Sidebar
    arena: "竞技场",
    title: "评分竞技场",
    subtitle: "用于基准数据集、可重复性和模型间评分漂移的桌面工作台。",
    navDatasets: "数据集",
    navRuns: "运行记录",
    navCompare: "对比",
    navTargets: "目标模型",
    statusLoading: "加载中...",
    statusError: "错误",
    statusLoaded: "已加载 {{count}} 个数据集",
    statusConnected: "前端已连接 Tauri 后端。",

    // Hero
    heroTag: "桌面评分实验室",
    heroTitle: "面向 RSS 文章评分的稳定性优先基准测试平台",
    heroDesc: "在固定数据集上对比廉价与强力模型，检查评分分布，追踪指令遵循度，而不仅看单次评分。",
    btnCreateRun: "创建运行",
    btnStopRun: "停止运行",
    btnImport: "导入现有结果",
    repeatLabel: "重复次数",

    // Datasets
    datasetsTag: "数据集",
    datasetsTitle: "固定基准",
    datasetsLoaded: "已加载 {{count}} 个",
    datasetsSeeded: "{{count}} 个内置",
    backToList: "返回列表",
    items: "{{count}} 条数据",

    // Compare
    compareTag: "对比",
    compareTitle: "关键指标",
    metricsV1: "v1 指标",
    metricAvgSpread: "平均分差",
    metricMaxSpread: "最大分差",
    metricHighScore: "高分率",
    metricNegSignal: "负面信号检出率",
    metricCheapGap: "廉价模型与 SOTA 差距",

    // Targets
    targetsTitle: "模型配置",
    addTarget: "添加目标",
    saveTargets: "保存配置",
    targetName: "别名",
    targetModel: "模型 ID",
    targetBaseUrl: "接口地址",
    targetEnvKey: "环境变量名",

    // Runs
    runsTag: "运行记录",
    runsTitle: "最近评估",
    runsPlaceholder: "示例数据",
    expected: "预期",
    runSuccess: "运行已成功启动",
    runError: "运行启动失败",
    runDetail: "运行详情",
    metricsTitle: "性能指标",
    resultsTable: "单条评价结果",
    colTitle: "标题",
    colScore: "得分",
    colSpread: "分差",
    colReason: "理由",
    noRuns: "暂无运行记录",
    avgSpread: "平均漂移",
    maxSpread: "最大漂移",
    highScoreRate: "高分膨胀",
    negSignal: "负面信号率",
    gap: "模型分差",
    consoleTitle: "执行控制台",
    clearLogs: "清空",
    progressTitle: "运行进度",
    progressQueued: "真实评测已排队",
    progressRunning: "运行中",
    progressStopping: "停止中",
    progressFinished: "已完成",
    progressModeReal: "真实运行",
    compareOpen: "打开对比",
    compareWorkspace: "运行结果对比",
    compareHint: "先在运行记录页选择两个或更多 run，再在这里查看模型差异。",
    compareSelected: "已选择 {{count}} 个",
    compareNeedMore: "至少选择两个 run 才能开始对比。",
    compareLoading: "正在加载已选 run...",
    compareSelectRun: "加入对比",
    compareAverageScore: "平均分",
    compareTopArticles: "高分文章",
    compareGapTitle: "分差最大",
    compareGapSubtitle: "同一篇文章在不同 run 间分歧最大的结果",
    compareGapColumn: "分差",
    compareRunCount: "运行次数",
    compareDistribution: "分布",

    // Errors
    errDatasetsDir: "未找到数据集目录",
    errReadDir: "读取数据集目录失败",
  },
};

export function t(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  let text = (translations[lang] as Record<string, string>)[key] || key;
  if (vars) {
    Object.entries(vars).forEach(([k, v]) => {
      text = text.replace(`{{${k}}}`, String(v));
    });
  }
  return text;
}
