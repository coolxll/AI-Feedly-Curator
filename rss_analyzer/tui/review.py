"""Review-unread interactions for stream and batch reading modes."""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from typing import Callable

from rich.panel import Panel


@dataclass(frozen=True)
class ReviewContext:
    console: object
    logger: object
    load_backend_service: Callable[[], object | None]
    select_stream_interactive: Callable[[], tuple[str | None, str | None]]
    get_review_defaults: Callable[[], tuple[int, int, int]]


def render_stream_result(context: ReviewContext, result):
    digest = result.get("digest") or {}
    stats = digest.get("stats", {})
    context.console.print(
        Panel(
            f"策略: {result['strategy']}\n"
            f"文章数（时间窗内）: {result['article_count']}\n"
            f"抓取数: {result.get('fetched_count', result['article_count'])}\n"
            f"Headline: {digest.get('headline', result['summary'])}\n"
            f"摘要: {digest.get('executive_summary', result['summary'])}",
            title="Stream Daily Digest",
            border_style="blue",
        )
    )

    theme_groups = digest.get("top_themes", result.get("theme_groups", []))
    if theme_groups:
        context.console.print("\n[bold]今日重点主题[/bold]")
        for group in theme_groups[:8]:
            context.console.print(
                f"- [cyan]{group['bucket']}[/cyan] ({group['count']}) - {group['summary']}"
            )

    p2_briefing = digest.get("p2_briefing") or {}
    p2_items = p2_briefing.get("must_read") or p2_briefing.get("items") or []
    if p2_briefing:
        context.console.print("\n[bold]P2 快速情报[/bold]")
        context.console.print(f"- {p2_briefing.get('headline', 'No P2 items.')}")
        for item in p2_items[:8]:
            score = item.get("score")
            score_text = f" [{score}/5.0]" if score is not None else ""
            context.console.print(f"- {item.get('event') or item.get('title')}{score_text}")
            if item.get("actors") or item.get("region"):
                context.console.print(
                    f"  [dim]相关方:[/dim] {item.get('actors', '')} "
                    f"[dim]地区:[/dim] {item.get('region', '')}"
                )
            if item.get("core_fact"):
                context.console.print(f"  [dim]事实:[/dim] {item['core_fact']}")
            if item.get("why_it_matters"):
                context.console.print(f"  [dim]影响:[/dim] {item['why_it_matters']}")
            if item.get("link"):
                context.console.print(f"  [dim]链接:[/dim] {item['link']}")

    must_read = digest.get("deep_analyzed_reads") or digest.get(
        "must_read_candidates", result.get("worth_expanding_items", [])
    )
    context.console.print("\n[bold]必须读[/bold]")
    if must_read:
        for item in must_read:
            context.console.print(f"- {item['title']}")
            if item.get("link"):
                context.console.print(f"  [dim]链接:[/dim] {item['link']}")
            if item.get("analysis_summary"):
                context.console.print(f"  [dim]分析:[/dim] {item['analysis_summary']}")
            elif item.get("interpretation"):
                context.console.print(f"  [dim]解读:[/dim] {item['interpretation']}")
            if item.get("score") is not None:
                context.console.print(f"  [dim]评分:[/dim] {item['score']}/5.0")
    else:
        context.console.print("- None")

    skim_items = digest.get("skim_items", [])
    context.console.print("\n[bold]可略读[/bold]")
    if skim_items:
        for item in skim_items[:8]:
            context.console.print(f"- {item['title']}")
            if item.get("link"):
                context.console.print(f"  [dim]链接:[/dim] {item['link']}")
            if item.get("interpretation"):
                context.console.print(f"  [dim]解读:[/dim] {item['interpretation']}")
    else:
        context.console.print("- None")

    clear_items = digest.get("clear_items", result.get("low_priority_items", []))
    context.console.print("\n[bold]可速清[/bold]")
    if clear_items:
        for item in clear_items[:10]:
            context.console.print(f"- {item['title']}")
        if len(clear_items) > 10:
            context.console.print(f"[dim]... and {len(clear_items) - 10} more[/dim]")
    else:
        context.console.print("- None")

    actions = digest.get("actions", [])
    if actions:
        context.console.print("\n[bold]建议动作[/bold]")
        for action in actions:
            context.console.print(f"- {action}")

    if stats:
        context.console.print(
            f"\n[dim]候选 {stats.get('candidate_count', 0)} | "
            f"must-read {stats.get('must_read_count', 0)} | "
            f"skim {stats.get('skim_count', 0)} | "
            f"clear {stats.get('clear_count', 0)}[/dim]"
        )
        if "llm_chunk_count" in stats:
            context.console.print(
                f"[dim]LLM chunks {stats.get('llm_chunk_count', 0)} "
                f"(size {stats.get('llm_chunk_size', 0)}) | "
                f"uncached {stats.get('triage_uncached_count', 0)} | "
                f"cached {stats.get('triage_cached_count', 0)} | "
                f"fallback {stats.get('fallback_chunk_count', 0)}[/dim]"
            )


def open_stream_article(context: ReviewContext, article: dict) -> bool:
    link = article.get("link")
    if not link:
        context.console.print("[red]Selected article does not have a link.[/red]")
        return False

    try:
        return bool(webbrowser.open(link))
    except Exception:
        context.logger.exception("Failed to open article link")
        return False


def prompt_open_stream_article(context: ReviewContext, digest):
    try:
        import questionary
    except ImportError:
        return

    openable_items = []
    for section, items in (
        ("必须读", digest.get("deep_analyzed_reads", [])),
        ("可略读", digest.get("skim_items", [])),
    ):
        for item in items:
            if item.get("link"):
                openable_items.append((section, item))

    if not openable_items:
        return

    if not questionary.confirm("是否在默认浏览器中打开推荐文章阅读?:", default=False).ask():
        return

    choices = [
        questionary.Choice(f"[{section}] {item['title']}", value=item)
        for section, item in openable_items
    ]
    choices.append(questionary.Choice("取消 (Cancel)", value=None))
    selected = questionary.select("请选择要在浏览器中打开的文章:", choices=choices).ask()
    if not selected:
        return

    if open_stream_article(context, selected):
        context.console.print(f"[green]已在浏览器打开:[/green] {selected['title']}")
    else:
        context.console.print("[red]打开文章链接失败。[/red]")


def loop_open_articles(context: ReviewContext, digest):
    """Open articles from digest in browser, one at a time in a loop."""
    import questionary

    openable_items = []
    for section, items in (
        ("必须读", digest.get("deep_analyzed_reads", [])),
        ("可略读", digest.get("skim_items", [])),
    ):
        for item in items:
            if item.get("link"):
                openable_items.append((section, item))

    if not openable_items:
        context.console.print("[yellow]没有包含有效链接的文章可打开。[/yellow]")
        return

    # Build a label->item map since questionary.Choice value may not
    # round-trip dicts reliably.
    opened_links: set[str] = set()

    while True:
        remaining = [
            (s, i) for s, i in openable_items if i.get("link") not in opened_links
        ]
        if not remaining:
            context.console.print("[dim]本批次推荐文章已全部在浏览器中打开。[/dim]")
            break

        label_to_item: dict[str, dict] = {}
        labels: list[str] = []
        for section, item in remaining:
            score_str = ""
            score = item.get("score")
            if score is not None:
                score_str = f" [{score:.1f}]"
            label = f"[{section}] {item['title']}{score_str}"
            label_to_item[label] = item
            labels.append(label)

        done_label = "阅读完毕，返回上一级 (Done reading)"
        labels.append(done_label)
        selected_label = questionary.select(
            f"打开文章阅读 (剩余 {len(remaining)} 篇):", choices=labels
        ).ask()

        if selected_label is None or selected_label == done_label:
            break

        item = label_to_item.get(selected_label)
        if not item:
            continue

        if open_stream_article(context, item):
            opened_links.add(item["link"])
            context.console.print(f"[green]已在浏览器打开:[/green] {item['title']}")
        else:
            context.console.print("[red]打开文章链接失败。[/red]")


def run_batch_read_flow(context: ReviewContext):
    """Batch reading mode: fetch N articles, AI filter, read, mark, repeat."""
    import questionary

    _, default_days, default_chunk = context.get_review_defaults()

    use_stream = questionary.confirm(
        "是否指定特定分类/订阅源 (默认全局所有)?:", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = context.select_stream_interactive()
        if stream_id is None and stream_label is None:
            return
    else:
        stream_id = None
        stream_label = "全量未读 (Global All)"

    batch_str = questionary.text("每批次处理文章数 (Chunk Size):", default=str(default_chunk)).ask()
    try:
        batch_size = int(batch_str)
    except ValueError:
        batch_size = default_chunk

    days_str = questionary.text("最近天数范围 (Recent Days):", default=str(default_days)).ask()
    try:
        days = int(days_str)
    except ValueError:
        days = default_days

    execute_batch_read(
        context,
        stream_id,
        stream_label=stream_label,
        batch_size=batch_size,
        days=days,
    )


def execute_batch_read(
    context: ReviewContext,
    stream_id,
    stream_label=None,
    batch_size=50,
    days=3,
):
    import questionary

    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    context.console.print(
        Panel(
            f"运行模式: 分批渐进清读 (Batch Clear Backlog)\n"
            f"目标订阅源: {display_stream}\n"
            f"单批文章数: {batch_size}\n"
            f"时间范围: 最近 {days} 天",
            title="执行配置 (Configuration)",
            border_style="cyan",
        )
    )

    try:
        backend = context.load_backend_service()
        if backend is None:
            return

        batch_num = 0
        total_marked = 0

        while True:
            batch_num += 1
            context.console.print(f"\n[bold cyan]━━━ 第 {batch_num} 批 (Batch #{batch_num}) ━━━[/bold cyan]")

            result = backend.process_batch(
                stream_id=stream_id,
                stream_label=stream_label,
                batch_size=batch_size,
                days=days,
            )

            fetched = result.get("fetched_count", 0)
            if fetched == 0:
                context.console.print("[green]✓ 所有未读文章已处理完毕！[/green]")
                break

            render_stream_result(context, result)

            digest = result.get("digest") or {}
            mark_read_ids = result.get("mark_read_candidates", [])

            # Interactive loop for this batch
            while True:
                choices = [
                    questionary.Choice("📖 在浏览器中打开文章阅读", value="open"),
                    questionary.Choice(
                        f"🗑️ 标记本批 {len(mark_read_ids)} 篇低优先级文章为已读",
                        value="mark_clear",
                    ),
                    questionary.Choice("✅ 标记本批全部文章为已读并进入下一批", value="mark_all"),
                    questionary.Choice("⏭️ 跳过标记，直接进入下一批", value="next"),
                    questionary.Choice("🚪 退出分批阅读", value="exit"),
                ]
                action = questionary.select(
                    "请选择对本批次文章的操作:",
                    choices=choices,
                ).ask()

                if action == "open":
                    loop_open_articles(context, digest)
                elif action == "mark_clear":
                    if mark_read_ids:
                        mark_result = backend.mark_articles_read(mark_read_ids)
                        if mark_result.get("success"):
                            context.console.print(
                                f"[green]已成功标记 {mark_result['marked_count']} 篇低优先级文章为已读。[/green]"
                            )
                            total_marked += mark_result["marked_count"]
                        else:
                            context.console.print("[red]标记已读失败。[/red]")
                    else:
                        context.console.print("[yellow]本批次无低优先级文章需要标记。[/yellow]")
                elif action == "mark_all":
                    all_ids = []
                    for item in digest.get("deep_analyzed_reads", []):
                        if item.get("id"):
                            all_ids.append(item["id"])
                    for item in digest.get("skim_items", []):
                        if item.get("id"):
                            all_ids.append(item["id"])
                    for item in digest.get("clear_items", []):
                        if item.get("id"):
                            all_ids.append(item["id"])
                    if all_ids:
                        mark_result = backend.mark_articles_read(all_ids)
                        if mark_result.get("success"):
                            context.console.print(
                                f"[green]已成功标记本批全部 {mark_result['marked_count']} 篇文章为已读。[/green]"
                            )
                            total_marked += mark_result["marked_count"]
                        else:
                            context.console.print("[red]标记已读失败。[/red]")
                    break  # move to next batch after marking all
                elif action == "next":
                    break
                elif action == "exit":
                    context.console.print(
                        f"[cyan]分批阅读已结束。累计标记已读: {total_marked} 篇[/cyan]"
                    )
                    return

        context.console.print(
            f"\n[bold green]分批阅读已完成！累计标记已读: {total_marked} 篇[/bold green]"
        )

    except KeyboardInterrupt:
        context.console.print("\n[red]用户取消分批阅读。[/red]")
    except Exception:
        context.logger.exception("An error occurred during batch reading")
        context.console.print("[red]处理过程中发生异常，请检查上方日志。[/red]")


def run_process_stream_flow(context: ReviewContext):
    import questionary

    default_limit, default_days, _ = context.get_review_defaults()

    use_stream = questionary.confirm(
        "是否指定特定分类/订阅源 (默认全局所有)?:", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = context.select_stream_interactive()
        if stream_id is None and stream_label is None:
            return
    else:
        stream_id = None
        stream_label = "全量未读 (Global All)"

    limit_default_str = "0" if default_limit <= 0 else str(default_limit)
    limit_str = questionary.text(
        "抓取文章数量上限 (0 或 'all' 表示全量未读):", default=limit_default_str
    ).ask()
    if not limit_str or limit_str.strip().lower() in ("all", "0", "full"):
        limit = 0
    else:
        try:
            limit = int(limit_str)
        except ValueError:
            limit = default_limit

    days_str = questionary.text("最近天数范围 (Recent Days):", default=str(default_days)).ask()
    try:
        days = int(days_str)
    except ValueError:
        days = default_days

    execute_process_stream(
        context,
        stream_id,
        limit=limit if limit > 0 else 9999,
        days=days,
        stream_label=stream_label,
    )


def execute_process_stream(
    context: ReviewContext,
    stream_id,
    *,
    limit=500,
    days=3,
    stream_label=None,
):
    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    limit_display = "全量未读" if limit >= 9999 else str(limit)
    context.console.print(
        Panel(
            f"运行模式: 快速情报流阅览 (Quick Review Stream)\n"
            f"目标订阅源: {display_stream}\n"
            f"数量上限: {limit_display}\n"
            f"时间范围: 最近 {days} 天",
            title="执行配置 (Configuration)",
            border_style="blue",
        )
    )

    try:
        backend_service = context.load_backend_service()
        if backend_service is None:
            return

        result = backend_service.process_stream(
            stream_id=stream_id,
            stream_label=stream_label,
            days=days,
            limit=limit,
        )
        render_stream_result(context, result)

        try:
            import questionary
        except ImportError:
            return

        digest = result.get("digest") or {}
        prompt_open_stream_article(context, digest)

        low_priority_ids = result.get("mark_read_candidates", [])
        if low_priority_ids and questionary.confirm(
            f"是否将 {len(low_priority_ids)} 篇低优先级文章在 Feedly 标记为已读?:",
            default=False,
        ).ask():
            mark_result = backend_service.mark_stream_low_priority_read(low_priority_ids)
            if mark_result.get("success"):
                context.console.print(
                    f"[green]已成功标记 {mark_result['marked_count']} 篇低优先级文章为已读。[/green]"
                )
            else:
                context.console.print("[red]标记低优先级文章已读失败。[/red]")

        if questionary.confirm("是否导出 Markdown 综述报告?:", default=False).ask():
            overview_file = backend_service.save_stream_overview_markdown(
                result["markdown"],
                stream_label=stream_label or stream_id,
                strategy=result["strategy"],
            )
            context.console.print(f"[green]报告已成功保存至: {overview_file}[/green]")

    except KeyboardInterrupt:
        context.console.print("\n[red]操作已被用户取消。[/red]")
    except Exception:
        context.logger.exception("An error occurred during stream processing")
        context.console.print("[red]处理过程中发生异常，请检查上方日志。[/red]")
