# Deep Worker Packet Template

You are deep-reading selected Feedly candidates prepared by `prepare_deep_packets.py`.

## Rules

- Analyze only articles in this packet.
- Do not call Feedly, fetch tokens, refresh tokens, mark articles read, or write repository files.
- Use the packet `link` field as the only URL source.
- Ground your judgment in `summary`, `content`, `content_source`, `quality_flags`, and the existing `triage` object.
- If `content_source` is `feedly_summary_limited`, avoid overconfident claims and say the available text is limited.

## Output

Return JSON only. The top-level value must be an array with one object per article:

```json
[
  {
    "id": "Feedly entry id",
    "title": "Article title",
    "link": "Exact packet link, or empty string",
    "origin": "Feed/source name",
    "domain": "example.com",
    "readflow_domain": "Tech | P1 | P2 | Other",
    "score": 4.2,
    "decision": "must_read | skim | clear",
    "event": "Short event or topic",
    "actors": "Main actors, comma-separated",
    "region": "Region/country, if relevant",
    "core_fact": "Most important confirmed fact",
    "core_facts": ["Concrete fact from the article"],
    "why_it_matters": "Why this changes the user's understanding",
    "analysis_summary": "Short deep-read conclusion",
    "reasoning": "Why the triage decision is confirmed or changed",
    "similarity_key": "Stable topic/event key"
  }
]
```

Only keep `must_read` when the full packet confirms meaningful value. Demote to `skim` or `clear` when the full content is routine, duplicated, promotional, or too thin.
