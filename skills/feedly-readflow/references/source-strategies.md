# Source Strategies

Use these rules when preparing packets and when judging whether missing full text is acceptable.

## Use Feedly Content As-Is

- 华尔街见闻: previews are usually rich enough for market signal analysis.
- 钛媒体: Feedly content is often article-level.
- cnBeta 全文版: generally enough for triage.
- 爱范儿, 异次元软件世界, 小众软件: use Feedly preview/content unless obviously truncated.
- 雪球今日话题: often sufficient; avoid generic `xueqiu.com/today` links in final reports.

## Briefs

- 36kr newsflashes: do not expand. Treat the preview as the full item.
- Solidot: usually a brief; use as-is unless the summary is empty.
- Daily digest sources: treat as brief summaries, not deep articles.

## Forums

- V2EX: high volume and low signal. Filter aggressively: promotions, shared subscriptions, airport/VPS deals, short Q&A, generic Apple troubleshooting, game deals, empty previews, and very short posts outside `[分享创造]` / `[程序员]`.
- 集思录 / `jisilu.cn`: do not fetch originals by default because login/comments are usually inaccessible. Use Feedly summary/content and mark `feedly_summary_limited`.
- Reddit: lower priority by default. Keep only substantive technical, market, geopolitical, or social discussions.
- LinuxDo: Cloudflare often blocks RSS/web fetches. Do not add a separate Feedly workaround inside this skill.

## Content Sufficiency

Fetch original text only when:

- The source is not in the no-fetch list.
- The item is not a 36kr newsflash or other brief where preview is the content.
- Feedly summary/content is too short for a grounded decision.

When fetch fails, keep the article if the Feedly summary is still meaningful and set a quality flag such as `fetch_failed` or `short_summary`.
