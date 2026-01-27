#!/usr/bin/env python3
"""
Feedly AI Filter TUI Runner
Interactive menu for running Feedly filters.
"""
import sys
import logging
import os
import feedly_filter
import regenerate_summary
import article_analyzer
from rss_analyzer.feedly_client import feedly_get_categories, feedly_get_subscriptions, feedly_get_unread_counts
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
        console.print("4. Exit")
        
        choice = get_input("Select an option")
        
        if choice == "4":
            console.print("[cyan]Goodbye![/cyan]")
            sys.exit()
        elif choice == "1":
            simple_filter_flow()
        elif choice == "2":
            simple_analyze_flow()
        elif choice == "3":
            run_summary_flow()
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

    mark_read_str = get_input("Mark as read after analysis? (y/n)", default="n")
    mark_read = mark_read_str.lower().startswith('y')

    execute_analyze(limit, refresh, mark_read, stream_id)

def simple_filter_flow():
    """Fallback filter flow"""
    console.print("\n[bold]Select Filter Mode:[/bold]")
    console.print("1. All Filters (Newsflash + Low Score)")
    console.print("2. Newsflash Only")
    console.print("3. Low Score Only")
    console.print("4. Back")
    
    choice = get_input("Select mode")
    
    mode = "all"
    if choice == "1": mode = "all"
    elif choice == "2": mode = "newsflash"
    elif choice == "3": mode = "low-score"
    elif choice == "4": return
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
    
    execute_filter(mode, limit, threshold, dry_run)

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
            return None
        return None

    # Map counts
    # API returns: {"unreadcounts": [{"id": "...", "count": 123, "updated": ...}]}
    count_map = {item['id']: item['count'] for item in counts_data.get('unreadcounts', [])}

    choices = []

    # 1. Global All
    # We don't have the exact user ID readily available without loading config again or parsing stream IDs
    # But usually one of the unreadcounts entries is for global.all
    global_count = 0
    for cid, count in count_map.items():
        if 'global.all' in cid:
            global_count = count
            break

    choices.append(questionary.Choice(f"Global All ({global_count} unread)", value=None))

    # 2. Categories
    cat_choices = []
    for cat in categories:
        cid = cat['id']
        label = cat['label']
        count = count_map.get(cid, 0)
        if count > 0:
            cat_choices.append((count, f"📁 Category: {label}", cid))

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
            feed_choices.append((count, f"📰 Feed: {title}", fid))

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

    if stream_id == "MANUAL":
        stream_id = questionary.text("Enter Stream ID:").ask()
        if not stream_id:
            return None

    return stream_id


def main_menu():
    """Fancy menu using questionary"""
    try:
        import questionary
        # Test if we can access the prompt session (catch NoConsoleScreenBufferError)
        import prompt_toolkit
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

def run_summary_flow():
    console.print(Panel("Regenerating Summary...", style="bold blue"))
    try:
        regenerate_summary.main()
        console.print(Panel("Summary Generation Complete!", style="bold green"))
    except Exception as e:
        logger.exception("Error generating summary")
        console.print("[red]Failed to generate summary.[/red]")

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
    if refresh:
        # Only ask for stream if we are refreshing
        use_stream = questionary.confirm("Select specific Category/Feed?", default=False).ask()
        if use_stream:
            stream_id = select_stream_interactive()

    mark_read = questionary.confirm("Mark as read after analysis?", default=False).ask()

    execute_analyze(limit, refresh, mark_read, stream_id)

def execute_analyze(limit, refresh, mark_read, stream_id=None):
    """Shared analyze execution logic"""
    console.print(Panel(
        f"Analyzing Articles\n"
        f"Limit: {limit}\n"
        f"Refresh: {refresh}\n"
        f"Stream: {stream_id or 'Global (All)'}\n"
        f"Mark Read: {mark_read}",
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

        try:
            # Call article_analyzer.main() which will parse sys.argv
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

def execute_filter(mode, limit, threshold, dry_run, stream_id=None):
    """Shared execution logic"""
    console.print(Panel(
        f"Running Mode: [bold]{mode}[/bold]\n"
        f"Limit: {limit}\n"
        f"Threshold: {threshold}\n"
        f"Stream: {stream_id or 'Global (All)'}\n"
        f"Dry Run: {dry_run}",
        title="Configuration",
        border_style="blue"
    ))

    try:
        filters = []
        articles = []

        # Determine target stream (priority: explicitly passed stream_id > mode default)
        target_stream = stream_id

        if mode == 'newsflash':
            # For newsflash, usually we target 36kr, but if user provided a stream, use that
            if not target_stream:
                target_stream = feedly_filter.FEED_ID_36KR

            articles = feedly_filter.fetch_articles(limit, stream_id=target_stream)
            filters = [feedly_filter.newsflash_filter]
        elif mode == 'low-score':
            articles = feedly_filter.fetch_articles(limit, stream_id=target_stream)
            filters = [lambda a: feedly_filter.low_score_filter(a, threshold, dry_run)]
        else:  # all
            articles = feedly_filter.fetch_articles(limit, stream_id=target_stream)
            filters = [
                feedly_filter.newsflash_filter,
                lambda a: feedly_filter.low_score_filter(a, threshold, dry_run)
            ]

        if not articles:
            console.print("[yellow]No unread articles found.[/yellow]")
            return

        feedly_filter.run_filters(articles, filters, dry_run)
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
    use_stream = questionary.confirm("Select specific Category/Feed?", default=False).ask()
    if use_stream:
        stream_id = select_stream_interactive()

    # 3. Execution
    execute_filter(mode, limit, threshold, dry_run, stream_id)

if __name__ == "__main__":
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
