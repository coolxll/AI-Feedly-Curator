"""Unread cleanup interactions for the Feedly TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.panel import Panel

from rss_analyzer.tui.support import format_limit_display, get_cleanup_defaults


@dataclass(frozen=True)
class CleanupContext:
    console: object
    logger: object
    load_backend_service: Callable[[], object | None]
    select_stream_interactive: Callable[[], tuple[str | None, str | None]]
    get_input: Callable[..., str]
    execute_filter: Callable[..., object]


def simple_filter_flow(context: CleanupContext):
    """Fallback filter flow"""
    default_limit, default_threshold, default_mark_read = get_cleanup_defaults()
    limit_text = format_limit_display(default_limit)
    mark_text = "是" if default_mark_read else "否"
    context.console.print("\n[bold]低分与快讯批量过滤 (Clean Up Unread):[/bold]")
    context.console.print(
        f"1. ⚡ 一键全量过滤 (快讯 + 低分 < {default_threshold}, 篇数: {limit_text}, 自动标已读: {mark_text})"
    )
    context.console.print(
        f"2. ⚡ 一键快讯过滤 (仅 36kr 7x24 短讯, 篇数: {limit_text}, 自动标已读: {mark_text})"
    )
    context.console.print(
        f"3. ⚡ 一键低分过滤 (仅 AI 评分 < {default_threshold}, 篇数: {limit_text}, 自动标已读: {mark_text})"
    )
    context.console.print("4. 🛠 自定义过滤配置")
    context.console.print("5. 🔙 返回主菜单")

    choice = context.get_input("请选择操作序号", default="1")

    if choice == "1":
        context.execute_filter(
            "all", default_limit, default_threshold, False, mark_read=default_mark_read
        )
        return
    elif choice == "2":
        context.execute_filter(
            "newsflash",
            default_limit,
            default_threshold,
            False,
            mark_read=default_mark_read,
        )
        return
    elif choice == "3":
        context.execute_filter(
            "low-score",
            default_limit,
            default_threshold,
            False,
            mark_read=default_mark_read,
        )
        return
    elif choice == "5":
        return
    elif choice == "4":
        context.console.print("\n[bold]选择过滤模式:[/bold]")
        context.console.print("1. 全部过滤 (快讯 + 低分)")
        context.console.print("2. 仅过滤快讯")
        context.console.print("3. 仅过滤低分文章")
        context.console.print("4. 🔙 返回")

        m_choice = context.get_input("选择模式", default="1")
        if m_choice == "1":
            mode = "all"
        elif m_choice == "2":
            mode = "newsflash"
        elif m_choice == "3":
            mode = "low-score"
        else:
            return

        limit_str = context.get_input("文章抓取上限 (输入 0 为全量)", default=str(default_limit))
        try:
            limit = int(limit_str)
        except ValueError:
            limit = default_limit

        threshold = default_threshold
        if mode in ["all", "low-score"]:
            t_str = context.get_input("低分过滤阈值", default=str(default_threshold))
            try:
                threshold = float(t_str)
            except ValueError:
                threshold = default_threshold

        dr_str = context.get_input("是否仅模拟运行? (y/n)", default="n")
        dry_run = dr_str.lower().startswith("y")

        mark_read_str = context.get_input(
            "过滤后是否标记已读? (y/n)", default="y" if default_mark_read else "n"
        )
        mark_read = mark_read_str.lower().startswith("y")

        context.execute_filter(mode, limit, threshold, dry_run, mark_read=mark_read)
    else:
        context.console.print("[red]无效选项，请重新输入[/red]")


def execute_filter(
    context: CleanupContext,
    mode,
    limit,
    threshold,
    dry_run,
    mark_read,
    stream_id=None,
    stream_label=None,
):
    """Shared execution logic"""
    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    limit_display = format_limit_display(limit)
    mode_names = {
        "all": "全量清理 (快讯 + 低分过滤)",
        "newsflash": "仅过滤快讯 (36kr等)",
        "low-score": "仅过滤低分文章 (AI评分)",
    }
    mode_display = mode_names.get(mode, mode)
    context.console.print(
        Panel(
            f"清理模式: [bold]{mode_display}[/bold]\n"
            f"处理上限: {limit_display}\n"
            f"评分阈值: {threshold}\n"
            f"目标订阅源: {display_stream}\n"
            f"演练模式 (Dry Run): {'是 (仅模拟不修改)' if dry_run else '否 (实际标记)'}\n"
            f"标记已读: {'是' if mark_read else '否'}",
            title="执行配置 (Configuration)",
            border_style="blue",
        )
    )

    try:
        backend_service = context.load_backend_service()
        if backend_service is None:
            return

        result = backend_service.run_filter_workflow(
            mode=mode,
            limit=limit,
            threshold=threshold,
            dry_run=dry_run,
            mark_read=mark_read,
            stream_id=stream_id,
        )
        if result.get("error"):
            context.console.print(Panel(result["message"], style="red"))
            return

        if result["article_count"] == 0:
            context.console.print("[yellow]未找到符合条件的未读文章。[/yellow]")
            return

        context.console.print(
            Panel(
                "清理过滤完成！(Filter Run Complete)\n"
                f"过滤数量: {result['filtered_count']}\n"
                f"保留数量: {result['remaining_count']}",
                style="bold green",
            )
        )

    except KeyboardInterrupt:
        context.console.print("\n[red]操作已被用户取消。[/red]")
    except Exception:
        context.logger.exception("An error occurred during execution")
        context.console.print("[red]执行过程中发生异常，请检查上方日志。[/red]")


def run_filter_flow(context: CleanupContext):
    import questionary

    default_limit, default_threshold, default_mark_read = get_cleanup_defaults()
    limit_text = format_limit_display(default_limit)
    mark_text = "是" if default_mark_read else "否"

    # 1. Select Mode or Quick Run
    action = questionary.select(
        "清理未读文章 (Clean Up Unread):",
        choices=[
            questionary.Choice(
                f"⚡ 快速清理: 全规则过滤 (上限: {limit_text}, 评分 < {default_threshold}, 标记已读: {mark_text})",
                value="quick_all",
            ),
            questionary.Choice(
                f"⚡ 快速清理: 仅过滤快讯 (上限: {limit_text}, 标记已读: {mark_text})",
                value="quick_newsflash",
            ),
            questionary.Choice(
                f"⚡ 快速清理: 仅过滤低分 (上限: {limit_text}, 评分 < {default_threshold}, 标记已读: {mark_text})",
                value="quick_low_score",
            ),
            questionary.Choice(
                "🛠️ 自定义配置清理 (自定义上限、阈值、订阅源、演练模式等...)",
                value="custom",
            ),
            questionary.Choice("返回上一级 (Back)", value="back"),
        ],
    ).ask()

    if not action or action == "back":
        return

    if action == "quick_all":
        context.execute_filter(
            "all", default_limit, default_threshold, False, default_mark_read
        )
        return
    elif action == "quick_newsflash":
        context.execute_filter(
            "newsflash", default_limit, default_threshold, False, default_mark_read
        )
        return
    elif action == "quick_low_score":
        context.execute_filter(
            "low-score", default_limit, default_threshold, False, default_mark_read
        )
        return

    # If "custom", select filter mode then prompt parameters
    mode = questionary.select(
        "请选择清理过滤模式:",
        choices=[
            questionary.Choice("全规则过滤 (快讯过滤 + 低分过滤)", value="all"),
            questionary.Choice("仅过滤快讯 (36氪等简讯)", value="newsflash"),
            questionary.Choice("仅过滤低分文章 (AI 评分低于阈值)", value="low-score"),
            questionary.Choice("返回上一级 (Back)", value="back"),
        ],
    ).ask()

    if not mode or mode == "back":
        return

    # Configure Parameters
    limit_default_str = "0" if default_limit <= 0 else str(default_limit)
    limit_str = questionary.text(
        "文章数量上限 (0 或 'all' 表示全量未读):",
        default=limit_default_str,
    ).ask()
    if not limit_str or limit_str.strip().lower() in ("all", "0", "full"):
        limit = 0
    else:
        try:
            limit = int(limit_str)
        except ValueError:
            context.console.print(f"[red]无效的数字，使用默认值 {limit_default_str}[/red]")
            limit = default_limit

    threshold = default_threshold
    if mode in ["all", "low-score"]:
        threshold_str = questionary.text(
            "评分过滤阈值 (Score Threshold):", default=str(default_threshold)
        ).ask()
        try:
            threshold = float(threshold_str)
        except ValueError:
            context.console.print(f"[red]无效的阈值，使用默认值 {default_threshold}[/red]")
            threshold = default_threshold

    dry_run = questionary.confirm(
        "是否为演练模式 (Dry Run - 仅模拟不实际修改)?:", default=False
    ).ask()

    # Stream Selection
    stream_id = None
    stream_label = None
    use_stream = questionary.confirm(
        "是否指定特定分类/订阅源 (默认全局所有)?:", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = context.select_stream_interactive()

    # Execution
    mark_read = questionary.confirm(
        "清理完成后是否在 Feedly 标记为已读?:", default=default_mark_read
    ).ask()

    context.execute_filter(
        mode,
        limit,
        threshold,
        dry_run,
        mark_read,
        stream_id,
        stream_label,
    )
