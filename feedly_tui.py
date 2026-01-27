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
    
    mark_read_str = get_input("Mark as read after analysis? (y/n)", default="n")
    mark_read = mark_read_str.lower().startswith('y')
    
    execute_analyze(limit, refresh, mark_read)

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
    mark_read = questionary.confirm("Mark as read after analysis?", default=False).ask()
    
    execute_analyze(limit, refresh, mark_read)

def execute_analyze(limit, refresh, mark_read):
    """Shared analyze execution logic"""
    console.print(Panel(
        f"Analyzing Articles\n"
        f"Limit: {limit}\n"
        f"Refresh: {refresh}\n"
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

def execute_filter(mode, limit, threshold, dry_run):
    """Shared execution logic"""
    console.print(Panel(f"Running Mode: [bold]{mode}[/bold]\nLimit: {limit}\nThreshold: {threshold}\nDry Run: {dry_run}", title="Configuration", border_style="blue"))
    
    try:
        filters = []
        articles = []
        
        if mode == 'newsflash':
            articles = feedly_filter.fetch_articles(limit, stream_id=feedly_filter.FEED_ID_36KR)
            filters = [feedly_filter.newsflash_filter]
        elif mode == 'low-score':
            articles = feedly_filter.fetch_articles(limit)
            filters = [lambda a: feedly_filter.low_score_filter(a, threshold, dry_run)]
        else:  # all
            articles = feedly_filter.fetch_articles(limit)
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

    # 3. Execution
    execute_filter(mode, limit, threshold, dry_run)

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
