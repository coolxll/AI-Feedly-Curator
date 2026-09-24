"""Export, summary, and deep-analysis interactions for the Feedly TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.panel import Panel

from rss_analyzer.config import LATEST_ANALYZED_FILE, PROJ_CONFIG
from rss_analyzer.tui.support import (
    filter_articles_by_titles,
    format_limit_display,
    resolve_export_path,
    resolve_stream_feed_titles,
)
from rss_analyzer.utils import load_articles


@dataclass(frozen=True)
class ReportContext:
    console: object
    logger: object
    load_backend_service: Callable[[], object | None]
    select_stream_interactive: Callable[[], tuple[str | None, str | None]]


def run_export_flow(context: ReportContext):
    """Interactive export flow"""
    import questionary
    from datetime import datetime

    # 1. Select Stream
    use_stream = questionary.confirm(
        "是否指定特定分类或订阅源 (默认导出全局所有)?", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = context.select_stream_interactive()
        if stream_id is None and stream_label is None:
            return
    else:
        stream_id = None
        stream_label = "Global All"

    # 2. Limit
    limit_str = questionary.text("导出文章数量上限 (输入 0 为全量):", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    # 3. Output Filename
    default_filename = f"output/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename = questionary.text("导出文件路径 (Output Filename):", default=default_filename).ask()

    execute_export(context, limit, stream_id, filename, stream_label)



def execute_export(
    context: ReportContext,
    limit,
    stream_id,
    filename,
    stream_label=None,
):
    filename = resolve_export_path(filename)
    display_stream = stream_label if stream_label else (stream_id or "Global All (全局所有)")
    limit_display = "All (全量)" if limit == 0 else str(limit)
    context.console.print(
        Panel(
            f"正在导出未读文章\n"
            f"数量上限: {limit_display}\n"
            f"订阅范围: {display_stream}\n"
            f"导出路径: {filename}",
            title="导出配置",
            border_style="blue",
        )
    )

    try:
        backend_service = context.load_backend_service()
        if backend_service is None:
            return

        result = backend_service.export_articles(
            limit=limit,
            output_file=filename,
            stream_id=stream_id,
        )
        if result.get("error"):
            context.console.print(Panel(result["message"], style="red"))
            return

        context.console.print(
            Panel(f"导出完成！已成功保存至 {filename}", style="bold green")
        )
    except Exception:
        context.logger.exception("Error exporting")
        context.console.print("[red]导出失败，请检查日志。[/red]")

def run_summary_flow(context: ReportContext):
    try:
        import questionary
    except ImportError:
        context.console.print(Panel("正在生成总结报告...", style="bold blue"))
        try:
            backend_service = context.load_backend_service()
            if backend_service is None:
                return

            result = backend_service.regenerate_summary()
            if result.get("error"):
                context.console.print(Panel(result["message"], style="red"))
                return

            context.console.print(Panel("总结报告生成完成！", style="bold green"))
        except Exception:
            context.logger.exception("Error generating summary")
            context.console.print("[red]生成总结报告失败。[/red]")
        return

    mode = questionary.select(
        "选择总结模式 (Summary Mode):",
        choices=[
            questionary.Choice(
                "基于本地已分析的数据重新生成总结", value="local"
            ),
            questionary.Choice(
                "从 Feedly 重新抓取、完整分析并生成总结", value="refresh"
            ),
            questionary.Choice("🔙 返回上级 (Back)", value="back"),
        ],
    ).ask()

    if mode == "back":
        return

    use_stream = questionary.confirm(
        "是否指定特定分类或订阅源 (默认全局所有)?", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = context.select_stream_interactive()
        if stream_id is None and stream_label is None:
            return
    else:
        stream_id = None
        stream_label = "Global All"

    if mode == "local":
        context.console.print(Panel("Summarizing Local Articles...", style="bold blue"))
        try:
            context.console.print(f"[dim]Loading {LATEST_ANALYZED_FILE}...[/dim]")
            articles = load_articles(LATEST_ANALYZED_FILE)

            if stream_id:
                context.console.print("[dim]Resolving selected stream...[/dim]")
                titles = resolve_stream_feed_titles(stream_id)
                if titles is None:
                    context.console.print(
                        "[yellow]Unable to resolve stream to feeds. Using all local articles.[/yellow]"
                    )
                articles = filter_articles_by_titles(articles, titles)

            if not articles:
                context.console.print("[yellow]No articles matched the selection.[/yellow]")
                return

            backend_service = context.load_backend_service()
            if backend_service is None:
                return

            result = backend_service.generate_summary_report(articles)
            context.console.print(
                Panel(
                    "总结报告生成完成！(Summary Generation Complete)\n"
                    f"- 报告文件: {result['summary_file']}\n"
                    f"- 最新报告: {result['latest_summary_file']}",
                    style="bold green",
                )
            )
        except Exception:
            context.logger.exception("Error generating summary")
            context.console.print("[red]生成总结报告失败。[/red]")
        return

    # refresh mode
    limit_str = questionary.text("文章数量上限 (Article Limit):", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        context.console.print("[red]无效的数字，使用默认值 100[/red]")
        limit = 100

    mark_read = questionary.confirm(
        "分析完成后是否在 Feedly 标记为已读 (Mark as read)?:",
        default=PROJ_CONFIG.get("mark_read", False),
    ).ask()

    execute_analyze(context, limit, True, mark_read, stream_id, 3, stream_label)


def run_analyze_flow(context: ReportContext):
    """Interactive analyze flow using questionary"""
    import questionary

    # Configure parameters
    limit_str = questionary.text("文章数量上限 (Article Limit):", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        context.console.print("[red]无效的数字，使用默认值 100[/red]")
        limit = 100

    refresh = questionary.confirm(
        "是否从 Feedly 拉取最新未读文章 (Refresh)?:", default=True
    ).ask()

    stream_id = None
    stream_label = None
    if refresh:
        # Only ask for stream if we are refreshing
        use_stream = questionary.confirm(
            "是否指定特定分类/订阅源 (默认全局所有)?:", default=False
        ).ask()
        if use_stream:
            stream_id, stream_label = context.select_stream_interactive()

    mark_read = questionary.confirm(
        "分析完成后是否在 Feedly 标记为已读 (Mark as read)?:",
        default=PROJ_CONFIG.get("mark_read", False),
    ).ask()

    threads_str = questionary.text("并发分析线程数 (Threads):", default="3").ask()
    try:
        threads = int(threads_str)
    except ValueError:
        context.console.print("[red]无效的线程数，使用默认值 3[/red]")
        threads = 3

    execute_analyze(context, limit, refresh, mark_read, stream_id, threads, stream_label)

def execute_analyze(
    context: ReportContext,
    limit,
    refresh,
    mark_read,
    stream_id=None,
    threads=3,
    stream_label=None,
):
    """Shared analyze execution logic"""
    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    limit_display = format_limit_display(limit)
    context.console.print(
        Panel(
            f"运行模式: 深度研读与分析报告 (Full Analyze + Report)\n"
            f"文章上限: {limit_display}\n"
            f"重新拉取: {'是' if refresh else '否'}\n"
            f"目标订阅源: {display_stream}\n"
            f"标记已读: {'是' if mark_read else '否'}\n"
            f"并发线程: {threads}",
            title="执行配置 (Configuration)",
            border_style="blue",
        )
    )

    try:
        backend_service = context.load_backend_service()
        if backend_service is None:
            return

        result = backend_service.analyze_articles(
            limit=limit,
            refresh=refresh,
            mark_read=mark_read,
            stream_id=stream_id,
            threads=threads,
        )
        if result.get("error"):
            context.console.print(Panel(result["message"], style="red"))
            return

        context.console.print(
            Panel(
                "深度研读分析完成！(Article Analysis Complete)\n"
                f"- 分析数据: {result['analyzed_file']}\n"
                f"- 总结报告: {result['summary_file']}",
                style="bold green",
            )
        )

    except KeyboardInterrupt:
        context.console.print("\n[red]操作已被用户取消。[/red]")
    except Exception:
        context.logger.exception("An error occurred during analysis")
        context.console.print("[red]分析过程中发生异常，请检查上方日志。[/red]")
