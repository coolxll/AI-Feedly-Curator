# Repo Contract

This skill is a thin orchestration layer over AI-Feedly-Curator. Shared product behavior belongs in the repository core.

## Canonical Entry Points

- `rss_analyzer.feedly_client.feedly_fetch_unread(stream_id=None, limit=999)`  
  Fetch unread Feedly entries with token refresh and proxy handling.

- `rss_analyzer.feedly_client.feedly_mark_read(article_ids)`  
  Mark entry-level Feedly IDs as read using `{"type": "entries", "entryIds": [...]}`.

- `rss_analyzer.article_fetcher.fetch_article_content(url)`  
  Fetch and extract article body text using the project extraction path.

- `rss_analyzer.llm_analyzer.analyze_article_with_llm(title, summary, content)`  
  Score and summarize one article through the current scoring implementation.

- `rss_analyzer.llm_analyzer.analyze_articles_with_llm_batch(articles)`  
  Batch score articles when the project config enables batch behavior.

- `rss_analyzer.backend_service.generate_summary_report(articles)`  
  Generate the repository summary report from analyzed articles.

- `python article_analyzer.py --export output/unread_news.json --limit <N>`  
  Export unread Feedly articles without analysis.

## Do Not Duplicate

Do not create a second implementation for:

- Feedly token loading or refresh.
- Feedly API requests.
- Feedly pagination.
- Article content extraction.
- LLM scoring rubrics or score parsing.
- Cache or vector-store writes.
- Mark-read HTTP calls.

If the skill needs a shared capability that does not exist, add it under `rss_analyzer/` first, test it, then call it from the skill.

## Data Safety

Subagents receive normalized article packets only. Packets must not contain `token`, `refresh_token`, API keys, `.env` values, `feedly_config.json`, or raw request headers.
