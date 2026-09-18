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
GLOBAL_STREAM_SENTINEL = "__GLOBAL_ALL__"


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
                "Feedly AI Filter TUI\n"
                f"[dim]analysis:[/dim] {analysis_model}\n"
                f"[dim]summary:[/dim] {summary_model}"
            ),
            style="bold cyan",
            subtitle="Interactive Runner",
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
            "Feedly AI Filter (Simple Mode)", style="bold cyan", subtitle="Basic Runner"
        )
    )

    while True:
        console.print("\n[bold]Main Menu:[/bold]")
        console.print("1. Review Unread")
        console.print("2. Clean Up Unread")
        console.print("3. Analyze & Reports")
        console.print("4. Export Unread JSON")
        console.print("5. Exit")

        choice = get_input("Select an option")

        if choice == "5":
            console.print("[cyan]Goodbye![/cyan]")
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
            console.print("[red]Invalid choice[/red]")


def simple_review_menu():
    while True:
        console.print("\n[bold]Review Unread:[/bold]")
        console.print("1. Quick Review Stream")
        console.print("2. Batch Clear Backlog")
        console.print("3. Back")
        choice = get_input("Select an option")
        if choice == "1":
            simple_process_stream_flow()
        elif choice == "2":
            run_batch_read_flow()
        elif choice == "3":
            return
        else:
            console.print("[red]Invalid choice[/red]")


def simple_reports_menu():
    while True:
        console.print("\n[bold]Analyze & Reports:[/bold]")
        console.print("1. Quick Full Analyze (Limit: 100, Refresh: Yes, Threads: 3)")
        console.print("2. Custom Full Analyze + Report")
        console.print("3. Summary / Report")
        console.print("4. Back")
        choice = get_input("Select an option", default="1")
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
            console.print("[red]Invalid choice[/red]")


def simple_analyze_flow():
    """Fallback analyze flow"""
    console.print("\n[bold]Full Analyze + Report Configuration:[/bold]")

    limit_str = get_input("Article Limit", default="100")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    refresh_str = get_input("Refresh from Feedly? (y/n)", default="y")
    refresh = refresh_str.lower().startswith("y")

    stream_id = None
    if refresh:
        sid = get_input("Stream ID (Optional, press Enter to skip)", default="")
        if sid:
            stream_id = sid

    default_mark = "y" if PROJ_CONFIG.get("mark_read") else "n"
    mark_read_str = get_input(
        "Mark as read after analysis? (y/n)", default=default_mark
    )
    mark_read = mark_read_str.lower().startswith("y")

    threads_str = get_input("Number of threads (Default: 3)", default="3")
    try:
        threads = int(threads_str)
    except ValueError:
        threads = 3

    execute_analyze(limit, refresh, mark_read, stream_id, threads)


def simple_export_flow():
    """Fallback export flow"""
    console.print("\n[bold]Export Configuration:[/bold]")

    sid = get_input("Stream ID (Optional, press Enter for Global)", default="")
    stream_id = sid if sid else None

    limit_str = get_input("Limit", default="100")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    from datetime import datetime

    default_filename = f"output/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename = get_input("Output Filename", default=default_filename)

    execute_export(limit, stream_id, filename)


def simple_process_stream_flow():
    console.print("\n[bold]Quick Review Stream:[/bold]")
    sid = get_input("Stream ID (Optional, press Enter for Global)", default="")
    stream_id = sid if sid else None

    limit_str = get_input("Limit", default="500")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 500

    days_str = get_input("Recent Days", default="3")
    try:
        days = int(days_str)
    except ValueError:
        days = 3

    execute_process_stream(stream_id, limit=limit, days=days)


def run_export_flow():
    """Interactive export flow"""
    import questionary
    from datetime import datetime

    # 1. Select Stream
    stream_id, stream_label = select_stream_interactive()

    # 2. Limit
    limit_str = questionary.text("Article Limit:", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100

    # 3. Output Filename
    default_filename = f"output/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename = questionary.text("Output Filename:", default=default_filename).ask()

    execute_export(limit, stream_id, filename, stream_label)


def resolve_export_path(filename: str) -> str:
    from pathlib import Path

    path = Path(filename)
    if not path.parent or str(path.parent) == ".":
        path = Path("output") / path.name
    return str(path)


def execute_export(limit, stream_id, filename, stream_label=None):
    filename = resolve_export_path(filename)
    display_stream = stream_label if stream_label else (stream_id or "Global (All)")
    console.print(
        Panel(
            f"Exporting Articles\n"
            f"Limit: {limit}\n"
            f"Stream: {display_stream}\n"
            f"Output: {filename}",
            title="Export Configuration",
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
            Panel(f"Export Complete! File saved to {filename}", style="bold green")
        )
    except Exception:
        logger.exception("Error exporting")
        console.print("[red]Export failed.[/red]")


def _format_limit_display(limit: int | None) -> str:
    if limit is None or limit <= 0:
        return "All (全量)"
    return str(limit)


def _get_cleanup_defaults() -> tuple[int, float, bool]:
    limit_str = os.getenv("CLEANUP_DEFAULT_LIMIT")
    if limit_str is not None and limit_str != "":
        val = limit_str.strip().lower()
        if val in ("all", "0", "full", "none", "inf"):
            default_limit = 0
        else:
            try:
                default_limit = int(val)
            except ValueError:
                default_limit = 0
    else:
        default_limit = 0

    thresh_str = os.getenv("CLEANUP_DEFAULT_THRESHOLD")
    if thresh_str:
        try:
            default_threshold = float(thresh_str)
        except ValueError:
            default_threshold = 3.0
    else:
        default_threshold = 3.0

    env_mark = os.getenv("CLEANUP_DEFAULT_MARK_READ")
    if env_mark is not None:
        default_mark_read = env_mark.strip().lower() in ("1", "true", "yes", "on")
    else:
        default_mark_read = True

    return default_limit, default_threshold, default_mark_read


def simple_filter_flow():
    """Fallback filter flow"""
    default_limit, default_threshold, default_mark_read = _get_cleanup_defaults()
    limit_text = _format_limit_display(default_limit)
    mark_text = "Yes" if default_mark_read else "No"
    console.print("\n[bold]Clean Up Unread:[/bold]")
    console.print(
        f"1. Quick Clean: All Filters (Limit: {limit_text}, Score < {default_threshold}, Mark Read: {mark_text})"
    )
    console.print(
        f"2. Quick Clean: Newsflash Only (Limit: {limit_text}, Mark Read: {mark_text})"
    )
    console.print(
        f"3. Quick Clean: Low Score Only (Limit: {limit_text}, Score < {default_threshold}, Mark Read: {mark_text})"
    )
    console.print("4. Custom Configuration")
    console.print("5. Back")

    choice = get_input("Select an option", default="1")

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
        console.print("\n[bold]Select Filter Mode:[/bold]")
        console.print("1. All Filters (Newsflash + Low Score)")
        console.print("2. Newsflash Only")
        console.print("3. Low Score Only")
        console.print("4. Back")

        m_choice = get_input("Select mode", default="1")
        if m_choice == "1":
            mode = "all"
        elif m_choice == "2":
            mode = "newsflash"
        elif m_choice == "3":
            mode = "low-score"
        else:
            return

        limit_str = get_input("Article Limit", default=str(default_limit))
        try:
            limit = int(limit_str)
        except ValueError:
            limit = default_limit

        threshold = default_threshold
        if mode in ["all", "low-score"]:
            t_str = get_input("Score Threshold", default=str(default_threshold))
            try:
                threshold = float(t_str)
            except ValueError:
                threshold = default_threshold

        dr_str = get_input("Dry Run? (y/n)", default="n")
        dry_run = dr_str.lower().startswith("y")

        mark_read_str = get_input(
            "Mark as read? (y/n)", default="y" if default_mark_read else "n"
        )
        mark_read = mark_read_str.lower().startswith("y")

        execute_filter(mode, limit, threshold, dry_run, mark_read=mark_read)
    else:
        console.print("[red]Invalid choice[/red]")


def select_stream_interactive():
    """Interactive stream selector"""
    import questionary

    console.print("[dim]Fetching Feedly directory info...[/dim]")

    # Parallel fetch could be better but sequential is safer for now
    categories = feedly_get_categories()
    subscriptions = feedly_get_subscriptions()
    counts_data = feedly_get_unread_counts()

    if not categories or not subscriptions or not counts_data:
        console.print("[red]Failed to fetch complete directory info.[/red]")
        if questionary.confirm(
            "Continue with default Global Stream?", default=True
        ).ask():
            return None, "Global (Default)"
        return None, None

    # Map counts
    # API returns: {"unreadcounts": [{"id": "...", "count": 123, "updated": ...}]}
    count_map = {
        item["id"]: item["count"] for item in counts_data.get("unreadcounts", [])
    }

    # Create ID to Label mapping for return value
    id_to_label = {}

    choices = []

    # 1. Global All
    # We don't have the exact user ID readily available without loading config again or parsing stream IDs
    # But usually one of the unreadcounts entries is for global.all
    global_count = 0
    for cid, count in count_map.items():
        if "global.all" in cid:
            global_count = count
            break

    global_label = f"Global All ({global_count} unread)"
    choices.append(questionary.Choice(global_label, value=GLOBAL_STREAM_SENTINEL))
    id_to_label[GLOBAL_STREAM_SENTINEL] = "Global All"

    # 2. Categories
    cat_choices = []
    for cat in categories:
        cid = cat["id"]
        label = cat["label"]
        count = count_map.get(cid, 0)
        if count > 0:
            display_label = f"📁 Category: {label}"
            cat_choices.append((count, display_label, cid))
            id_to_label[cid] = f"Category: {label}"

    # Sort by count descending
    cat_choices.sort(key=lambda x: x[0], reverse=True)

    for count, label, cid in cat_choices:
        choices.append(questionary.Choice(f"{label} ({count} unread)", value=cid))

    # 3. Feeds (Top 20 by unread count)
    feed_choices = []
    for sub in subscriptions:
        fid = sub["id"]
        title = sub["title"]
        count = count_map.get(fid, 0)
        if count > 0:
            display_label = f"📰 Feed: {title}"
            feed_choices.append((count, display_label, fid))
            id_to_label[fid] = f"Feed: {title}"

    feed_choices.sort(key=lambda x: x[0], reverse=True)

    # Add separator if we have feeds
    if feed_choices:
        choices.append(questionary.Separator("--- Feeds ---"))

    for i, (count, label, fid) in enumerate(feed_choices):
        if i >= 50:  # Limit to top 50 to avoid clutter
            break
        choices.append(questionary.Choice(f"{label} ({count} unread)", value=fid))

    choices.append(questionary.Separator("--- Other ---"))
    choices.append(questionary.Choice("Enter Stream ID manually", value="MANUAL"))

    stream_id = questionary.select(
        "Select Stream to Process:",
        choices=choices,
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

    stream_label = None
    if stream_id == GLOBAL_STREAM_SENTINEL:
        return None, "Global All"

    if stream_id == "MANUAL":
        stream_id = questionary.text("Enter Stream ID:").ask()
        if not stream_id:
            return None, None
        stream_label = f"Manual ID: {stream_id}"
    else:
        stream_label = id_to_label.get(stream_id, str(stream_id))

    return stream_id, stream_label


def resolve_stream_feed_titles(stream_id, categories=None, subscriptions=None):
    if not stream_id:
        return None

    if categories is None:
        categories = feedly_get_categories()
    if subscriptions is None:
        subscriptions = feedly_get_subscriptions()

    if not categories or not subscriptions:
        return None

    category_ids = {cat.get("id") for cat in categories}
    if stream_id in category_ids:
        matched_titles = []
        for sub in subscriptions:
            sub_categories = sub.get("categories", [])
            if any(cat.get("id") == stream_id for cat in sub_categories):
                title = sub.get("title")
                if title:
                    matched_titles.append(title)
        return matched_titles

    for sub in subscriptions:
        if sub.get("id") == stream_id:
            title = sub.get("title")
            return [title] if title else []

    return None


def filter_articles_by_titles(articles, titles):
    if titles is None:
        return articles
    if not titles:
        return []

    title_set = set(titles)
    return [a for a in articles if a.get("origin") in title_set]


def _import_error_hint(modname: str, err: Exception) -> str:
    # Goal: unblock users hitting binary dependency issues (pydantic-core / jiter) after Python upgrades.
    return (
        f"Failed to import '{modname}': {err}\n\n"
        "Common causes:\n"
        "- You upgraded Python (e.g. 3.13 → 3.14) and binary wheels (pydantic-core / jiter) no longer match.\n"
        "- Your environment has dependency conflicts (e.g. langchain-openai requires openai<2.0.0 but openai 2.x is installed).\n\n"
        "Recommended fix (clean venv):\n"
        "  python -m venv .venv\n"
        "  .venv\\Scripts\\activate\n"
        "  python -m pip install -U pip\n"
        "  python -m pip install -r requirements.txt\n\n"
        "If you use langchain-openai, pin OpenAI SDK to 1.x:\n"
        '  python -m pip install "openai>=1.86.0,<2.0.0"\n\n'
        "Diagnostics to paste:\n"
        "  python -V\n"
        '  python -c "import platform; print(platform.architecture()); print(platform.python_version())"\n'
        '  python -c "import sys; print(sys.executable)"\n'
        "  python -m pip -V\n"
        "  python -m pip show pydantic-core pydantic openai jiter langchain-openai\n"
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
            "What would you like to do?",
            choices=[
                questionary.Choice("Review Unread", value="review"),
                questionary.Choice("Clean Up Unread", value="cleanup"),
                questionary.Choice("Analyze & Reports", value="reports"),
                questionary.Choice("Export Unread JSON", value="export"),
                questionary.Choice("Exit", value="exit"),
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
            console.print("[cyan]Goodbye![/cyan]")
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

    action = questionary.select(
        "Review Unread:",
        choices=[
            questionary.Choice(
                "Quick Review Stream - one-shot radar preview", value="quick"
            ),
            questionary.Choice(
                "Batch Clear Backlog - cached triage loop", value="batch"
            ),
            questionary.Choice("Back", value="back"),
        ],
    ).ask()

    if action == "quick":
        run_process_stream_flow()
    elif action == "batch":
        run_batch_read_flow()


def run_reports_menu():
    import questionary

    action = questionary.select(
        "Analyze & Reports:",
        choices=[
            questionary.Choice(
                "⚡ Quick Full Analyze (Limit: 100, Refresh: Yes, All Feeds, Threads: 3)",
                value="quick_analyze",
            ),
            questionary.Choice("🛠 Custom Full Analyze + Report...", value="analyze"),
            questionary.Choice("Summary / Report", value="summary"),
            questionary.Choice("Back", value="back"),
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
        console.print(Panel("Regenerating Summary...", style="bold blue"))
        try:
            backend_service = _load_backend_service()
            if backend_service is None:
                return

            result = backend_service.regenerate_summary()
            if result.get("error"):
                console.print(Panel(result["message"], style="red"))
                return

            console.print(Panel("Summary Generation Complete!", style="bold green"))
        except Exception:
            logger.exception("Error generating summary")
            console.print("[red]Failed to generate summary.[/red]")
        return

    mode = questionary.select(
        "Summary Mode:",
        choices=[
            questionary.Choice(
                "Summarize existing analyzed file", value="local"
            ),
            questionary.Choice(
                "Refresh Feedly, full analyze, then summarize", value="refresh"
            ),
            questionary.Choice("Back", value="back"),
        ],
    ).ask()

    if mode == "back":
        return

    stream_id, stream_label = select_stream_interactive()
    if stream_id is None and stream_label is None:
        return

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
                    "Summary Generation Complete!\n"
                    f"- {result['summary_file']}\n"
                    f"- {result['latest_summary_file']}",
                    style="bold green",
                )
            )
        except Exception:
            logger.exception("Error generating summary")
            console.print("[red]Failed to generate summary.[/red]")
        return

    # refresh mode
    limit_str = questionary.text("Article Limit:", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        console.print("[red]Invalid limit, using default 100[/red]")
        limit = 100

    mark_read = questionary.confirm(
        "Mark as read after analysis?", default=PROJ_CONFIG.get("mark_read", False)
    ).ask()

    execute_analyze(limit, True, mark_read, stream_id, 3, stream_label)


def run_analyze_flow():
    """Interactive analyze flow using questionary"""
    import questionary

    # Configure parameters
    limit_str = questionary.text("Article Limit:", default="100").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        console.print("[red]Invalid limit, using default 100[/red]")
        limit = 100

    refresh = questionary.confirm("Refresh from Feedly?", default=True).ask()

    stream_id = None
    stream_label = None
    if refresh:
        # Only ask for stream if we are refreshing
        use_stream = questionary.confirm(
            "Select specific Category/Feed?", default=False
        ).ask()
        if use_stream:
            stream_id, stream_label = select_stream_interactive()

    mark_read = questionary.confirm(
        "Mark as read after analysis?", default=PROJ_CONFIG.get("mark_read", False)
    ).ask()

    threads_str = questionary.text("Number of threads:", default="3").ask()
    try:
        threads = int(threads_str)
    except ValueError:
        console.print("[red]Invalid thread count, using default 3[/red]")
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
        ("Must Read", digest.get("deep_analyzed_reads", [])),
        ("Skim", digest.get("skim_items", [])),
    ):
        for item in items:
            if item.get("link"):
                openable_items.append((section, item))

    if not openable_items:
        return

    if not questionary.confirm("Open a recommended article in browser?", default=False).ask():
        return

    choices = [
        questionary.Choice(f"[{section}] {item['title']}", value=item)
        for section, item in openable_items
    ]
    choices.append(questionary.Choice("Cancel", value=None))
    selected = questionary.select("Choose an article to open:", choices=choices).ask()
    if not selected:
        return

    if _open_stream_article(selected):
        console.print(f"[green]Opened:[/green] {selected['title']}")
    else:
        console.print("[red]Failed to open the article link.[/red]")


def _loop_open_articles(digest):
    """Open articles from digest in browser, one at a time in a loop."""
    import questionary

    openable_items = []
    for section, items in (
        ("Must Read", digest.get("deep_analyzed_reads", [])),
        ("Skim", digest.get("skim_items", [])),
    ):
        for item in items:
            if item.get("link"):
                openable_items.append((section, item))

    if not openable_items:
        console.print("[yellow]No articles with links to open.[/yellow]")
        return

    # Build a label->item map since questionary.Choice value may not
    # round-trip dicts reliably.
    opened_links: set[str] = set()

    while True:
        remaining = [
            (s, i) for s, i in openable_items if i.get("link") not in opened_links
        ]
        if not remaining:
            console.print("[dim]All articles opened.[/dim]")
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

        labels.append("Done reading")
        selected_label = questionary.select(
            f"Open article ({len(remaining)} left):", choices=labels
        ).ask()

        if selected_label is None or selected_label == "Done reading":
            break

        item = label_to_item.get(selected_label)
        if not item:
            continue

        if _open_stream_article(item):
            opened_links.add(item["link"])
            console.print(f"[green]Opened:[/green] {item['title']}")
        else:
            console.print("[red]Failed to open link.[/red]")


def run_batch_read_flow():
    """Batch reading mode: fetch N articles, AI filter, read, mark, repeat."""
    import questionary

    stream_id, stream_label = select_stream_interactive()
    if stream_id is None and stream_label is None:
        return

    batch_str = questionary.text("LLM Chunk Size:", default="50").ask()
    try:
        batch_size = int(batch_str)
    except ValueError:
        batch_size = 50

    days_str = questionary.text("Recent Days:", default="3").ask()
    try:
        days = int(days_str)
    except ValueError:
        days = 3

    display_stream = stream_label if stream_label else (stream_id or "Global (All)")
    console.print(
        Panel(
            f"Batch Reading Mode\n"
            f"Stream: {display_stream}\n"
            f"LLM Chunk Size: {batch_size}\n"
            f"Recent Days: {days}",
            title="Batch Clear Backlog",
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
            console.print(f"\n[bold cyan]━━━ Batch #{batch_num} ━━━[/bold cyan]")

            result = backend.process_batch(
                stream_id=stream_id,
                stream_label=stream_label,
                batch_size=batch_size,
                days=days,
            )

            fetched = result.get("fetched_count", 0)
            if fetched == 0:
                console.print("[green]✓ All articles processed![/green]")
                break

            _render_stream_result(result)

            digest = result.get("digest") or {}
            mark_read_ids = result.get("mark_read_candidates", [])

            # Interactive loop for this batch
            while True:
                choices = [
                    questionary.Choice("Open an article to read", value="open"),
                    questionary.Choice(
                        f"Mark {len(mark_read_ids)} low-priority items as read",
                        value="mark_clear",
                    ),
                    questionary.Choice("Mark ALL in this batch as read", value="mark_all"),
                    questionary.Choice("Next batch (skip marking)", value="next"),
                    questionary.Choice("Exit batch reading", value="exit"),
                ]
                action = questionary.select(
                    "What to do with this batch?",
                    choices=choices,
                ).ask()

                if action == "open":
                    _loop_open_articles(digest)
                elif action == "mark_clear":
                    if mark_read_ids:
                        mark_result = backend.mark_articles_read(mark_read_ids)
                        if mark_result.get("success"):
                            console.print(
                                f"[green]Marked {mark_result['marked_count']} items as read.[/green]"
                            )
                            total_marked += mark_result["marked_count"]
                        else:
                            console.print("[red]Failed to mark items as read.[/red]")
                    else:
                        console.print("[yellow]No low-priority items to mark.[/yellow]")
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
                                f"[green]Marked {mark_result['marked_count']} items as read.[/green]"
                            )
                            total_marked += mark_result["marked_count"]
                        else:
                            console.print("[red]Failed to mark items as read.[/red]")
                    break  # move to next batch after marking all
                elif action == "next":
                    break
                elif action == "exit":
                    console.print(
                        f"[cyan]Done. Total marked as read: {total_marked}[/cyan]"
                    )
                    return

        console.print(
            f"\n[bold green]Batch reading complete. Total marked as read: {total_marked}[/bold green]"
        )

    except KeyboardInterrupt:
        console.print("\n[red]Batch reading cancelled.[/red]")
    except Exception:
        logger.exception("An error occurred during batch reading")
        console.print("[red]An error occurred. Check logs above.[/red]")


def run_process_stream_flow():
    import questionary

    stream_id, stream_label = select_stream_interactive()
    if stream_id is None and stream_label is None:
        return

    limit_str = questionary.text("Fetch Limit:", default="500").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 500

    days_str = questionary.text("Recent Days:", default="3").ask()
    try:
        days = int(days_str)
    except ValueError:
        days = 3

    execute_process_stream(stream_id, limit=limit, days=days, stream_label=stream_label)


def execute_process_stream(stream_id, *, limit=500, days=3, stream_label=None):
    display_stream = stream_label if stream_label else (stream_id or "Global (All)")
    console.print(
        Panel(
            f"Quick Review Stream\n"
            f"Stream: {display_stream}\n"
            f"Limit: {limit}\n"
            f"Recent Days: {days}",
            title="Configuration",
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
            f"Mark {len(low_priority_ids)} low-priority items as read?", default=False
        ).ask():
            mark_result = backend_service.mark_stream_low_priority_read(low_priority_ids)
            if mark_result.get("success"):
                console.print(
                    f"[green]Marked {mark_result['marked_count']} low-priority items as read.[/green]"
                )
            else:
                console.print("[red]Failed to mark low-priority items as read.[/red]")

        if questionary.confirm("Export overview markdown?", default=False).ask():
            overview_file = backend_service.save_stream_overview_markdown(
                result["markdown"],
                stream_label=stream_label or stream_id,
                strategy=result["strategy"],
            )
            console.print(f"[green]Saved overview to {overview_file}[/green]")

    except KeyboardInterrupt:
        console.print("\n[red]Operation cancelled by user.[/red]")
    except Exception:
        logger.exception("An error occurred during stream processing")
        console.print("[red]An error occurred. Check logs above.[/red]")


def execute_analyze(
    limit, refresh, mark_read, stream_id=None, threads=3, stream_label=None
):
    """Shared analyze execution logic"""
    display_stream = stream_label if stream_label else (stream_id or "Global (All)")
    console.print(
        Panel(
            f"Full Analyze + Report\n"
            f"Limit: {limit}\n"
            f"Refresh: {refresh}\n"
            f"Stream: {display_stream}\n"
            f"Mark Read: {mark_read}\n"
            f"Threads: {threads}",
            title="Configuration",
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
                "Article Analysis Complete!\n"
                f"- {result['analyzed_file']}\n"
                f"- {result['summary_file']}",
                style="bold green",
            )
        )

    except KeyboardInterrupt:
        console.print("\n[red]Operation cancelled by user.[/red]")
    except Exception:
        logger.exception("An error occurred during analysis")
        console.print("[red]An error occurred. Check logs above.[/red]")


def execute_filter(
    mode, limit, threshold, dry_run, mark_read, stream_id=None, stream_label=None
):
    """Shared execution logic"""
    display_stream = stream_label if stream_label else (stream_id or "Global (All)")
    limit_display = _format_limit_display(limit)
    console.print(
        Panel(
            f"Running Mode: [bold]{mode}[/bold]\n"
            f"Limit: {limit_display}\n"
            f"Threshold: {threshold}\n"
            f"Stream: {display_stream}\n"
            f"Dry Run: {dry_run}\n"
            f"Mark Read: {mark_read}",
            title="Configuration",
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
            console.print("[yellow]No unread articles found.[/yellow]")
            return

        console.print(
            Panel(
                "Filter Run Complete!\n"
                f"Filtered: {result['filtered_count']}\n"
                f"Remaining: {result['remaining_count']}",
                style="bold green",
            )
        )

    except KeyboardInterrupt:
        console.print("\n[red]Operation cancelled by user.[/red]")
    except Exception:
        logger.exception("An error occurred during execution")
        console.print("[red]An error occurred. Check logs above.[/red]")


def run_filter_flow():
    import questionary

    default_limit, default_threshold, default_mark_read = _get_cleanup_defaults()
    limit_text = _format_limit_display(default_limit)
    mark_text = "Yes" if default_mark_read else "No"

    # 1. Select Mode or Quick Run
    action = questionary.select(
        "Clean Up Unread:",
        choices=[
            questionary.Choice(
                f"⚡ Quick Clean: All Filters (Limit: {limit_text}, Score < {default_threshold}, Mark Read: {mark_text})",
                value="quick_all",
            ),
            questionary.Choice(
                f"⚡ Quick Clean: Newsflash Only (Limit: {limit_text}, Mark Read: {mark_text})",
                value="quick_newsflash",
            ),
            questionary.Choice(
                f"⚡ Quick Clean: Low Score Only (Limit: {limit_text}, Score < {default_threshold}, Mark Read: {mark_text})",
                value="quick_low_score",
            ),
            questionary.Choice(
                "🛠 Custom Configuration (Customize Limit, Threshold, Stream, Dry-Run...)",
                value="custom",
            ),
            questionary.Choice("Back", value="back"),
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
        "Select Filter Mode:",
        choices=[
            questionary.Choice("All Filters (Newsflash + Low Score)", value="all"),
            questionary.Choice("Newsflash Only (36kr)", value="newsflash"),
            questionary.Choice("Low Score Only (AI Scoring)", value="low-score"),
            questionary.Choice("Back", value="back"),
        ],
    ).ask()

    if not mode or mode == "back":
        return

    # Configure Parameters
    limit_default_str = "0" if default_limit <= 0 else str(default_limit)
    limit_str = questionary.text(
        "Article Limit (0 or 'all' for full unread 全量):",
        default=limit_default_str,
    ).ask()
    if not limit_str or limit_str.strip().lower() in ("all", "0", "full"):
        limit = 0
    else:
        try:
            limit = int(limit_str)
        except ValueError:
            console.print(f"[red]Invalid limit, using default {limit_default_str}[/red]")
            limit = default_limit

    threshold = default_threshold
    if mode in ["all", "low-score"]:
        threshold_str = questionary.text(
            "Score Threshold:", default=str(default_threshold)
        ).ask()
        try:
            threshold = float(threshold_str)
        except ValueError:
            console.print(f"[red]Invalid threshold, using default {default_threshold}[/red]")
            threshold = default_threshold

    dry_run = questionary.confirm(
        "Dry Run? (Simulate only, no changes)", default=False
    ).ask()

    # Stream Selection
    stream_id = None
    stream_label = None
    use_stream = questionary.confirm(
        "Select specific Category/Feed?", default=False
    ).ask()
    if use_stream:
        stream_id, stream_label = select_stream_interactive()

    # Execution
    mark_read = questionary.confirm(
        "Mark as read after filter?", default=default_mark_read
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
