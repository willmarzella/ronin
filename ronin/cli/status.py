"""Status dashboard for Ronin.

Displays configuration, database statistics, schedule state, and last
run times using Rich tables.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from loguru import logger
from rich.console import Console
from rich.table import Table

from ronin.config import get_ronin_home

console = Console()


def _find_config_path() -> Optional[Path]:
    """Locate the config file without raising on absence.

    Returns:
        Path to config.yaml if found, else None.
    """
    user_config = get_ronin_home() / "config.yaml"
    if user_config.exists():
        return user_config

    project_config = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    if project_config.exists():
        return project_config

    return None


def _find_profile_path() -> Optional[Path]:
    """Locate the profile/resume directory.

    Returns:
        Path to the resumes directory if it exists, else None.
    """
    resumes_dir = get_ronin_home() / "resumes"
    if resumes_dir.exists() and any(resumes_dir.iterdir()):
        return resumes_dir
    return None


def _get_db_stats() -> Dict:
    """Query the database for job statistics.

    Returns:
        Dict with total_jobs, by_status, and by_source breakdowns.
        Empty dict on failure.
    """
    try:
        from ronin.db import get_db_manager

        db = get_db_manager()
        stats = db.get_jobs_stats()
        db.close()
        return stats
    except Exception as exc:
        logger.debug(f"Could not read database: {exc}")
        return {}


def _get_outcome_stats() -> Dict:
    """Query tracked application outcomes for feedback-loop visibility."""
    try:
        from ronin.db import get_db_manager

        db = get_db_manager()
        stats = db.get_application_outcome_stats()
        db.close()
        return stats
    except Exception as exc:
        logger.debug(f"Could not read outcome stats: {exc}")
        return {}


def _get_queue_summary() -> Dict:
    """Read queue grouping for archetype batch workflows."""
    try:
        from ronin.db import get_db_manager

        db = get_db_manager()
        summary = db.get_queue_summary()
        db.close()
        return summary
    except Exception as exc:
        logger.debug(f"Could not read queue summary: {exc}")
        return {}


def _get_active_alert_count() -> int:
    """Count unacknowledged drift alerts."""
    try:
        from ronin.db import get_db_manager

        db = get_db_manager()
        count = len(db.get_unacknowledged_alerts())
        db.close()
        return count
    except Exception as exc:
        logger.debug(f"Could not read drift alerts: {exc}")
        return 0


def _get_last_run(log_name: str) -> Optional[str]:
    """Get the last modification time of a log file.

    Args:
        log_name: Filename inside the logs directory (e.g. ``search.log``).

    Returns:
        ISO-formatted timestamp string, or None if the file doesn't exist.
    """
    for logs_dir in [get_ronin_home() / "logs", Path("logs")]:
        log_path = logs_dir / log_name
        if log_path.exists():
            mtime = log_path.stat().st_mtime
            return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    return None


def show_status() -> None:
    """Display the Ronin status dashboard."""
    console.print("\n[bold blue]Ronin Status Dashboard[/bold blue]\n")

    # -- Configuration -------------------------------------------------------
    config_table = Table(
        title="Configuration",
        show_header=False,
        border_style="dim",
        pad_edge=False,
    )
    config_table.add_column("Key", style="dim", min_width=20)
    config_table.add_column("Value")

    config_path = _find_config_path()
    if config_path:
        config_table.add_row("Config", f"[green]{config_path}[/green]")
    else:
        config_table.add_row("Config", "[red]Not found[/red]")

    profile_path = _find_profile_path()
    if profile_path:
        config_table.add_row("Profiles", f"[green]{profile_path}[/green]")
    else:
        config_table.add_row("Profiles", "[yellow]None[/yellow]")

    config_table.add_row("Ronin home", str(get_ronin_home()))
    console.print(config_table)
    console.print()

    # -- Database stats ------------------------------------------------------
    stats = _get_db_stats()

    db_table = Table(
        title="Database",
        show_header=False,
        border_style="dim",
        pad_edge=False,
    )
    db_table.add_column("Key", style="dim", min_width=20)
    db_table.add_column("Value")

    if stats:
        db_table.add_row("Total jobs", str(stats.get("total_jobs", 0)))

        by_status: Dict = stats.get("by_status", {})
        for status_name in ["DISCOVERED", "APPLIED", "STALE", "APP_ERROR"]:
            count = by_status.get(status_name, 0)
            if status_name == "APPLIED":
                style = "green"
            elif status_name == "DISCOVERED":
                style = "cyan"
            elif status_name == "STALE":
                style = "yellow"
            else:
                style = "red"
            db_table.add_row(f"  {status_name}", f"[{style}]{count}[/{style}]")

        by_source: Dict = stats.get("by_source", {})
        if by_source:
            db_table.add_row("", "")
            for source, count in by_source.items():
                db_table.add_row(f"  Source: {source}", str(count))
    else:
        db_table.add_row("Status", "[yellow]No database found[/yellow]")

    console.print(db_table)
    console.print()

    # -- Queue summary -------------------------------------------------------
    queue_summary = _get_queue_summary()
    if queue_summary:
        queue_table = Table(
            title="Application Queue",
            show_header=False,
            border_style="dim",
            pad_edge=False,
        )
        queue_table.add_column("Key", style="dim", min_width=20)
        queue_table.add_column("Value")

        for key in ["builder", "fixer", "operator", "translator", "market_intel"]:
            values = queue_summary.get(key)
            if not values:
                continue
            label = "Market intel" if key == "market_intel" else key.capitalize()
            queue_table.add_row(
                f"{label}",
                f"{int(values.get('count', 0))} (avg {float(values.get('avg_score', 0.0)):.2f})",
            )

        active_alerts = _get_active_alert_count()
        queue_table.add_row("Active drift alerts", str(active_alerts))

        console.print(queue_table)
        console.print()

    # -- Outcome feedback stats ----------------------------------------------
    outcome_stats = _get_outcome_stats()
    if outcome_stats.get("total", 0) > 0:
        feedback_table = Table(
            title="Feedback Loop",
            show_header=False,
            border_style="dim",
            pad_edge=False,
        )
        feedback_table.add_column("Key", style="dim", min_width=20)
        feedback_table.add_column("Value")

        feedback_table.add_row(
            "Tracked applications", str(outcome_stats.get("total", 0))
        )
        feedback_table.add_row(
            "Resolved outcomes", str(outcome_stats.get("resolved", 0))
        )
        feedback_table.add_row(
            "Positive outcomes",
            str(outcome_stats.get("positive", 0)),
        )
        feedback_table.add_row(
            "Positive rate",
            f"{outcome_stats.get('conversion_rate', 0.0):.1%}",
        )

        by_outcome = outcome_stats.get("by_outcome", {})
        for key in ["PENDING", "REJECTION", "CALLBACK", "INTERVIEW", "OFFER"]:
            if key in by_outcome:
                feedback_table.add_row(f"  {key}", str(by_outcome[key]))

        console.print(feedback_table)
        console.print()

    # -- Schedule ------------------------------------------------------------
    schedule_table = Table(
        title="Schedule",
        show_header=False,
        border_style="dim",
        pad_edge=False,
    )
    schedule_table.add_column("Key", style="dim", min_width=20)
    schedule_table.add_column("Value")

    try:
        from ronin.scheduler import get_schedule_status

        sched = get_schedule_status()
        if sched.get("installed"):
            schedule_table.add_row("Status", "[green]Installed[/green]")
            schedule_table.add_row("Platform", sched.get("platform", "unknown"))
            schedule_table.add_row(
                "Interval", f"every {sched.get('interval_hours', '?')}h"
            )
            if sched.get("next_run"):
                schedule_table.add_row("Next run", sched["next_run"])
        else:
            schedule_table.add_row("Status", "[yellow]Not installed[/yellow]")
            schedule_table.add_row("Platform", sched.get("platform", "unknown"))
    except Exception as exc:
        logger.debug(f"Could not read schedule status: {exc}")
        schedule_table.add_row("Status", "[red]Error reading schedule[/red]")

    console.print(schedule_table)
    console.print()

    # -- Last runs -----------------------------------------------------------
    runs_table = Table(
        title="Last Runs",
        show_header=False,
        border_style="dim",
        pad_edge=False,
    )
    runs_table.add_column("Key", style="dim", min_width=20)
    runs_table.add_column("Value")

    last_search = _get_last_run("search.log")
    last_apply = _get_last_run("apply.log")
    last_ronin = _get_last_run("ronin.log")

    runs_table.add_row(
        "Last search",
        last_search if last_search else "[dim]never[/dim]",
    )
    runs_table.add_row(
        "Last apply",
        last_apply if last_apply else "[dim]never[/dim]",
    )
    runs_table.add_row(
        "Last activity",
        last_ronin if last_ronin else "[dim]never[/dim]",
    )

    console.print(runs_table)
    console.print()
