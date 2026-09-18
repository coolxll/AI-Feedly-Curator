---
name: feedly-readflow
description: "Orchestrate high-quality Feedly unread review workflows for AI-Feedly-Curator: fetch all unread RSS items, prefilter noise, enrich article text, split work across 3+ agents, merge similar topics, validate links, generate Markdown reports, and optionally mark confirmed entry-level Feedly items as read."
---

# Feedly Readflow

Use this skill to run a complete Feedly unread reading flow from this repository. The skill owns agent orchestration, prompts, report shape, link validation, Hermes/Codex/Claude delivery, and mark-read safety. Feedly API access, token refresh, caching, article fetching, scoring, LLM calls, and canonical mark-read behavior stay in `rss_analyzer/`.

## Boundary

- Use `rss_analyzer.feedly_client.feedly_fetch_unread` or `python article_analyzer.py --export ...` for Feedly data.
- Use `rss_analyzer.article_fetcher.fetch_article_content` for supplemental article text.
- Use `rss_analyzer.llm_analyzer` and `rss_analyzer.scoring` for the project scoring model.
- Do not add another Feedly client, token refresh path, cache layer, or scoring implementation inside this skill.
- Do not pass Feedly tokens, refresh tokens, API keys, or config files to subagents.

See `references/repo-contract.md` before changing integrations.

## Workflow

1. Fetch unread articles:

   ```bash
   python article_analyzer.py --export output/unread_news.json --limit <N>
   ```

   Or run the packet preparer, which calls the same canonical client:

   ```bash
   python3 skills/feedly-readflow/scripts/prepare_packets.py --limit <N>
   ```

2. Prepare triage packets with deterministic filtering and balanced chunks:

   ```bash
   python3 skills/feedly-readflow/scripts/prepare_packets.py \
     --input output/unread_news.json \
     --output-dir /tmp \
     --no-fetch-content
   ```

   Use `--fetch-content` for real runs when summaries are too short. The script writes `/tmp/feedly_articles.json`, `/tmp/feedly_prefiltered_low_quality.json`, `/tmp/fb_chunk_<n>.json`, and `/tmp/feedly_readflow_manifest.json`.

3. Read `templates/worker_packet.md`, then dispatch at least 3 triage worker agents. Send each worker exactly one chunk file and the worker template. Workers only triage their chunk and return structured JSON. They do not fetch Feedly, write repo files, or mark items read.

   Chunk count:
   - Fewer than 30 candidate articles: 3 workers.
   - 30-90 candidate articles: 3 workers by source/topic balance.
   - More than 90 candidate articles: prefilter first, then use `max(3, ceil(article_count / 50))`.

4. If a worker fails with 429, timeout, or empty output, retry that chunk once. If it fails again, the main agent reads the chunk overview directly and writes equivalent structured triage. Fallback output must still include editorial judgment, topic linkage, and clickable links. See `references/fallback-quality.md`.

5. Optionally deep-analyze only `must_read` or `needs_deep_read=true` candidates:

   ```bash
   python3 skills/feedly-readflow/scripts/prepare_deep_packets.py \
     --report-glob '/tmp/fb_report_*.json' \
     --data /tmp/feedly_articles.json \
     --output-dir /tmp
   ```

   Read `templates/deep_worker_packet.md`, then dispatch deep workers for `/tmp/fb_deep_chunk_<n>.json`. Deep worker reports should be written as `/tmp/fb_deep_report_<n>.json` and may override triage `score`, `decision`, `reasoning`, and `analysis_summary`. Do not deep-read `clear` items unless the triage output is malformed or obviously mistaken.

6. Merge worker JSON outputs into the final Markdown report:

   ```bash
   python3 skills/feedly-readflow/scripts/merge_reports.py \
     --report-glob '/tmp/fb_report_*.json' \
     --deep-report-glob '/tmp/fb_deep_report_*.json' \
     --data /tmp/feedly_articles.json \
     --low-quality /tmp/feedly_prefiltered_low_quality.json \
     --output /tmp/feedly_final_report.md
   ```

   `merge_reports.py` clusters items by `similarity_key` (event entity, company/product, policy, market theme, or technical problem). For each cluster it keeps the highest-score item as the representative and lists the rest as supporting links. Deep reports override triage reports for the same entry. Items with `decision: clear` go to the cleanup section. Legacy `strong_recommend` / `optional` / `low_quality` reports are accepted and normalized. The output follows `templates/final_report.md` with `###` short subheadings and cross-article synthesis, not title-list dumping.

7. Run link repair against the merged Markdown:

   ```bash
   python3 skills/feedly-readflow/scripts/post_merge_link_fix.py \
     --report /tmp/feedly_final_report.md \
     --data /tmp/feedly_articles.json
   ```

   Link validation is mandatory before presenting the report. See `references/link-validation.md`.

8. Mark read only after explicit user confirmation. Use entry-level IDs only:

   ```bash
   python3 skills/feedly-readflow/scripts/mark_read.py clear \
     --report-glob '/tmp/fb_report_*.json' \
     --deep-report-glob '/tmp/fb_deep_report_*.json' \
     --low-quality /tmp/feedly_prefiltered_low_quality.json \
     --confirm MARK_READ
   ```

## Source Rules

- Do not fetch original pages for `jisilu.cn` / `www.jisilu.cn`; use Feedly summary/content and mark `content_source: feedly_summary_limited`.
- Do not expand 36kr newsflash URLs; the Feedly preview is the content.
- Filter V2EX aggressively for promotions, shared-plan posts, short Q&A, generic troubleshooting, and empty previews.
- Treat Reddit and forum posts as lower priority unless the body contains concrete technical, market, or social signal.
- Read `references/source-strategies.md` when source-specific behavior matters.

## Link Rules

Every article link in worker output and final Markdown must come from the packet `link` field. Never construct, guess, splice, or extract article URLs from preview text. If `link` is empty, write `无链接`.

Run `post_merge_link_fix.py` after merging to repair known failure modes: tmtpost `.html`, V2EX title/link mismatches, duplicate collapsed URLs, broken Markdown links, and generic Xueqiu URLs.

## Mark-Read Rules

- Default is no mark-read.
- Mark read only with explicit user confirmation or an explicit `--confirm MARK_READ` command.
- Use only entry-level `entryIds` through `rss_analyzer.feedly_client.feedly_mark_read`.
- Never use stream-level mark-all from this skill.

## WSL Hermes Usage

This skill is intended to be used by Hermes inside WSL through a repository reference, not by copying business logic into `~/.hermes`.

Recommended setup:

```bash
cd /mnt/c/Workspace/Personal/rss-opml
export UV_PROJECT_ENVIRONMENT=.venv-wsl
uv sync
mkdir -p ~/.hermes/skills/research
ln -sfn /mnt/c/Workspace/Personal/rss-opml/skills/feedly-readflow \
  ~/.hermes/skills/research/feedly-readflow
```

Run repository scripts from the repo root:

```bash
cd /mnt/c/Workspace/Personal/rss-opml
export UV_PROJECT_ENVIRONMENT=.venv-wsl
uv run python skills/feedly-readflow/scripts/prepare_packets.py \
  --limit 60 \
  --output-dir /tmp/readflow
```

Do not use a shared `.venv/` between Windows and WSL. Use `.venv-wsl/` in WSL and `.venv-win/` on Windows. Do not copy `.env`, `feedly_config.json`, tokens, API keys, or raw request headers into Hermes worker prompts.
