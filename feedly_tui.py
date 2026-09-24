#!/usr/bin/env python3
"""
AI-Feedly-Curator TUI Runner
Interactive menu for running Feedly filters.
"""

import sys
import logging
import os
from rss_analyzer.config import (
    PROJ_CONFIG,
    get_openai_task_config,
)
from rss_analyzer.feedly_client import (
    feedly_get_categories,
    feedly_get_subscriptions,
    feedly_get_unread_counts,
)
from rss_analyzer.tui.support import (
    format_limit_display as _format_limit_display,
    get_cleanup_defaults as _get_cleanup_defaults,
    get_review_defaults as _get_review_defaults,
    import_error_hint as _import_error_hint,
)
from rss_analyzer.tui.stream_selection import (
    GLOBAL_STREAM_SENTINEL,
    select_stream_interactive as _select_stream_interactive,
)
from rss_analyzer.tui.review import (
    ReviewContext,
    execute_batch_read as _review_execute_batch_read,
    execute_process_stream as _review_execute_process_stream,
    loop_open_articles as _review_loop_open_articles,
    open_stream_article as _review_open_stream_article,
    prompt_open_stream_article as _review_prompt_open_stream_article,
    render_stream_result as _review_render_stream_result,
    run_batch_read_flow as _review_run_batch_read_flow,
    run_process_stream_flow as _review_run_process_stream_flow,
)
from rss_analyzer.tui.reports import (
    ReportContext,
    execute_analyze as _report_execute_analyze,
    execute_export as _report_execute_export,
    run_analyze_flow as _report_run_analyze_flow,
    run_export_flow as _report_run_export_flow,
    run_summary_flow as _report_run_summary_flow,
)
from rss_analyzer.tui.cleanup import (
    CleanupContext,
    execute_filter as _cleanup_execute_filter,
    run_filter_flow as _cleanup_run_filter_flow,
    simple_filter_flow as _cleanup_simple_filter_flow,
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


def _report_context() -> ReportContext:
    return ReportContext(
        console=console,
        logger=logger,
        load_backend_service=_load_backend_service,
        select_stream_interactive=select_stream_interactive,
    )


def run_export_flow():
    return _report_run_export_flow(_report_context())


def execute_export(limit, stream_id, filename, stream_label=None):
    return _report_execute_export(
        _report_context(),
        limit,
        stream_id,
        filename,
        stream_label=stream_label,
    )





def _cleanup_context() -> CleanupContext:
    return CleanupContext(
        console=console,
        logger=logger,
        load_backend_service=_load_backend_service,
        select_stream_interactive=select_stream_interactive,
        get_input=get_input,
        execute_filter=execute_filter,
    )


def simple_filter_flow():
    return _cleanup_simple_filter_flow(_cleanup_context())




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
    return _report_run_summary_flow(_report_context())


def run_analyze_flow():
    return _report_run_analyze_flow(_report_context())




def _review_context() -> ReviewContext:
    return ReviewContext(
        console=console,
        logger=logger,
        load_backend_service=_load_backend_service,
        select_stream_interactive=select_stream_interactive,
        get_review_defaults=_get_review_defaults,
    )


def _render_stream_result(result):
    return _review_render_stream_result(_review_context(), result)


def _open_stream_article(article: dict) -> bool:
    return _review_open_stream_article(_review_context(), article)


def _prompt_open_stream_article(digest):
    return _review_prompt_open_stream_article(_review_context(), digest)


def _loop_open_articles(digest):
    return _review_loop_open_articles(_review_context(), digest)


def run_batch_read_flow():
    return _review_run_batch_read_flow(_review_context())


def execute_batch_read(stream_id, stream_label=None, batch_size=50, days=3):
    return _review_execute_batch_read(
        _review_context(),
        stream_id,
        stream_label=stream_label,
        batch_size=batch_size,
        days=days,
    )


def run_process_stream_flow():
    return _review_run_process_stream_flow(_review_context())


def execute_process_stream(stream_id, *, limit=500, days=3, stream_label=None):
    return _review_execute_process_stream(
        _review_context(),
        stream_id,
        limit=limit,
        days=days,
        stream_label=stream_label,
    )




def execute_analyze(
    limit, refresh, mark_read, stream_id=None, threads=3, stream_label=None
):
    return _report_execute_analyze(
        _report_context(),
        limit,
        refresh,
        mark_read,
        stream_id=stream_id,
        threads=threads,
        stream_label=stream_label,
    )




def execute_filter(
    mode, limit, threshold, dry_run, mark_read, stream_id=None, stream_label=None
):
    return _cleanup_execute_filter(
        _cleanup_context(),
        mode,
        limit,
        threshold,
        dry_run,
        mark_read,
        stream_id=stream_id,
        stream_label=stream_label,
    )


def run_filter_flow():
    return _cleanup_run_filter_flow(_cleanup_context())




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
