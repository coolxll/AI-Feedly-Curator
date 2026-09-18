# Fallback Quality

Use this when worker agents fail due to 429, timeout, empty output, or malformed JSON.

## Retry Policy

- Start with at least 3 workers.
- Retry only failed chunks.
- Retry each failed chunk at most once.
- If the retry fails, the main agent analyzes that chunk directly.

## Direct Analysis Standard

Direct analysis must still be real reading. Do not write a keyword grouping script that emits "this topic contains N articles" plus title lists.

Use this process:

1. Print or inspect each article's source, title, link, summary, content snippet, and quality flags.
2. Score each item using the 1-5 rubric from the worker template.
3. Drop or demote low-value items.
4. Cluster by event/entity/theme, not by source.
5. Write topic-level analysis with editorial judgment and links.
6. Return the same JSON structure expected from workers, or write a temporary report matching the merge script section format.

## Quality Checks

- Each theme has synthesis, not just links.
- Each claim is grounded in summary/content.
- Similar news is merged into one theme.
- Links are clickable and come from packet `link`.
- `###` subheadings are short semantic labels, not truncated sentences.
- The report does not use traffic-light priority labels.
