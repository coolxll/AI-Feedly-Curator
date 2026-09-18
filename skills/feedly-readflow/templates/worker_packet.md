# Triage Worker Packet Template

You are analyzing one Feedly chunk prepared by `skills/feedly-readflow/scripts/prepare_packets.py`.

## Rules

- Analyze only articles in this packet.
- Do not call Feedly, fetch tokens, refresh tokens, mark articles read, or write repository files.
- Use the packet `link` field as the only URL source. Do not extract, infer, repair, or invent URLs from previews or titles.
- If `link` is empty, set `link` to `""` and mention `无链接` only in prose.
- Read the `summary`, `content_excerpt`, `content_source`, `quality_flags`, and source/domain fields. Do not judge from titles alone.
- If `content_source` is `feedly_summary_limited`, state that the summary is limited and avoid overconfident claims.

## Triage

Classify every article with the same readflow triage used by the TUI.

`domain` must be one of:

- `Tech`: technology, AI, developer tools, engineering.
- `P1`: investing, markets, macro, assets.
- `P2`: geopolitics, diplomacy, war, sanctions, national relations.
- `Other`: everything else.

`decision` must be one of:

- `must_read`: worth opening or needs full-text confirmation.
- `skim`: core fact is enough; no urgent deep read.
- `clear`: repeated, low-incremental, promotional, unreadable, or irrelevant.

Score on 1-5:

- `5`: rare, high-value original analysis, major event, technical breakthrough, or unusually useful detail.
- `4`: useful industry/market/technical/geopolitical development with real substance.
- `3`: acceptable but routine news, product update, or normal discussion.
- `2`: low-information, repetitive, shallow, weakly relevant.
- `1`: noise, ad, spam, title bait, unreadable, or no useful content.

If `domain` is `P2`, extract event, actors, region, concrete fact, and impact. Mark `needs_deep_read=true` when the Feedly summary is too short, the event is consequential, or the article may contain important facts not visible in the packet.

## Output

Return JSON only. The top-level value must be an array with one object per article you analyzed:

```json
[
  {
    "id": "Feedly entry id",
    "title": "Article title",
    "link": "Exact packet link, or empty string",
    "origin": "Feed/source name",
    "domain": "example.com",
    "readflow_domain": "Tech | P1 | P2 | Other",
    "domain_confidence": 0.9,
    "score": 3.6,
    "decision": "must_read | skim | clear",
    "quality_flags": ["short_summary", "pure_promotion"],
    "content_source": "fetched | feedly_content | feedly_summary | feedly_summary_limited",
    "event": "Short event or topic",
    "actors": "Main actors, comma-separated",
    "region": "Region/country, if relevant",
    "core_fact": "Concrete fact, number, entity, or technical point",
    "core_facts": ["Concrete fact, number, entity, or technical point"],
    "why_it_matters": "Why it matters, if there is substance",
    "novelty": "new | repeat | unclear",
    "needs_deep_read": false,
    "rec": "Short reading recommendation",
    "reasoning": "Concise rationale grounded in the actual summary/content.",
    "similarity_key": "Short stable key for topic/event clustering"
  }
]
```

Use `similarity_key` to make final grouping easy: company/product, policy/event, market theme, technical problem, or community discussion theme. Do not group only by source.
