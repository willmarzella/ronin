#!/usr/bin/env python3
"""Job search CLI with progress display."""

import sys

from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table

from ronin.analyzer import JobAnalyzerService
from ronin.application_queue import ApplicationQueueService
from ronin.config import get_ronin_home, load_config, load_env
from ronin.db import get_db_manager
from ronin.scraper import SeekScraper

console = Console()


def _rich_sink(message: str) -> None:
    console.print(message.rstrip(), highlight=False)


def _configure_logging() -> None:
    """Add search-specific log handlers (file + Rich console)."""
    log_dir = get_ronin_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_dir / "search.log"),
        rotation="10 MB",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}",
    )
    logger.add(
        _rich_sink,
        level="INFO",
        format="<dim>{time:HH:mm:ss}</dim> | <level>{level: <7}</level> | {message}",
    )


def main():
    """Main job search function."""
    load_env()
    _configure_logging()

    console.print("\n[bold blue]Ronin Job Search[/bold blue]\n")

    try:
        config = load_config()

        # Best-effort: flush any locally spooled rows into Postgres first.
        try:
            from ronin.spool_sync import sync_spool_to_remote

            spool_stats = sync_spool_to_remote(config=config, dry_run=False)
            if (
                spool_stats
                and not spool_stats.get("skipped")
                and not spool_stats.get("error")
            ):
                touched = (
                    int(spool_stats.get("jobs_inserted", 0) or 0)
                    + int(spool_stats.get("jobs_status_updated", 0) or 0)
                    + int(spool_stats.get("applications_inserted", 0) or 0)
                    + int(spool_stats.get("variants_upserted", 0) or 0)
                )
                if touched:
                    console.print(
                        "[dim]Flushed local spool to remote Postgres before search.[/dim]"
                    )
        except Exception:
            pass

        keywords = config["search"]["keywords"]
        console.print(f"[dim]Searching for {len(keywords)} keyword groups...[/dim]\n")

        scraper = SeekScraper(config)
        analyzer = JobAnalyzerService(config)
        db_manager = get_db_manager(config=config)

        # Phase 1: Scrape job previews
        with console.status("[bold green]Scraping job listings from Seek..."):
            previews = scraper.get_job_previews()

        if not previews:
            console.print("[yellow]No jobs found matching your criteria[/yellow]")
            return

        console.print(f"[green]✓[/green] Found {len(previews)} matching listings\n")

        # Phase 2: Fetch full job details with progress bar
        jobs = []
        skipped_quick_apply = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "[cyan]Fetching job details...", total=len(previews)
            )

            for preview in previews:
                title = preview.get("title", "Unknown")[:35]
                company = preview.get("company", "Unknown")[:20]
                progress.update(task, description=f"[cyan]{title} @ {company}")

                details = scraper.get_job_details(preview["job_id"])
                if details:
                    if scraper.quick_apply_only and not details.get(
                        "quick_apply", False
                    ):
                        skipped_quick_apply += 1
                    else:
                        jobs.append({**preview, **details})

                progress.advance(task)

        if skipped_quick_apply > 0:
            console.print(
                f"[dim]Skipped {skipped_quick_apply} without quick apply[/dim]"
            )
        console.print(f"[green]✓[/green] Fetched details for {len(jobs)} jobs\n")

        if not jobs:
            console.print("[yellow]No jobs with quick apply found[/yellow]")
            return

        # Phase 3: Filter duplicates
        stats = db_manager.get_jobs_stats()
        existing_count = stats.get("total_jobs", 0)

        new_jobs = []
        duplicate_count = 0

        for job in jobs:
            job_id = job.get("job_id", "")
            if job_id and db_manager.job_exists(job_id):
                duplicate_count += 1
            else:
                new_jobs.append(job)

        if duplicate_count > 0:
            console.print(
                f"[dim]Skipped {duplicate_count} duplicates "
                f"(checked against {existing_count} existing)[/dim]"
            )

        if not new_jobs:
            console.print("[yellow]No new jobs to analyze[/yellow]")
            return

        console.print(f"[green]✓[/green] {len(new_jobs)} new jobs to analyze\n")

        # Phase 4: Analyze jobs with AI
        analyzed_jobs = []
        failed_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Analyzing jobs...", total=len(new_jobs))

            for job in new_jobs:
                title = job.get("title", "Unknown")[:35]
                company = job.get("company", "Unknown")[:20]
                progress.update(task, description=f"[cyan]{title} @ {company}")

                try:
                    analyzed_job = analyzer.analyze_job(job)
                    if analyzed_job:
                        analyzed_jobs.append(analyzed_job)
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.error(
                        f"Analysis failed for {job.get('title', 'unknown')}: {e}"
                    )

                progress.advance(task)

        if failed_count > 0:
            console.print(f"[dim]Failed to analyze {failed_count} jobs[/dim]")

        if not analyzed_jobs:
            console.print("[yellow]No jobs were successfully analyzed[/yellow]")
            return

        console.print(f"[green]✓[/green] Analyzed {len(analyzed_jobs)} jobs\n")

        # Phase 5: Save to database
        with console.status("[bold green]Saving to database..."):
            results = db_manager.batch_insert_jobs(analyzed_jobs)

        queue_stats = {}
        with console.status("[bold green]Scoring queue alignment..."):
            queue_service = ApplicationQueueService(
                config=config, db_manager=db_manager
            )
            queue_stats = queue_service.recompute_queue()

        # Results summary
        console.print()
        table = Table(title="Results", show_header=False, border_style="dim")
        table.add_column("Metric", style="dim")
        table.add_column("Value", style="bold")

        table.add_row("New jobs added", f"[green]{results['new_jobs']}[/green]")
        table.add_row(
            "Duplicates skipped",
            f"[yellow]{duplicate_count + results['duplicates']}[/yellow]",
        )
        if results["errors"] > 0:
            table.add_row("Errors", f"[red]{results['errors']}[/red]")

        if queue_stats:
            table.add_row(
                "Queue evaluated",
                str(queue_stats.get("evaluated", 0)),
            )
            table.add_row(
                "Market-intel only",
                str(queue_stats.get("market_intelligence", 0)),
            )

        console.print(table)
        console.print()

    except KeyboardInterrupt:
        console.print("\n[yellow]Search cancelled[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
