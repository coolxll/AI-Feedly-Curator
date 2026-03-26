---
name: article-reading-report
description: Build content-first reading reports from Feedly or exported RSS JSON by first preparing a reading packet with fetched article bodies, embedded content, or summary fallbacks, then using the agent's own reasoning to rank articles and write a final overall summary. Use when Codex needs to summarize many links/articles, decide what is worth reading, or replace title/summary-only article clustering.
---

# Article Reading Report

Fast workflow to fetch article bodies from exported RSS JSON, prepare an analysis packet, and let the agent itself produce the final reading report.

## Summary

- Reads exported RSS or Feedly JSON files such as `export_<timestamp>.json`
- Fetches full article bodies before judging whenever possible
- Falls back to embedded content or RSS summaries when fetching fails
- Produces a structured JSON packet for the agent to read
- Produces a Markdown sources index with clickable original links
- Requires the agent itself to write the final Markdown report and overall summary
- Labels evidence explicitly: `正文`, `RSS全文`, `摘要回退`, `抓取失败`

## Quick start

```powershell
python skills/article-reading-report/scripts/build_reading_report.py --input <exported-json-file>
python skills/article-reading-report/scripts/build_reading_report.py --input <exported-json-file> --limit 40
```

After the script finishes, read the generated packet and use the current agent model to produce a final report. In that final report, always use Markdown links for article titles: `[title](url)`.

## Rules

1. Do not call an external LLM from the script.
2. Use the script only to fetch, clean, and package evidence.
3. Use the agent's own reasoning for per-article judgment and final batch summary.
4. In the final report, every article reference should include the original link.
5. The final human-facing artifact should be a single Markdown report that combines conclusions and original links together.
6. Lower confidence when the judgment is not based on fetched body text.
7. Mark weak-evidence items explicitly in the final report.

## Useful flags

- `--limit <N>`: only prepare the first N articles
- `--min-content-chars <N>`: minimum extracted body length before falling back to summary
- `--output-dir <path>`: choose where the outputs are written

Example:

```powershell
python skills/article-reading-report/scripts/build_reading_report.py `
  --input <exported-json-file> `
  --limit 40 `
  --min-content-chars 600 `
  --output-dir output\reading-reports
```

## Output

The script writes:

- one run directory under `output/reading-reports/<timestamp>/`
- `reading-packet.json` with cleaned content and evidence labels
- `reading-sources.md` with clickable original article links

When writing the final human-facing report, use `skills/article-reading-report/references/final-report-template.md` as the output template.

The agent should then use that packet to answer:

- Which articles should be read first?
- Which ones can be skipped safely?
- Which judgments are weak because only summary text was available?
- Which topics dominate the export?
- What is the concise final takeaway from this batch?

## Script

- `skills/article-reading-report/scripts/build_reading_report.py`
