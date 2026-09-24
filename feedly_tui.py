#!/usr/bin/env python3
"""
AI-Feedly-Curator TUI Runner
Interactive menu for running Feedly filters.
"""

import sys
import logging
import os
import webbrowser
from rss_analyzer.config import (
    LATEST_ANALYZED_FILE,
    PROJ_CONFIG,
    get_openai_task_config,
)
from rss_analyzer.feedly_client import (
    feedly_get_categories,
    feedly_get_subscriptions,
    feedly_get_unread_counts,
)
from rss_analyzer.utils import load_articles
from rss_analyzer.tui.support import (
    filter_articles_by_titles,
    format_limit_display as _format_limit_display,
    get_cleanup_defaults as _get_cleanup_defaults,
    get_review_defaults as _get_review_defaults,
    import_error_hint as _import_error_hint,
    resolve_export_path,
    resolve_stream_feed_titles,
)
from rss_analyzer.tui.stream_selection import (
    GLOBAL_STREAM_SENTINEL,
    select_stream_interactive as _select_stream_interactive,
)
from rich.console import Console
from rich.panel import Panel
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback

# Configure Rich Tracebacks
install_rich_traceback()

# Re-configure logging to use RichHandler
log_level_str = os.environ.get("RSS_NATIVE_LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False)],
    force=True,
)

console = Console()
logger = logging.getLogger("tui")
def render_main_header():
    analysis_model = get_openai_task_config(
        "analysis", default_model="gpt-4o-mini"
    ).model
    summary_model = get_openai_task_config(
        "summary", default_model="gpt-4o-mini"
    ).model
    console.print(
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


def _maybe_reexec_in_project_venv() -> None:
    """Re-exec into the project's .venv interpreter if present.

    This avoids requiring users to manually activate the venv when launching a
    terminal via right-click/open-in-terminal.
    """
    if os.environ.get("RSS_OPML_SKIP_VENV") == "1":
        return
    if os.environ.get("RSS_OPML_VENV_REEXEC") == "1":
        return
    if sys.prefix != sys.base_prefix:
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_name = os.environ.get("UV_PROJECT_ENVIRONMENT")
    if not venv_name:
        if sys.platform == "win32":
            venv_name = ".venv-win" if os.path.exists(os.path.join(script_dir, ".venv-win")) else ".venv"
        else:
            venv_name = ".venv-wsl" if os.path.exists(os.path.join(script_dir, ".venv-wsl")) else ".venv"

    candidates = [
        os.path.join(script_dir, venv_name, "Scripts", "python.exe"),  # Windows
        os.path.join(script_dir, venv_name, "bin", "python"),  # POSIX
    ]

    current = os.path.abspath(sys.executable)
    for venv_py in candidates:
        if os.path.exists(venv_py) and os.path.abspath(venv_py) != current:
            env = os.environ.copy()
            env["RSS_OPML_VENV_REEXEC"] = "1"
            os.execve(venv_py, [venv_py] + sys.argv, env)


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


def simple_menu():
    """Fallback menu using standard input"""
    console.clear()
    console.print(
        Panel.fit(
            "Feedly AI Curator (基础简易模式)", style="bold cyan", subtitle="控制台交互"
        )
    )

    while True:
        console.print("\n[bold]主菜单 (Main Menu):[/bold]")
        console.print("1. 📖 未读速览与清理 (Review Unread)")
        console.print("2. 🧹 低分与快讯过滤 (Clean Up Unread)")
        console.print("3. 📊 深度分析与综合报告 (Analyze & Reports)")
        console.print("4. 💾 导出未读文章为 JSON (Export Unread JSON)")
        console.print("5. 🚪 退出程序 (Exit)")

        choice = get_input("请选择操作序号", default="1")

        if choice == "5":
            console.print("[cyan]感谢使用，再见！[/cyan]")
            sys.exit()
        elif choice == "1":
            simple_review_menu()
        elif choice == "2":
            simple_filter_flow()
        elif choice == "3":
            simple_reports_menu()
        elif choice == "4":
            simple_export_flow()
        else:
            console.print("[red]无效选项，请重新输入[/red]")


def simple_review_menu():
    default_limit, default_days, default_chunk = _get_review_defaults()
    limit_text = _format_limit_display(default_limit)
    while True:
        console.print("\n[bold]未读速览与清理 (Review Unread):[/bold]")
        console.print(
            f"1. ⚡ 一键雷达全景速览 (全局所有订阅, 上限: {limit_text}, 近 {default_days} 天)"
        )
        console.print(
            f"2. ⚡ 一键分批逐步清理 (全局所有订阅, 每批: {default_chunk} 篇, 近 {default_days} 天)"
        )
        console.print("3. 🛠 自定义雷达速览")
        console.print("4. 🛠 自定义分批清理")
        console.print("5. 🔙 返回主菜单")
        choice = get_input("请选择操作序号", default="1")
        if choice == "1":
            execute_process_stream(
                stream_id=None,
                limit=default_limit if default_limit > 0 else 9999,
                days=default_days,
                stream_label="Global All",
            )
        elif choice == "2":
            execute_batch_read(
                stream_id=None,
                stream_label="Global All",
                batch_size=default_chunk,
                days=default_days,
            )
        elif choice == "3":
            simple_process_stream_flow()
        elif choice == "4":
            run_batch_read_flow()
        elif choice == "5":
            return
        else:
            console.print("[red]无效选项，请重新输入[/red]")


def simple_reports_menu():
    while True:
        console.print("\n[bold]深度分析与综合报告 (Analyze & Reports):[/bold]")
        console.print("1. ⚡ 一键全量分析与总结 (上限: 100 篇, 强制刷新, 并发: 3)")
        console.print("2. 🛠 自定义全量分析与报告")
        console.print("3. 📋 重新生成总结报告 (基于已有分析数据)")
        console.print("4. 🔙 返回主菜单")
        choice = get_input("请选择操作序号", default="1")
        if choice == "1":
            execute_analyze(
                limit=100, refresh=True, mark_read=False, stream_id=None, threads=3
            )
        elif choice == "2":
            simple_analyze_flow()
        elif choice == "3":
            run_summary_flow()
        elif choice == "4":
            return
        else:
            console.print("[red]无效选项，请重新输入[/red]")


def simple_analyze_flow():
    """Fallback analyze flow"""
    console.print("\n[bold]全量分析与总结配置:[/bold]")

    limit_str = get_input("文章抓取上限 (Article Limit)", default="100")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    refresh_str = get_input("是否从 Feedly 拉取最新文章? (y/n)", default="y")
    refresh = refresh_str.lower().startswith("y")

    stream_id = None
    if refresh:
        sid = get_input("指定 Stream ID (可选，直接回车使用全局订阅)", default="")
        if sid:
            stream_id = sid

    default_mark = "y" if PROJ_CONFIG.get("mark_read") else "n"
    mark_read_str = get_input(
        "分析完成后是否在 Feedly 标记为已读? (y/n)", default=default_mark
    )
    mark_read = mark_read_str.lower().startswith("y")

    threads_str = get_input("并发分析线程数 (默认: 3)", default="3")
    try:
        threads = int(threads_str)
    except ValueError:
        threads = 3

    execute_analyze(limit, refresh, mark_read, stream_id, threads)


def simple_export_flow():
    """Fallback export flow"""
    console.print("\n[bold]导出未读文章配置:[/bold]")

    sid = get_input("指定 Stream ID (可选，直接回车使用全局订阅)", default="")
    stream_id = sid if sid else None

    limit_str = get_input("导出数量上限 (输入 0 为全量未读)", default="100")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    from datetime import datetime

    default_filename = f"output/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename = get_input("导出文件路径", default=default_filename)

    execute_export(limit, stream_id, filename)


def simple_process_stream_flow():
    default_limit, default_days, _ = _get_review_defaults()
    console.print("\n[bold]Quick Review Stream:[/bold]")
    sid = get_input("Stream ID (Optional, press Enter for Global)", default="")
    stream_id = sid if sid else None

    limit_default_str = "0" if default_limit <= 0 else str(default_limit)
    limit_str = get_input(
        "Limit (0 or 'all' for full unread)", default=limit_default_str
    )
    if not limit_str or limit_str.strip().lower() in ("all", "0", "full"):
        limit = 0
    else:
        try:
            limit = int(limit_str)
        except ValueError:
            limit = default_limit

    days_str = get_input("Recent Days", default=str(default_days))
    try:
        days = int(days_str)
    except ValueError:
        days = default_days

    execute_process_stream(
        stream_id,
        limit=limit if limit > 0 else 9999,
        days=days,
        stream_label="Global All" if not stream_id else None,
    )


def run_export_flow():
    """Interactive export flow"""
    import questionary
    from datetime import datetime

    # 1. Select Stream
    use_stream = questionary.confirm(
        "是否指定特定分类或订阅源 (默认导出全局所有)?", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = select_stream_interactive()
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

    execute_export(limit, stream_id, filename, stream_label)



def execute_export(limit, stream_id, filename, stream_label=None):
    filename = resolve_export_path(filename)
    display_stream = stream_label if stream_label else (stream_id or "Global All (全局所有)")
    limit_display = "All (全量)" if limit == 0 else str(limit)
    console.print(
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
        backend_service = _load_backend_service()
        if backend_service is None:
            return

        result = backend_service.export_articles(
            limit=limit,
            output_file=filename,
            stream_id=stream_id,
        )
        if result.get("error"):
            console.print(Panel(result["message"], style="red"))
            return

        console.print(
            Panel(f"导出完成！已成功保存至 {filename}", style="bold green")
        )
    except Exception:
        logger.exception("Error exporting")
        console.print("[red]导出失败，请检查日志。[/red]")



def simple_filter_flow():
    """Fallback filter flow"""
    default_limit, default_threshold, default_mark_read = _get_cleanup_defaults()
    limit_text = _format_limit_display(default_limit)
    mark_text = "是" if default_mark_read else "否"
    console.print("\n[bold]低分与快讯批量过滤 (Clean Up Unread):[/bold]")
    console.print(
        f"1. ⚡ 一键全量过滤 (快讯 + 低分 < {default_threshold}, 篇数: {limit_text}, 自动标已读: {mark_text})"
    )
    console.print(
        f"2. ⚡ 一键快讯过滤 (仅 36kr 7x24 短讯, 篇数: {limit_text}, 自动标已读: {mark_text})"
    )
    console.print(
        f"3. ⚡ 一键低分过滤 (仅 AI 评分 < {default_threshold}, 篇数: {limit_text}, 自动标已读: {mark_text})"
    )
    console.print("4. 🛠 自定义过滤配置")
    console.print("5. 🔙 返回主菜单")

    choice = get_input("请选择操作序号", default="1")

    if choice == "1":
        execute_filter(
            "all", default_limit, default_threshold, False, mark_read=default_mark_read
        )
        return
    elif choice == "2":
        execute_filter(
            "newsflash",
            default_limit,
            default_threshold,
            False,
            mark_read=default_mark_read,
        )
        return
    elif choice == "3":
        execute_filter(
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
        console.print("\n[bold]选择过滤模式:[/bold]")
        console.print("1. 全部过滤 (快讯 + 低分)")
        console.print("2. 仅过滤快讯")
        console.print("3. 仅过滤低分文章")
        console.print("4. 🔙 返回")

        m_choice = get_input("选择模式", default="1")
        if m_choice == "1":
            mode = "all"
        elif m_choice == "2":
            mode = "newsflash"
        elif m_choice == "3":
            mode = "low-score"
        else:
            return

        limit_str = get_input("文章抓取上限 (输入 0 为全量)", default=str(default_limit))
        try:
            limit = int(limit_str)
        except ValueError:
            limit = default_limit

        threshold = default_threshold
        if mode in ["all", "low-score"]:
            t_str = get_input("低分过滤阈值", default=str(default_threshold))
            try:
                threshold = float(t_str)
            except ValueError:
                threshold = default_threshold

        dr_str = get_input("是否仅模拟运行? (y/n)", default="n")
        dry_run = dr_str.lower().startswith("y")

        mark_read_str = get_input(
            "过滤后是否标记已读? (y/n)", default="y" if default_mark_read else "n"
        )
        mark_read = mark_read_str.lower().startswith("y")

        execute_filter(mode, limit, threshold, dry_run, mark_read=mark_read)
    else:
        console.print("[red]无效选项，请重新输入[/red]")


def select_stream_interactive():
    return _select_stream_interactive(
        console=console,
        get_categories=feedly_get_categories,
        get_subscriptions=feedly_get_subscriptions,
        get_unread_counts=feedly_get_unread_counts,
    )





def _load_backend_service():
    try:
        from rss_analyzer import backend_service
    except Exception as e:
        console.print(Panel(_import_error_hint("rss_analyzer.backend_service", e), style="red"))
        return None

    return backend_service


def _verify_startup_dependencies_or_exit() -> None:
    """Fail-fast dependency check.

    User preference: if LLM-related deps are broken (often due to Python upgrades
    making binary wheels like pydantic-core/jiter incompatible), show a clear
    message and exit before entering the menu.
    """
    # Importing these modules is enough to trigger the common failure modes.
    # Keep the import list minimal and aligned with the plan.
    required = ["rss_analyzer.backend_service"]

    for mod in required:
        try:
            __import__(mod)
        except Exception as e:
            console.print(Panel(_import_error_hint(mod, e), style="red"))
            raise SystemExit(1)


def _pause_and_render_main_header() -> None:
    input("\nPress Enter to return to menu...")
    console.clear()
    render_main_header()


def main_menu():
    """Fancy menu using questionary"""
    try:
        import questionary

        # Test if we can access the prompt session (catch NoConsoleScreenBufferError)
        import prompt_toolkit  # noqa: F401
    except ImportError:
        simple_menu()
        return

    console.clear()
    render_main_header()

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
            console.print("[cyan]感谢使用，再见！[/cyan]")
            sys.exit()
        elif action == "review":
            run_review_menu()
            _pause_and_render_main_header()
        elif action == "cleanup":
            run_filter_flow()
            _pause_and_render_main_header()
        elif action == "reports":
            run_reports_menu()
            _pause_and_render_main_header()
        elif action == "export":
            run_export_flow()
            _pause_and_render_main_header()


def run_review_menu():
    import questionary

    default_limit, default_days, default_chunk = _get_review_defaults()
    limit_text = _format_limit_display(default_limit)

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
        execute_process_stream(
            stream_id=None,
            limit=default_limit if default_limit > 0 else 9999,
            days=default_days,
            stream_label="Global All",
        )
    elif action in ("batch_default", "batch_all"):
        execute_batch_read(
            stream_id=None,
            stream_label="Global All",
            batch_size=default_chunk,
            days=default_days,
        )
    elif action in ("quick_custom", "quick"):
        run_process_stream_flow()
    elif action in ("batch_custom", "batch"):
        run_batch_read_flow()


def run_reports_menu():
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
        execute_analyze(
            limit=100, refresh=True, mark_read=False, stream_id=None, threads=3
        )
    elif action == "analyze":
        run_analyze_flow()
    elif action == "summary":
        run_summary_flow()


def run_summary_flow():
    try:
        import questionary
    except ImportError:
        console.print(Panel("正在生成总结报告...", style="bold blue"))
        try:
            backend_service = _load_backend_service()
            if backend_service is None:
                return

            result = backend_service.regenerate_summary()
            if result.get("error"):
                console.print(Panel(result["message"], style="red"))
                return

            console.print(Panel("总结报告生成完成！", style="bold green"))
        except Exception:
            logger.exception("Error generating summary")
            console.print("[red]生成总结报告失败。[/red]")
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
        stream_id, stream_label = select_stream_interactive()
        if stream_id is None and stream_label is None:
            return
    else:
        stream_id = None
        stream_label = "Global All"

    if mode == "local":
        console.print(Panel("Summarizing Local Articles...", style="bold blue"))
        try:
            console.print(f"[dim]Loading {LATEST_ANALYZED_FILE}...[/dim]")
            articles = load_articles(LATEST_ANALYZED_FILE)

            if stream_id:
                console.print("[dim]Resolving selected stream...[/dim]")
                titles = resolve_stream_feed_titles(stream_id)
                if titles is None:
                    console.print(
                        "[yellow]Unable to resolve stream to feeds. Using all local articles.[/yellow]"
                    )
                articles = filter_articles_by_titles(articles, titles)

            if not articles:
                console.print("[yellow]No articles matched the selection.[/yellow]")
                return

            backend_service = _load_backend_service()
            if backend_service is None:
                return

            result = backend_service.generate_summary_report(articles)
            console.print(
                Panel(
                    "总结报告生成完成！(Summary Generation Complete)\n"
                    f"- 报告文件: {result['summary_file']}\n"
                    f"- 最新报告: {result['latest_summary_file']}",
                    style="bold green",
                )
            )
        except Exception:
            logger.exception("Error generating summary")
            console.print("[red]生成总结报告失败。[/red]")
        return

    # refresh mode
    limit_str = questionary.text("文章数量上限 (Article Limit):", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        console.print("[red]无效的数字，使用默认值 100[/red]")
        limit = 100

    mark_read = questionary.confirm(
        "分析完成后是否在 Feedly 标记为已读 (Mark as read)?:",
        default=PROJ_CONFIG.get("mark_read", False),
    ).ask()

    execute_analyze(limit, True, mark_read, stream_id, 3, stream_label)


def run_analyze_flow():
    """Interactive analyze flow using questionary"""
    import questionary

    # Configure parameters
    limit_str = questionary.text("文章数量上限 (Article Limit):", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        console.print("[red]无效的数字，使用默认值 100[/red]")
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
            stream_id, stream_label = select_stream_interactive()

    mark_read = questionary.confirm(
        "分析完成后是否在 Feedly 标记为已读 (Mark as read)?:",
        default=PROJ_CONFIG.get("mark_read", False),
    ).ask()

    threads_str = questionary.text("并发分析线程数 (Threads):", default="3").ask()
    try:
        threads = int(threads_str)
    except ValueError:
        console.print("[red]无效的线程数，使用默认值 3[/red]")
        threads = 3

    execute_analyze(limit, refresh, mark_read, stream_id, threads, stream_label)


def _render_stream_result(result):
    digest = result.get("digest") or {}
    stats = digest.get("stats", {})
    console.print(
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
        console.print("\n[bold]今日重点主题[/bold]")
        for group in theme_groups[:8]:
            console.print(
                f"- [cyan]{group['bucket']}[/cyan] ({group['count']}) - {group['summary']}"
            )

    p2_briefing = digest.get("p2_briefing") or {}
    p2_items = p2_briefing.get("must_read") or p2_briefing.get("items") or []
    if p2_briefing:
        console.print("\n[bold]P2 快速情报[/bold]")
        console.print(f"- {p2_briefing.get('headline', 'No P2 items.')}")
        for item in p2_items[:8]:
            score = item.get("score")
            score_text = f" [{score}/5.0]" if score is not None else ""
            console.print(f"- {item.get('event') or item.get('title')}{score_text}")
            if item.get("actors") or item.get("region"):
                console.print(
                    f"  [dim]相关方:[/dim] {item.get('actors', '')} "
                    f"[dim]地区:[/dim] {item.get('region', '')}"
                )
            if item.get("core_fact"):
                console.print(f"  [dim]事实:[/dim] {item['core_fact']}")
            if item.get("why_it_matters"):
                console.print(f"  [dim]影响:[/dim] {item['why_it_matters']}")
            if item.get("link"):
                console.print(f"  [dim]链接:[/dim] {item['link']}")

    must_read = digest.get("deep_analyzed_reads") or digest.get(
        "must_read_candidates", result.get("worth_expanding_items", [])
    )
    console.print("\n[bold]必须读[/bold]")
    if must_read:
        for item in must_read:
            console.print(f"- {item['title']}")
            if item.get("link"):
                console.print(f"  [dim]链接:[/dim] {item['link']}")
            if item.get("analysis_summary"):
                console.print(f"  [dim]分析:[/dim] {item['analysis_summary']}")
            elif item.get("interpretation"):
                console.print(f"  [dim]解读:[/dim] {item['interpretation']}")
            if item.get("score") is not None:
                console.print(f"  [dim]评分:[/dim] {item['score']}/5.0")
    else:
        console.print("- None")

    skim_items = digest.get("skim_items", [])
    console.print("\n[bold]可略读[/bold]")
    if skim_items:
        for item in skim_items[:8]:
            console.print(f"- {item['title']}")
            if item.get("link"):
                console.print(f"  [dim]链接:[/dim] {item['link']}")
            if item.get("interpretation"):
                console.print(f"  [dim]解读:[/dim] {item['interpretation']}")
    else:
        console.print("- None")

    clear_items = digest.get("clear_items", result.get("low_priority_items", []))
    console.print("\n[bold]可速清[/bold]")
    if clear_items:
        for item in clear_items[:10]:
            console.print(f"- {item['title']}")
        if len(clear_items) > 10:
            console.print(f"[dim]... and {len(clear_items) - 10} more[/dim]")
    else:
        console.print("- None")

    actions = digest.get("actions", [])
    if actions:
        console.print("\n[bold]建议动作[/bold]")
        for action in actions:
            console.print(f"- {action}")

    if stats:
        console.print(
            f"\n[dim]候选 {stats.get('candidate_count', 0)} | "
            f"must-read {stats.get('must_read_count', 0)} | "
            f"skim {stats.get('skim_count', 0)} | "
            f"clear {stats.get('clear_count', 0)}[/dim]"
        )
        if "llm_chunk_count" in stats:
            console.print(
                f"[dim]LLM chunks {stats.get('llm_chunk_count', 0)} "
                f"(size {stats.get('llm_chunk_size', 0)}) | "
                f"uncached {stats.get('triage_uncached_count', 0)} | "
                f"cached {stats.get('triage_cached_count', 0)} | "
                f"fallback {stats.get('fallback_chunk_count', 0)}[/dim]"
            )


def _open_stream_article(article: dict) -> bool:
    link = article.get("link")
    if not link:
        console.print("[red]Selected article does not have a link.[/red]")
        return False

    try:
        return bool(webbrowser.open(link))
    except Exception:
        logger.exception("Failed to open article link")
        return False


def _prompt_open_stream_article(digest):
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

    if _open_stream_article(selected):
        console.print(f"[green]已在浏览器打开:[/green] {selected['title']}")
    else:
        console.print("[red]打开文章链接失败。[/red]")


def _loop_open_articles(digest):
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
        console.print("[yellow]没有包含有效链接的文章可打开。[/yellow]")
        return

    # Build a label->item map since questionary.Choice value may not
    # round-trip dicts reliably.
    opened_links: set[str] = set()

    while True:
        remaining = [
            (s, i) for s, i in openable_items if i.get("link") not in opened_links
        ]
        if not remaining:
            console.print("[dim]本批次推荐文章已全部在浏览器中打开。[/dim]")
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

        if _open_stream_article(item):
            opened_links.add(item["link"])
            console.print(f"[green]已在浏览器打开:[/green] {item['title']}")
        else:
            console.print("[red]打开文章链接失败。[/red]")


def run_batch_read_flow():
    """Batch reading mode: fetch N articles, AI filter, read, mark, repeat."""
    import questionary

    _, default_days, default_chunk = _get_review_defaults()

    use_stream = questionary.confirm(
        "是否指定特定分类/订阅源 (默认全局所有)?:", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = select_stream_interactive()
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
        stream_id,
        stream_label=stream_label,
        batch_size=batch_size,
        days=days,
    )


def execute_batch_read(stream_id, stream_label=None, batch_size=50, days=3):
    import questionary

    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    console.print(
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
        backend = _load_backend_service()
        if backend is None:
            return

        batch_num = 0
        total_marked = 0

        while True:
            batch_num += 1
            console.print(f"\n[bold cyan]━━━ 第 {batch_num} 批 (Batch #{batch_num}) ━━━[/bold cyan]")

            result = backend.process_batch(
                stream_id=stream_id,
                stream_label=stream_label,
                batch_size=batch_size,
                days=days,
            )

            fetched = result.get("fetched_count", 0)
            if fetched == 0:
                console.print("[green]✓ 所有未读文章已处理完毕！[/green]")
                break

            _render_stream_result(result)

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
                    _loop_open_articles(digest)
                elif action == "mark_clear":
                    if mark_read_ids:
                        mark_result = backend.mark_articles_read(mark_read_ids)
                        if mark_result.get("success"):
                            console.print(
                                f"[green]已成功标记 {mark_result['marked_count']} 篇低优先级文章为已读。[/green]"
                            )
                            total_marked += mark_result["marked_count"]
                        else:
                            console.print("[red]标记已读失败。[/red]")
                    else:
                        console.print("[yellow]本批次无低优先级文章需要标记。[/yellow]")
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
                            console.print(
                                f"[green]已成功标记本批全部 {mark_result['marked_count']} 篇文章为已读。[/green]"
                            )
                            total_marked += mark_result["marked_count"]
                        else:
                            console.print("[red]标记已读失败。[/red]")
                    break  # move to next batch after marking all
                elif action == "next":
                    break
                elif action == "exit":
                    console.print(
                        f"[cyan]分批阅读已结束。累计标记已读: {total_marked} 篇[/cyan]"
                    )
                    return

        console.print(
            f"\n[bold green]分批阅读已完成！累计标记已读: {total_marked} 篇[/bold green]"
        )

    except KeyboardInterrupt:
        console.print("\n[red]用户取消分批阅读。[/red]")
    except Exception:
        logger.exception("An error occurred during batch reading")
        console.print("[red]处理过程中发生异常，请检查上方日志。[/red]")


def run_process_stream_flow():
    import questionary

    default_limit, default_days, _ = _get_review_defaults()

    use_stream = questionary.confirm(
        "是否指定特定分类/订阅源 (默认全局所有)?:", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = select_stream_interactive()
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
        stream_id,
        limit=limit if limit > 0 else 9999,
        days=days,
        stream_label=stream_label,
    )


def execute_process_stream(stream_id, *, limit=500, days=3, stream_label=None):
    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    limit_display = "全量未读" if limit >= 9999 else str(limit)
    console.print(
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
        backend_service = _load_backend_service()
        if backend_service is None:
            return

        result = backend_service.process_stream(
            stream_id=stream_id,
            stream_label=stream_label,
            days=days,
            limit=limit,
        )
        _render_stream_result(result)

        try:
            import questionary
        except ImportError:
            return

        digest = result.get("digest") or {}
        _prompt_open_stream_article(digest)

        low_priority_ids = result.get("mark_read_candidates", [])
        if low_priority_ids and questionary.confirm(
            f"是否将 {len(low_priority_ids)} 篇低优先级文章在 Feedly 标记为已读?:",
            default=False,
        ).ask():
            mark_result = backend_service.mark_stream_low_priority_read(low_priority_ids)
            if mark_result.get("success"):
                console.print(
                    f"[green]已成功标记 {mark_result['marked_count']} 篇低优先级文章为已读。[/green]"
                )
            else:
                console.print("[red]标记低优先级文章已读失败。[/red]")

        if questionary.confirm("是否导出 Markdown 综述报告?:", default=False).ask():
            overview_file = backend_service.save_stream_overview_markdown(
                result["markdown"],
                stream_label=stream_label or stream_id,
                strategy=result["strategy"],
            )
            console.print(f"[green]报告已成功保存至: {overview_file}[/green]")

    except KeyboardInterrupt:
        console.print("\n[red]操作已被用户取消。[/red]")
    except Exception:
        logger.exception("An error occurred during stream processing")
        console.print("[red]处理过程中发生异常，请检查上方日志。[/red]")


def execute_analyze(
    limit, refresh, mark_read, stream_id=None, threads=3, stream_label=None
):
    """Shared analyze execution logic"""
    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    limit_display = _format_limit_display(limit)
    console.print(
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
        backend_service = _load_backend_service()
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
            console.print(Panel(result["message"], style="red"))
            return

        console.print(
            Panel(
                "深度研读分析完成！(Article Analysis Complete)\n"
                f"- 分析数据: {result['analyzed_file']}\n"
                f"- 总结报告: {result['summary_file']}",
                style="bold green",
            )
        )

    except KeyboardInterrupt:
        console.print("\n[red]操作已被用户取消。[/red]")
    except Exception:
        logger.exception("An error occurred during analysis")
        console.print("[red]分析过程中发生异常，请检查上方日志。[/red]")


def execute_filter(
    mode, limit, threshold, dry_run, mark_read, stream_id=None, stream_label=None
):
    """Shared execution logic"""
    display_stream = stream_label if stream_label else (stream_id or "全量未读 (Global All)")
    limit_display = _format_limit_display(limit)
    mode_names = {
        "all": "全量清理 (快讯 + 低分过滤)",
        "newsflash": "仅过滤快讯 (36kr等)",
        "low-score": "仅过滤低分文章 (AI评分)",
    }
    mode_display = mode_names.get(mode, mode)
    console.print(
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
        backend_service = _load_backend_service()
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
            console.print(Panel(result["message"], style="red"))
            return

        if result["article_count"] == 0:
            console.print("[yellow]未找到符合条件的未读文章。[/yellow]")
            return

        console.print(
            Panel(
                "清理过滤完成！(Filter Run Complete)\n"
                f"过滤数量: {result['filtered_count']}\n"
                f"保留数量: {result['remaining_count']}",
                style="bold green",
            )
        )

    except KeyboardInterrupt:
        console.print("\n[red]操作已被用户取消。[/red]")
    except Exception:
        logger.exception("An error occurred during execution")
        console.print("[red]执行过程中发生异常，请检查上方日志。[/red]")


def run_filter_flow():
    import questionary

    default_limit, default_threshold, default_mark_read = _get_cleanup_defaults()
    limit_text = _format_limit_display(default_limit)
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
        execute_filter(
            "all", default_limit, default_threshold, False, default_mark_read
        )
        return
    elif action == "quick_newsflash":
        execute_filter(
            "newsflash", default_limit, default_threshold, False, default_mark_read
        )
        return
    elif action == "quick_low_score":
        execute_filter(
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
            console.print(f"[red]无效的数字，使用默认值 {limit_default_str}[/red]")
            limit = default_limit

    threshold = default_threshold
    if mode in ["all", "low-score"]:
        threshold_str = questionary.text(
            "评分过滤阈值 (Score Threshold):", default=str(default_threshold)
        ).ask()
        try:
            threshold = float(threshold_str)
        except ValueError:
            console.print(f"[red]无效的阈值，使用默认值 {default_threshold}[/red]")
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
        stream_id, stream_label = select_stream_interactive()

    # Execution
    mark_read = questionary.confirm(
        "清理完成后是否在 Feedly 标记为已读?:", default=default_mark_read
    ).ask()

    execute_filter(mode, limit, threshold, dry_run, mark_read, stream_id, stream_label)


if __name__ == "__main__":
    # Auto-use project venv if present (so launching a fresh terminal is fine).
    _maybe_reexec_in_project_venv()

    # Fail fast on broken LLM dependencies (do not enter menu).
    _verify_startup_dependencies_or_exit()

    try:
        main_menu()
    except KeyboardInterrupt:
        sys.exit()
    except Exception as e:
        # Fallback for NoConsoleScreenBufferError or other TUI init failures
        if "NoConsole" in str(e) or "console" in str(e).lower():
            console.print(
                "[yellow]Interactive console not detected. Switching to simple mode...[/yellow]"
            )
            simple_menu()
        else:
            raise e
