# Link Validation

Every report link must be traceable to the normalized packet `link` field.

## Known Feedly/API Pitfalls

- Feedly raw entries use `alternate` singular, usually `alternate[0].href`.
- Normalized packets should expose one `link` field. Workers must use only that field.
- Never extract links from preview/content text; previews can contain unrelated links.

## Known Subagent Failure Modes

- V2EX title/link mismatches: a valid thread URL can be paired with the wrong title.
- URL collapse: one URL reused for many unrelated titles.
- tmtpost missing `.html`: `https://www.tmtpost.com/8036191` should become `https://www.tmtpost.com/8036191.html`.
- Broken Markdown: `- [title(url)` should become `- [title](url)`.
- Xueqiu generic URLs: `xueqiu.com/today` should be replaced with the article-specific packet URL when available.
- Duplicate `[来源](url)` lines can be introduced while merging similar sections.

## Required Process

1. Merge worker JSON reports with `scripts/merge_reports.py --report-glob '/tmp/fb_report_*.json'`. The script clusters by `similarity_key` and renders the final Markdown; links come only from each item's `link` field.
2. Run `scripts/post_merge_link_fix.py --report /tmp/feedly_final_report.md --data /tmp/feedly_articles.json` against the merged Markdown.
3. Manually inspect remaining warnings, especially repeated URLs and empty links.

HTTP status checks are optional and can be noisy because 302 redirects for 36kr/cnBeta are normal. Title/link cross-validation against packet data is more important than HTTP 200 checks.
