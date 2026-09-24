"""Compatibility facade for Feedly domain workflows."""

from rss_analyzer.feed_analysis_workflow import (
    PROJECT_ROOT,
    ProgressCallback,
    analyze_articles,
    get_analysis_service,
    get_runtime_paths,
)
from rss_analyzer.filter_workflows import (
    FEED_ID_36KR,
    FilterResult,
    fetch_filter_articles,
    low_score_filter,
    mark_article_ids_as_read,
    mark_filter_results_as_read,
    newsflash_filter,
    run_filter_pipeline,
    run_filter_workflow,
)
from rss_analyzer.readflow_workflows import (
    BATCH_READ_FETCH_LIMIT,
    BATCH_TRIAGE_CACHE_VERSION,
    _build_batch_triage_prompt,
    _deep_analysis_log_step,
    _deep_analyze_digest_candidates,
    _parse_batch_triage_results,
    mark_articles_read,
    mark_stream_low_priority_read,
    process_batch,
    process_stream,
    save_stream_overview_markdown,
)
