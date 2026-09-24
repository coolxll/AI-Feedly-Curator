#!/usr/bin/env python3
"""
AI-Feedly-Curator TUI Runner
Interactive menu for running Feedly filters.
"""

import sys
import logging
import os
from rss_analyzer.feedly_client import (
    feedly_get_categories,
    feedly_get_subscriptions,
    feedly_get_unread_counts,
)
from rss_analyzer.tui.support import (
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
from rss_analyzer.tui.menus import (
    MenuContext,
    get_input as _menu_get_input,
    main_menu as _menu_main,
    pause_and_render_main_header as _menu_pause_and_render_main_header,
    render_main_header as _menu_render_main_header,
    run_reports_menu as _menu_run_reports,
    run_review_menu as _menu_run_review,
    simple_analyze_flow as _menu_simple_analyze_flow,
    simple_export_flow as _menu_simple_export_flow,
    simple_menu as _menu_simple_menu,
    simple_process_stream_flow as _menu_simple_process_stream_flow,
    simple_reports_menu as _menu_simple_reports_menu,
    simple_review_menu as _menu_simple_review_menu,
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


def _menu_context() -> MenuContext:
    return MenuContext(
        console=console,
        get_input=get_input,
        get_review_defaults=_get_review_defaults,
        simple_filter_flow=simple_filter_flow,
        execute_process_stream=execute_process_stream,
        execute_batch_read=execute_batch_read,
        execute_analyze=execute_analyze,
        execute_export=execute_export,
        run_filter_flow=run_filter_flow,
        run_summary_flow=run_summary_flow,
        run_analyze_flow=run_analyze_flow,
        run_export_flow=run_export_flow,
        run_process_stream_flow=run_process_stream_flow,
        run_batch_read_flow=run_batch_read_flow,
    )


def render_main_header():
    return _menu_render_main_header(_menu_context())




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
    return _menu_get_input(prompt_text, default)


def simple_menu():
    return _menu_simple_menu(_menu_context())


def simple_review_menu():
    return _menu_simple_review_menu(_menu_context())


def simple_reports_menu():
    return _menu_simple_reports_menu(_menu_context())


def simple_analyze_flow():
    return _menu_simple_analyze_flow(_menu_context())


def simple_export_flow():
    return _menu_simple_export_flow(_menu_context())


def simple_process_stream_flow():
    return _menu_simple_process_stream_flow(_menu_context())




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
    return _menu_pause_and_render_main_header(_menu_context())


def main_menu():
    return _menu_main(_menu_context())


def run_review_menu():
    return _menu_run_review(_menu_context())


def run_reports_menu():
    return _menu_run_reports(_menu_context())




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
