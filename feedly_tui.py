#!/usr/bin/env python3
"""
AI-Feedly-Curator TUI Runner
Interactive menu for running Feedly filters.
"""
import sys
import logging
import os
from rss_analyzer.config import PROJ_CONFIG
from rss_analyzer.feedly_client import feedly_get_categories, feedly_get_subscriptions, feedly_get_unread_counts
from rss_analyzer.utils import load_articles
from rich.console import Console
from rich.panel import Panel
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback

# Configure Rich Tracebacks
install_rich_traceback()

# Re-configure logging to use RichHandler
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False)],
    force=True
)

console = Console()
logger = logging.getLogger("tui")


def _maybe_reexec_in_project_venv() -> None:
    """Re-exec into the project's .venv interpreter if present.

    This avoids requiring users to manually activate the venv when launching a
    terminal via right-click/open-in-terminal.
    """
    if os.environ.get("RSS_OPML_SKIP_VENV") == "1":
        return
    if os.environ.get("RSS_OPML_VENV_REEXEC") == "1":
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, ".venv", "Scripts", "python.exe"),  # Windows
        os.path.join(script_dir, ".venv", "bin", "python"),          # POSIX
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
    console.print(Panel.fit("Feedly AI Filter (Simple Mode)", style="bold cyan", subtitle="Basic Runner"))
    
    while True:
        console.print("\n[bold]Main Menu:[/bold]")
        console.print("1. Run Filter")
        console.print("2. Analyze Articles")
        console.print("3. Regenerate Summary")
        console.print("4. Export Articles")
        console.print("5. Exit")

        choice = get_input("Select an option")

        if choice == "5":
            console.print("[cyan]Goodbye![/cyan]")
            sys.exit()
        elif choice == "1":
            simple_filter_flow()
        elif choice == "2":
            simple_analyze_flow()
        elif choice == "3":
            run_summary_flow()
        elif choice == "4":
            simple_export_flow()
        else:
            console.print("[red]Invalid choice[/red]")

def simple_analyze_flow():
    """Fallback analyze flow"""
    console.print("\n[bold]Analyze Articles Configuration:[/bold]")
    
    limit_str = get_input("Article Limit", default="100")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 100
    
    refresh_str = get_input("Refresh from Feedly? (y/n)", default="y")
    refresh = refresh_str.lower().startswith('y')

    stream_id = None
    if refresh:
        sid = get_input("Stream ID (Optional, press Enter to skip)", default="")
        if sid:
            stream_id = sid

    default_mark = "y" if PROJ_CONFIG.get("mark_read") else "n"
    mark_read_str = get_input("Mark as read after analysis? (y/n)", default=default_mark)
    mark_read = mark_read_str.lower().startswith('y')

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
    default_filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename = get_input("Output Filename", default=default_filename)

    execute_export(limit, stream_id, filename)

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
    default_filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filename = questionary.text("Output Filename:", default=default_filename).ask()

    execute_export(limit, stream_id, filename, stream_label)

def execute_export(limit, stream_id, filename, stream_label=None):
    display_stream = stream_label if stream_label else (stream_id or 'Global (All)')
    console.print(Panel(
        f"Exporting Articles\n"
        f"Limit: {limit}\n"
        f"Stream: {display_stream}\n"
        f"Output: {filename}",
        title="Export Configuration",
        border_style="blue"
    ))

    try:
        import sys
        old_argv = sys.argv

        sys.argv = ['article_analyzer.py', '--limit', str(limit), '--export', filename]
        if stream_id:
            sys.argv.append('--stream-id')
            sys.argv.append(stream_id)

        try:
            try:
                import article_analyzer
            except Exception as e:
                console.print(Panel(_import_error_hint('article_analyzer', e), style="red"))
                return

            article_analyzer.main()
            console.print(Panel(f"Export Complete! File saved to {filename}", style="bold green"))
        finally:
            sys.argv = old_argv
    except Exception:
        logger.exception("Error exporting")
        console.print("[red]Export failed.[/red]")

def simple_filter_flow():
    """Fallback filter flow"""
    console.print("\n[bold]Select Filter Mode:[/bold]")
    console.print("1. All Filters (Newsflash + Low Score)")
    console.print("2. Newsflash Only")
    console.print("3. Low Score Only")
    console.print("4. Back")
    
    choice = get_input("Select mode")
    
    mode = "all"
    if choice == "1":
        mode = "all"
    elif choice == "2":
        mode = "newsflash"
    elif choice == "3":
        mode = "low-score"
    elif choice == "4":
        return
    else:
        console.print("[red]Invalid mode, defaulting to All[/red]")

    limit_str = get_input("Article Limit", default="500")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 500

    threshold = 3.0
    if mode in ["all", "low-score"]:
        t_str = get_input("Score Threshold", default="3.0")
        try:
            threshold = float(t_str)
        except ValueError:
            threshold = 3.0

    dr_str = get_input("Dry Run? (y/n)", default="n")
    dry_run = dr_str.lower().startswith('y')
    
    mark_read_str = get_input("Mark as read? (y/n)", default="n")
    mark_read = mark_read_str.lower().startswith('y')

    execute_filter(mode, limit, threshold, dry_run, mark_read=mark_read)

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
        if questionary.confirm("Continue with default Global Stream?", default=True).ask():
            return None, "Global (Default)"
        return None, None

    # Map counts
    # API returns: {"unreadcounts": [{"id": "...", "count": 123, "updated": ...}]}
    count_map = {item['id']: item['count'] for item in counts_data.get('unreadcounts', [])}

    # Create ID to Label mapping for return value
    id_to_label = {}

    choices = []

    # 1. Global All
    # We don't have the exact user ID readily available without loading config again or parsing stream IDs
    # But usually one of the unreadcounts entries is for global.all
    global_count = 0
    for cid, count in count_map.items():
        if 'global.all' in cid:
            global_count = count
            break

    global_label = f"Global All ({global_count} unread)"
    choices.append(questionary.Choice(global_label, value=None))
    id_to_label[None] = "Global All"

    # 2. Categories
    cat_choices = []
    for cat in categories:
        cid = cat['id']
        label = cat['label']
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
        fid = sub['id']
        title = sub['title']
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
        if i >= 50: # Limit to top 50 to avoid clutter
            break
        choices.append(questionary.Choice(f"{label} ({count} unread)", value=fid))

    choices.append(questionary.Separator("--- Other ---"))
    choices.append(questionary.Choice("Enter Stream ID manually", value="MANUAL"))

    stream_id = questionary.select(
        "Select Stream to Process:",
        choices=choices,
        style=questionary.Style([
            ('qmark', 'fg:cyan bold'),
            ('question', 'fg:cyan bold'),
            ('answer', 'fg:green bold'),
            ('pointer', 'fg:cyan bold'),
            ('highlighted', 'fg:cyan bold'),
            ('selected', 'fg:green bold'),
        ])
    ).ask()

    stream_label = None
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

    category_ids = {cat.get('id') for cat in categories}
    if stream_id in category_ids:
        matched_titles = []
        for sub in subscriptions:
            sub_categories = sub.get('categories', [])
            if any(cat.get('id') == stream_id for cat in sub_categories):
                title = sub.get('title')
                if title:
                    matched_titles.append(title)
        return matched_titles

    for sub in subscriptions:
        if sub.get('id') == stream_id:
            title = sub.get('title')
            return [title] if title else []

    return None


def filter_articles_by_titles(articles, titles):
    if titles is None:
        return articles
    if not titles:
        return []

    title_set = set(titles)
    return [a for a in articles if a.get('origin') in title_set]


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
        "  python -m pip install \"openai>=1.86.0,<2.0.0\"\n\n"
        "Diagnostics to paste:\n"
        "  python -V\n"
        "  python -c \"import platform; print(platform.architecture()); print(platform.python_version())\"\n"
        "  python -c \"import sys; print(sys.executable)\"\n"
        "  python -m pip -V\n"
        "  python -m pip show pydantic-core pydantic openai jiter langchain-openai\n"
    )


def _verify_startup_dependencies_or_exit() -> None:
    """Fail-fast dependency check.

    User preference: if LLM-related deps are broken (often due to Python upgrades
    making binary wheels like pydantic-core/jiter incompatible), show a clear
    message and exit before entering the menu.
    """
    # Importing these modules is enough to trigger the common failure modes.
    # Keep the import list minimal and aligned with the plan.
    required = [
        "feedly_filter",
        "article_analyzer",
        "regenerate_summary",
    ]

    for mod in required:
        try:
            __import__(mod)
        except Exception as e:
            console.print(Panel(_import_error_hint(mod, e), style="red"))
            raise SystemExit(1)


def main_menu():
    """Fancy menu using questionary"""
    try:
        import questionary
        # Test if we can access the prompt session (catch NoConsoleScreenBufferError)
        import prompt_toolkit # noqa: F401
    except ImportError:
        simple_menu()
        return

    console.clear()
    console.print(Panel.fit("Feedly AI Filter TUI", style="bold cyan", subtitle="Interactive Runner"))
    
    while True:
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("Run Filter", value="run"),
                questionary.Choice("Analyze Articles", value="analyze"),
                questionary.Choice("Regenerate Summary", value="summary"),
                questionary.Choice("Export Articles", value="export"),
                questionary.Choice("Exit", value="exit")
            ],
            style=questionary.Style([
                ('qmark', 'fg:cyan bold'),
                ('question', 'fg:cyan bold'),
                ('answer', 'fg:green bold'),
                ('pointer', 'fg:cyan bold'),
                ('highlighted', 'fg:cyan bold'),
                ('selected', 'fg:green bold'),
            ])
        ).ask()
        
        if action == "exit":
            console.print("[cyan]Goodbye![/cyan]")
            sys.exit()
        elif action == "run":
            run_filter_flow()
            input("\nPress Enter to return to menu...")
            console.clear()
            console.print(Panel.fit("Feedly AI Filter TUI", style="bold cyan", subtitle="Interactive Runner"))
        elif action == "analyze":
            run_analyze_flow()
            input("\nPress Enter to return to menu...")
            console.clear()
            console.print(Panel.fit("Feedly AI Filter TUI", style="bold cyan", subtitle="Interactive Runner"))
        elif action == "summary":
            run_summary_flow()
            input("\nPress Enter to return to menu...")
            console.clear()
            console.print(Panel.fit("Feedly AI Filter TUI", style="bold cyan", subtitle="Interactive Runner"))
        elif action == "export":
            run_export_flow()
            input("\nPress Enter to return to menu...")
            console.clear()
            console.print(Panel.fit("Feedly AI Filter TUI", style="bold cyan", subtitle="Interactive Runner"))

def run_summary_flow():
    try:
        import questionary
    except ImportError:
        console.print(Panel("Regenerating Summary...", style="bold blue"))
        try:
            try:
                import regenerate_summary
            except Exception as e:
                console.print(Panel(_import_error_hint('regenerate_summary', e), style="red"))
                return

            regenerate_summary.main()
            console.print(Panel("Summary Generation Complete!", style="bold green"))
        except Exception:
            logger.exception("Error generating summary")
            console.print("[red]Failed to generate summary.[/red]")
        return

    mode = questionary.select(
        "Summary Mode:",
        choices=[
            questionary.Choice("Summarize local analyzed articles", value="local"),
            questionary.Choice("Refresh from Feedly (analyze & summarize)", value="refresh"),
            questionary.Choice("Back", value="back")
        ]
    ).ask()

    if mode == "back":
        return

    stream_id, stream_label = select_stream_interactive()
    if stream_id is None and stream_label is None:
        return

    if mode == "local":
        console.print(Panel("Summarizing Local Articles...", style="bold blue"))
        try:
            console.print("[dim]Loading analyzed_articles.json...[/dim]")
            articles = load_articles('analyzed_articles.json')

            if stream_id:
                console.print("[dim]Resolving selected stream...[/dim]")
                titles = resolve_stream_feed_titles(stream_id)
                if titles is None:
                    console.print("[yellow]Unable to resolve stream to feeds. Using all local articles.[/yellow]")
                articles = filter_articles_by_titles(articles, titles)

            if not articles:
                console.print("[yellow]No articles matched the selection.[/yellow]")
                return

            try:
                import regenerate_summary
            except Exception as e:
                console.print(Panel(_import_error_hint('regenerate_summary', e), style="red"))
                return

            summary_file, latest_file = regenerate_summary.generate_summary_from_articles(articles)
            console.print(Panel(
                f"Summary Generation Complete!\n- {summary_file}\n- {latest_file}",
                style="bold green"
            ))
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

    mark_read = questionary.confirm("Mark as read after analysis?", default=PROJ_CONFIG.get("mark_read", False)).ask()

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
        use_stream = questionary.confirm("Select specific Category/Feed?", default=False).ask()
        if use_stream:
            stream_id, stream_label = select_stream_interactive()

    mark_read = questionary.confirm("Mark as read after analysis?", default=PROJ_CONFIG.get("mark_read", False)).ask()

    threads_str = questionary.text("Number of threads:", default="3").ask()
    try:
        threads = int(threads_str)
    except ValueError:
        console.print("[red]Invalid thread count, using default 3[/red]")
        threads = 3

    execute_analyze(limit, refresh, mark_read, stream_id, threads, stream_label)

def execute_analyze(limit, refresh, mark_read, stream_id=None, threads=3, stream_label=None):
    """Shared analyze execution logic"""
    display_stream = stream_label if stream_label else (stream_id or 'Global (All)')
    console.print(Panel(
        f"Analyzing Articles\n"
        f"Limit: {limit}\n"
        f"Refresh: {refresh}\n"
        f"Stream: {display_stream}\n"
        f"Mark Read: {mark_read}\n"
        f"Threads: {threads}",
        title="Configuration",
        border_style="blue"
    ))

    try:
        # Build command line arguments for article_analyzer
        import sys
        old_argv = sys.argv

        sys.argv = ['article_analyzer.py', '--limit', str(limit)]
        if refresh:
            sys.argv.append('--refresh')
        if mark_read:
            sys.argv.append('--mark-read')
        if stream_id:
            sys.argv.append('--stream-id')
            sys.argv.append(stream_id)
        if threads:
            sys.argv.append('--threads')
            sys.argv.append(str(threads))

        try:
            # Call article_analyzer.main() which will parse sys.argv
            try:
                import article_analyzer
            except Exception as e:
                console.print(Panel(_import_error_hint('article_analyzer', e), style="red"))
                return

            article_analyzer.main()
            console.print(Panel("Article Analysis Complete!", style="bold green"))
        finally:
            # Restore sys.argv
            sys.argv = old_argv
        
    except KeyboardInterrupt:
        console.print("\n[red]Operation cancelled by user.[/red]")
    except Exception as e:
        logger.exception("An error occurred during analysis")
        console.print("[red]An error occurred. Check logs above.[/red]")

def execute_filter(mode, limit, threshold, dry_run, mark_read, stream_id=None, stream_label=None):
    """Shared execution logic"""
    display_stream = stream_label if stream_label else (stream_id or 'Global (All)')
    console.print(Panel(
        f"Running Mode: [bold]{mode}[/bold]\n"
        f"Limit: {limit}\n"
        f"Threshold: {threshold}\n"
        f"Stream: {display_stream}\n"
        f"Dry Run: {dry_run}\n"
        f"Mark Read: {mark_read}",
        title="Configuration",
        border_style="blue"
    ))

    try:
        filters = []
        articles = []

        # Determine target stream (priority: explicitly passed stream_id > mode default)
        target_stream = stream_id

        try:
            import feedly_filter
        except Exception as e:
            console.print(Panel(_import_error_hint('feedly_filter', e), style="red"))
            return

        if mode == 'newsflash':
            # For newsflash, usually we target 36kr, but if user provided a stream, use that
            if not target_stream:
                target_stream = feedly_filter.FEED_ID_36KR

            articles = feedly_filter.fetch_articles(limit, stream_id=target_stream)
            filters = [feedly_filter.newsflash_filter]
        elif mode == 'low-score':
            articles = feedly_filter.fetch_articles(limit, stream_id=target_stream)
            filters = [lambda a: feedly_filter.low_score_filter(a, threshold, dry_run, mark_read)]
        else:  # all
            articles = feedly_filter.fetch_articles(limit, stream_id=target_stream)
            filters = [
                feedly_filter.newsflash_filter,
                lambda a: feedly_filter.low_score_filter(a, threshold, dry_run, mark_read)
            ]

        if not articles:
            console.print("[yellow]No unread articles found.[/yellow]")
            return

        feedly_filter.run_filters(articles, filters, dry_run, mark_read)
        console.print(Panel("Analysis Complete!", style="bold green"))
        
    except KeyboardInterrupt:
        console.print("\n[red]Operation cancelled by user.[/red]")
    except Exception as e:
        logger.exception("An error occurred during execution")
        console.print("[red]An error occurred. Check logs above.[/red]")

def run_filter_flow():
    import questionary
    # 1. Select Mode
    mode = questionary.select(
        "Select Filter Mode:",
        choices=[
            questionary.Choice("All Filters (Newsflash + Low Score)", value="all"),
            questionary.Choice("Newsflash Only (36kr)", value="newsflash"),
            questionary.Choice("Low Score Only (AI Scoring)", value="low-score"),
            questionary.Choice("Back", value="back")
        ]
    ).ask()
    
    if mode == "back":
        return

    # 2. Configure Parameters
    limit_str = questionary.text("Article Limit:", default="500").ask()
    try:
        limit = int(limit_str)
    except ValueError:
        console.print("[red]Invalid limit, using default 500[/red]")
        limit = 500

    threshold = 3.0
    if mode in ["all", "low-score"]:
        threshold_str = questionary.text("Score Threshold:", default="3.0").ask()
        try:
            threshold = float(threshold_str)
        except ValueError:
            console.print("[red]Invalid threshold, using default 3.0[/red]")
            threshold = 3.0

    dry_run = questionary.confirm("Dry Run? (Simulate only, no changes)", default=False).ask()

    # 4. Stream Selection
    stream_id = None
    stream_label = None
    use_stream = questionary.confirm("Select specific Category/Feed?", default=False).ask()
    if use_stream:
        stream_id, stream_label = select_stream_interactive()

    # 3. Execution
    mark_read = questionary.confirm("Mark as read after filter?", default=PROJ_CONFIG.get("mark_read", False)).ask()

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
            console.print("[yellow]Interactive console not detected. Switching to simple mode...[/yellow]")
            simple_menu()
        else:
            raise e
