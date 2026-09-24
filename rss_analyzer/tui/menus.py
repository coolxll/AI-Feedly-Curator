"""Main and fallback menu routing for the Feedly TUI."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from rich.panel import Panel

from rss_analyzer.config import PROJ_CONFIG, get_openai_task_config
from rss_analyzer.tui.support import format_limit_display


@dataclass(frozen=True)
class MenuContext:
    console: object
    get_input: Callable[..., str]
    get_review_defaults: Callable[[], tuple[int, int, int]]
    simple_filter_flow: Callable[[], object]
    execute_process_stream: Callable[..., object]
    execute_batch_read: Callable[..., object]
    execute_analyze: Callable[..., object]
    execute_export: Callable[..., object]
    run_filter_flow: Callable[[], object]
    run_summary_flow: Callable[[], object]
    run_analyze_flow: Callable[[], object]
    run_export_flow: Callable[[], object]
    run_process_stream_flow: Callable[[], object]
    run_batch_read_flow: Callable[[], object]


def render_main_header(context: MenuContext):
    analysis_model = get_openai_task_config(
        "analysis", default_model="gpt-4o-mini"
    ).model
    summary_model = get_openai_task_config(
        "summary", default_model="gpt-4o-mini"
    ).model
    context.console.print(
        Panel.fit(
            (
                "Feedly AI Curator / 智能阅读与清理终端\n"
                f"[dim]评分模型 (analysis):[/dim] {analysis_model}\n"
                f"[dim]总结模型 (summary):[/dim] {summary_model}"
            ),
            style="bold cyan",
            subtitle="交互式终端 (TUI)",
        )
    )


def get_input(prompt_text, default=None):
    """Fallback input helper"""
    p = f"{prompt_text} "
    if default:
        p += f"[{default}]: "
    else:
        p += ": "

    val = input(p).strip()
    if not val and default:
        return default
    return val


def simple_menu(context: MenuContext):
    """Fallback menu using standard input"""
    context.console.clear()
    context.console.print(
        Panel.fit(
            "Feedly AI Curator (基础简易模式)", style="bold cyan", subtitle="控制台交互"
        )
    )

    while True:
        context.console.print("\n[bold]主菜单 (Main Menu):[/bold]")
        context.console.print("1. 📖 未读速览与清理 (Review Unread)")
        context.console.print("2. 🧹 低分与快讯过滤 (Clean Up Unread)")
        context.console.print("3. 📊 深度分析与综合报告 (Analyze & Reports)")
        context.console.print("4. 💾 导出未读文章为 JSON (Export Unread JSON)")
        context.console.print("5. 🚪 退出程序 (Exit)")

        choice = context.get_input("请选择操作序号", default="1")

        if choice == "5":
            context.console.print("[cyan]感谢使用，再见！[/cyan]")
            sys.exit()
        elif choice == "1":
            simple_review_menu(context)
        elif choice == "2":
            context.simple_filter_flow()
        elif choice == "3":
            simple_reports_menu(context)
        elif choice == "4":
            simple_export_flow(context)
        else:
            context.console.print("[red]无效选项，请重新输入[/red]")


def simple_review_menu(context: MenuContext):
    default_limit, default_days, default_chunk = context.get_review_defaults()
    limit_text = format_limit_display(default_limit)
    while True:
        context.console.print("\n[bold]未读速览与清理 (Review Unread):[/bold]")
        context.console.print(
            f"1. ⚡ 一键雷达全景速览 (全局所有订阅, 上限: {limit_text}, 近 {default_days} 天)"
        )
        context.console.print(
            f"2. ⚡ 一键分批逐步清理 (全局所有订阅, 每批: {default_chunk} 篇, 近 {default_days} 天)"
        )
        context.console.print("3. 🛠 自定义雷达速览")
        context.console.print("4. 🛠 自定义分批清理")
        context.console.print("5. 🔙 返回主菜单")
        choice = context.get_input("请选择操作序号", default="1")
        if choice == "1":
            context.execute_process_stream(
                stream_id=None,
                limit=default_limit if default_limit > 0 else 9999,
                days=default_days,
                stream_label="Global All",
            )
        elif choice == "2":
            context.execute_batch_read(
                stream_id=None,
                stream_label="Global All",
                batch_size=default_chunk,
                days=default_days,
            )
        elif choice == "3":
            simple_process_stream_flow(context)
        elif choice == "4":
            context.run_batch_read_flow()
        elif choice == "5":
            return
        else:
            context.console.print("[red]无效选项，请重新输入[/red]")


def simple_reports_menu(context: MenuContext):
    while True:
        context.console.print("\n[bold]深度分析与综合报告 (Analyze & Reports):[/bold]")
        context.console.print("1. ⚡ 一键全量分析与总结 (上限: 100 篇, 强制刷新, 并发: 3)")
        context.console.print("2. 🛠 自定义全量分析与报告")
        context.console.print("3. 📋 重新生成总结报告 (基于已有分析数据)")
        context.console.print("4. 🔙 返回主菜单")
        choice = context.get_input("请选择操作序号", default="1")
        if choice == "1":
            context.execute_analyze(
                limit=100, refresh=True, mark_read=False, stream_id=None, threads=3
            )
        elif choice == "2":
            simple_analyze_flow(context)
        elif choice == "3":
            context.run_summary_flow()
        elif choice == "4":
            return
        else:
            context.console.print("[red]无效选项，请重新输入[/red]")


def simple_analyze_flow(context: MenuContext):
    """Fallback analyze flow"""
    context.console.print("\n[bold]全量分析与总结配置:[/bold]")

    limit_str = context.get_input("文章抓取上限 (Article Limit)", default="100")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    refresh_str = context.get_input("是否从 Feedly 拉取最新文章? (y/n)", default="y")
    refresh = refresh_str.lower().startswith("y")

    stream_id = None
    if refresh:
        sid = context.get_input("指定 Stream ID (可选，直接回车使用全局订阅)", default="")
        if sid:
            stream_id = sid

    default_mark = "y" if PROJ_CONFIG.get("mark_read") else "n"
    mark_read_str = context.get_input(
        "分析完成后是否在 Feedly 标记为已读? (y/n)", default=default_mark
    )
    mark_read = mark_read_str.lower().startswith("y")

    threads_str = context.get_input("并发分析线程数 (默认: 3)", default="3")
    try:
        threads = int(threads_str)
    except ValueError:
        threads = 3

    context.execute_analyze(limit, refresh, mark_read, stream_id, threads)


def simple_export_flow(context: MenuContext):
    """Fallback export flow"""
    context.console.print("\n[bold]导出未读文章配置:[/bold]")

    sid = context.get_input("指定 Stream ID (可选，直接回车使用全局订阅)", default="")
    stream_id = sid if sid else None

    limit_str = context.get_input("导出数量上限 (输入 0 为全量未读)", default="100")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    from datetime import datetime

    default_filename = f"output/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename = context.get_input("导出文件路径", default=default_filename)

    context.execute_export(limit, stream_id, filename)


def simple_process_stream_flow(context: MenuContext):
    default_limit, default_days, _ = context.get_review_defaults()
    context.console.print("\n[bold]Quick Review Stream:[/bold]")
    sid = context.get_input("Stream ID (Optional, press Enter for Global)", default="")
    stream_id = sid if sid else None

    limit_default_str = "0" if default_limit <= 0 else str(default_limit)
    limit_str = context.get_input(
        "Limit (0 or 'all' for full unread)", default=limit_default_str
    )
    if not limit_str or limit_str.strip().lower() in ("all", "0", "full"):
        limit = 0
    else:
        try:
            limit = int(limit_str)
        except ValueError:
            limit = default_limit

    days_str = context.get_input("Recent Days", default=str(default_days))
    try:
        days = int(days_str)
    except ValueError:
        days = default_days

    context.execute_process_stream(
        stream_id,
        limit=limit if limit > 0 else 9999,
        days=days,
        stream_label="Global All" if not stream_id else None,
    )


def pause_and_render_main_header(context: MenuContext) -> None:
    input("\nPress Enter to return to menu...")
    context.console.clear()
    render_main_header(context)


def main_menu(context: MenuContext):
    """Fancy menu using questionary"""
    try:
        import questionary

        # Test if we can access the prompt session (catch NoConsoleScreenBufferError)
        import prompt_toolkit  # noqa: F401
    except ImportError:
        simple_menu(context)
        return

    context.console.clear()
    render_main_header(context)

    while True:
        action = questionary.select(
            "请选择操作 (What would you like to do?):",
            choices=[
                questionary.Choice("1. 📖 未读速览与清理 (Review Unread)", value="review"),
                questionary.Choice("2. 🧹 低分与快讯过滤 (Clean Up Unread)", value="cleanup"),
                questionary.Choice("3. 📊 深度分析与综合报告 (Analyze & Reports)", value="reports"),
                questionary.Choice("4. 💾 导出未读文章为 JSON (Export Unread JSON)", value="export"),
                questionary.Choice("5. 🚪 退出程序 (Exit)", value="exit"),
            ],
            style=questionary.Style(
                [
                    ("qmark", "fg:cyan bold"),
                    ("question", "fg:cyan bold"),
                    ("answer", "fg:green bold"),
                    ("pointer", "fg:cyan bold"),
                    ("highlighted", "fg:cyan bold"),
                    ("selected", "fg:green bold"),
                ]
            ),
        ).ask()

        if action == "exit":
            context.console.print("[cyan]感谢使用，再见！[/cyan]")
            sys.exit()
        elif action == "review":
            run_review_menu(context)
            pause_and_render_main_header(context)
        elif action == "cleanup":
            context.run_filter_flow()
            pause_and_render_main_header(context)
        elif action == "reports":
            run_reports_menu(context)
            pause_and_render_main_header(context)
        elif action == "export":
            context.run_export_flow()
            pause_and_render_main_header(context)


def run_review_menu(context: MenuContext):
    import questionary

    default_limit, default_days, default_chunk = context.get_review_defaults()
    limit_text = format_limit_display(default_limit)

    action = questionary.select(
        "未读速览与清理 (Review Unread):",
        choices=[
            questionary.Choice(
                f"⚡ 一键雷达全景速览 (全局所有订阅, 上限: {limit_text}, 近 {default_days} 天)",
                value="quick_default",
            ),
            questionary.Choice(
                f"⚡ 一键分批逐步清理 (全局所有订阅, 每批: {default_chunk} 篇, 近 {default_days} 天)",
                value="batch_default",
            ),
            questionary.Choice(
                "🛠 自定义雷达速览 (选择订阅/分类, 自定义上限与天数)...",
                value="quick_custom",
            ),
            questionary.Choice(
                "🛠 自定义分批清理 (选择订阅/分类, 自定义每批数量与天数)...",
                value="batch_custom",
            ),
            questionary.Choice("🔙 返回主菜单 (Back)", value="back"),
        ],
    ).ask()

    if not action or action == "back":
        return

    if action in ("quick_default", "quick_all"):
        context.execute_process_stream(
            stream_id=None,
            limit=default_limit if default_limit > 0 else 9999,
            days=default_days,
            stream_label="Global All",
        )
    elif action in ("batch_default", "batch_all"):
        context.execute_batch_read(
            stream_id=None,
            stream_label="Global All",
            batch_size=default_chunk,
            days=default_days,
        )
    elif action in ("quick_custom", "quick"):
        context.run_process_stream_flow()
    elif action in ("batch_custom", "batch"):
        context.run_batch_read_flow()


def run_reports_menu(context: MenuContext):
    import questionary

    action = questionary.select(
        "深度分析与综合报告 (Analyze & Reports):",
        choices=[
            questionary.Choice(
                "⚡ 一键全量深度分析 (上限: 100 篇, 强制刷新, 全局订阅, 并发: 3)",
                value="quick_analyze",
            ),
            questionary.Choice("🛠 自定义深度分析与报告 (自定义上限、订阅源、标记已读等)...", value="analyze"),
            questionary.Choice("📋 重新生成总结报告 (基于已有分析数据，无需重复调大模型打分)", value="summary"),
            questionary.Choice("🔙 返回主菜单 (Back)", value="back"),
        ],
    ).ask()

    if action == "quick_analyze":
        context.execute_analyze(
            limit=100, refresh=True, mark_read=False, stream_id=None, threads=3
        )
    elif action == "analyze":
        context.run_analyze_flow()
    elif action == "summary":
        context.run_summary_flow()
