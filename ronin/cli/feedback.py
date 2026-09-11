#!/usr/bin/env python3
"""Closed-loop feedback CLI commands."""

from __future__ import annotations

import sys

from loguru import logger
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from ronin.config import get_ronin_home, load_config, load_env
from ronin.db import get_db_manager
from ronin.feedback import GmailOutcomeTracker, OutcomeAnalytics

console = Console()


def _rich_sink(message: str) -> None:
    console.print(message.rstrip(), highlight=False)


def _configure_logging() -> None:
    log_dir = get_ronin_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_dir / "feedback.log"),
        rotation="10 MB",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}",
    )
    logger.add(
        _rich_sink,
        level="INFO",
        format="<dim>{time:HH:mm:ss}</dim> | <level>{level: <7}</level> | {message}",
    )


def sync_gmail_outcomes(max_messages: int = 250, dry_run: bool = False) -> int:
    """Sync Gmail outcomes into the local applications feedback tables."""
    load_env()
    _configure_logging()

    console.print("\n[bold blue]Ronin Feedback Sync[/bold blue]\n")

    db_manager = None
    try:
        config = load_config()
        tracking_cfg = config.get("tracking", {}).get("gmail", {})

        db_manager = get_db_manager(config=config)

        query = tracking_cfg.get("query", "newer_than:1d")
        auth_mode = tracking_cfg.get("auth_mode", "auto")
        credentials_path = tracking_cfg.get("credentials_path")
        token_path = tracking_cfg.get("token_path")
        max_messages = int(
            max_messages or tracking_cfg.get("max_messages_per_sync", 250)
        )

        tracker = GmailOutcomeTracker(
            db_manager=db_manager,
            credentials_path=credentials_path,
            token_path=token_path,
            query=query,
            auth_mode=auth_mode,
        )

        stats = tracker.sync(max_messages=max_messages, dry_run=dry_run)

        table = Table(title="Gmail Outcome Sync", show_header=False, border_style="dim")
        table.add_column("Metric", style="dim")
        table.add_column("Value", style="bold")
        table.add_row("Query", query)
        table.add_row("Emails scanned", str(stats["emails_scanned"]))
        table.add_row("Outcome emails", str(stats["outcome_emails"]))
        table.add_row("Events recorded", str(stats["events_recorded"]))
        table.add_row("Matched to applications", str(stats["matched"]))
        table.add_row("Manual review", str(stats.get("manual_review", 0)))
        table.add_row("Ignored senders", str(stats.get("ignored", 0)))
        table.add_row("Duplicates skipped", str(stats["duplicates"]))
        table.add_row("Dry run", "yes" if dry_run else "no")
        console.print(table)
        console.print()
        return 0

    except Exception as e:
        console.print(f"[red]Feedback sync failed:[/red] {e}")
        return 1
    finally:
        if db_manager:
            db_manager.close()


def show_feedback_report(min_samples: int = 2) -> int:
    """Render a conversion report from tracked outcomes."""
    load_env()
    _configure_logging()

    console.print("\n[bold blue]Ronin Feedback Report[/bold blue]\n")

    db_manager = get_db_manager()
    analytics = OutcomeAnalytics(db_manager=db_manager)

    try:
        report = analytics.build_feedback_report(min_samples=max(1, int(min_samples)))
        outcome_stats = report.get("outcome_stats", {})

        overview = Table(title="Outcomes", show_header=False, border_style="dim")
        overview.add_column("Metric", style="dim")
        overview.add_column("Value", style="bold")

        overview.add_row("Applications tracked", str(outcome_stats.get("total", 0)))
        overview.add_row("Resolved outcomes", str(outcome_stats.get("resolved", 0)))
        overview.add_row("Positive outcomes", str(outcome_stats.get("positive", 0)))
        overview.add_row(
            "Positive rate",
            f"{outcome_stats.get('conversion_rate', 0.0):.1%}",
        )

        by_outcome = outcome_stats.get("by_outcome", {})
        for outcome in [
            "PENDING",
            "ACKNOWLEDGED",
            "VIEWED",
            "REJECTION",
            "INTERVIEW",
            "OFFER",
            "GHOST",
        ]:
            if outcome in by_outcome:
                overview.add_row(f"  {outcome}", str(by_outcome[outcome]))

        console.print(overview)
        console.print()

        resumes = report.get("resume_performance", [])
        if resumes:
            table = Table(title="Resume Performance", border_style="dim")
            table.add_column("Profile", style="cyan")
            table.add_column("Archetype", style="magenta")
            table.add_column("Positive", justify="right")
            table.add_column("Total", justify="right")
            table.add_column("Rate", justify="right")
            for row in resumes[:8]:
                table.add_row(
                    row["resume_profile"],
                    row["resume_archetype"],
                    str(row["positive"]),
                    str(row["total"]),
                    f"{row['positive_rate']:.1%}",
                )
            console.print(table)
            console.print()

        keywords = report.get("keyword_performance", [])
        if keywords:
            table = Table(title="Keyword Conversion", border_style="dim")
            table.add_column("Keyword", style="cyan")
            table.add_column("Positive", justify="right")
            table.add_column("Total", justify="right")
            table.add_column("Rate", justify="right")
            for row in keywords[:8]:
                table.add_row(
                    row["keyword"],
                    str(row["positive"]),
                    str(row["total"]),
                    f"{row['positive_rate']:.1%}",
                )
            console.print(table)
            console.print()

        mappings = report.get("role_title_mappings", [])
        if mappings:
            table = Table(title="Role-Title Mappings", border_style="dim")
            table.add_column("Title family", style="cyan")
            table.add_column("Best profile", style="green")
            table.add_column("Archetype", style="magenta")
            table.add_column("Profile rate", justify="right")
            table.add_column("Family total", justify="right")
            for row in mappings[:8]:
                table.add_row(
                    row["title_family"],
                    row["best_resume_profile"],
                    row["best_resume_archetype"],
                    f"{row['best_profile_rate']:.1%}",
                    str(row["family_total"]),
                )
            console.print(table)
            console.print()

        if not resumes and not keywords and not mappings:
            console.print(
                "[yellow]Not enough resolved outcomes yet to compute feedback signals.[/yellow]"
            )
            console.print(
                "[dim]Run `ronin feedback sync` after outcomes land in Gmail.[/dim]"
            )
            console.print()

        return 0

    except Exception as e:
        console.print(f"[red]Feedback report failed:[/red] {e}")
        return 1
    finally:
        analytics.close()
        db_manager.close()


def add_sender_ignore(
    sender_domain: str = "",
    sender_address: str = "",
    reason: str = "",
) -> int:
    """Add a sender/domain rule to the ignore list."""
    load_env()
    _configure_logging()

    db = get_db_manager()
    try:
        if not sender_domain and not sender_address:
            console.print(
                "[red]Provide --domain or --address to add an ignore rule.[/red]"
            )
            return 1

        ok = db.add_sender_ignore(
            sender_address=sender_address or None,
            sender_domain=sender_domain or None,
            reason=reason,
        )
        if ok:
            target = sender_address or sender_domain
            console.print(f"[green]Ignored:[/green] {target}")
            return 0
        console.print("[red]Failed to add ignore rule.[/red]")
        return 1
    except Exception as exc:
        console.print(f"[red]Failed to add ignore rule:[/red] {exc}")
        return 1
    finally:
        db.close()


def list_sender_ignores(limit: int = 200) -> int:
    """List ignore rules stored in the database."""
    load_env()
    _configure_logging()

    db = get_db_manager()
    try:
        rows = db.list_sender_ignores(limit=limit)
        if not rows:
            console.print("[dim]No ignore rules configured.[/dim]")
            return 0

        table = Table(title="Sender Ignore List", border_style="dim")
        table.add_column("ID", style="dim", justify="right")
        table.add_column("Address", style="cyan")
        table.add_column("Domain", style="magenta")
        table.add_column("Reason")
        table.add_column("Created", style="dim")

        for row in rows:
            table.add_row(
                str(row.get("id")),
                row.get("sender_address") or "",
                row.get("sender_domain") or "",
                row.get("reason") or "",
                str(row.get("created_at") or ""),
            )

        console.print(table)
        return 0
    finally:
        db.close()


def review_manual_matches(limit: int = 25, auto_resolve: bool = False) -> int:
    """Interactive workflow to resolve ambiguous email->application matches."""
    load_env()
    _configure_logging()

    console.print("\n[bold blue]Ronin Manual Review[/bold blue]\n")

    db = get_db_manager()
    try:
        emails = db.get_manual_review_emails(limit=max(1, int(limit)))
        if not emails:
            console.print("[green]No emails require manual review.[/green]")
            return 0

        applications = db.get_recent_applications_for_matching(days=180)
        matcher = GmailOutcomeTracker(db_manager=db)

        resolved = 0
        skipped = 0

        interactive = False
        try:
            interactive = sys.stdin.isatty()
        except Exception:
            interactive = False

        if not interactive:
            table = Table(title="Manual Review (Non-Interactive)", border_style="dim")
            table.add_column("Email", style="dim", justify="right")
            table.add_column("Outcome", style="magenta")
            table.add_column("From")
            table.add_column("Subject")
            table.add_column("Top App", style="cyan", justify="right")
            table.add_column("Score", style="dim", justify="right")

            pending_rows = 0
            for email in emails:
                email_id = int(email.get("id"))
                outcome = (email.get("outcome_classification") or "other").strip()
                sender = (email.get("sender_address") or "").strip()
                subject = (email.get("subject") or "").strip()

                match = matcher._match_email_to_application(
                    email, applications
                )  # noqa: SLF001

                if (
                    auto_resolve
                    and match.status == "auto_matched"
                    and match.application
                ):
                    ok = db.resolve_manual_review_email_match(
                        email_parsed_id=email_id,
                        application_id=int(match.application.get("id")),
                        match_method=str(match.method or "manual"),
                    )
                    if ok:
                        resolved += 1
                        continue

                candidates = match.candidates or []
                top_app_id = ""
                top_score = ""
                if candidates:
                    top_app_id = str(candidates[0][0].get("id") or "")
                    top_score = f"{float(candidates[0][1]):.2f}"

                pending_rows += 1
                table.add_row(
                    str(email_id),
                    outcome,
                    sender,
                    subject[:48],
                    top_app_id,
                    top_score,
                )

            if resolved:
                console.print(f"[green]Auto-resolved:[/green] {resolved}")

            if pending_rows:
                console.print(table)
                console.print(
                    "\n[dim]Run `ronin feedback review` in an interactive terminal to resolve remaining matches.[/dim]"
                )
            else:
                console.print(
                    "[green]No remaining emails require manual review.[/green]"
                )
            return 0

        for email in emails:
            email_id = int(email.get("id"))
            sender = (email.get("sender_address") or "").strip()
            received = str(email.get("date_received") or "")
            subject = (email.get("subject") or "").strip()
            outcome = (email.get("outcome_classification") or "other").strip()

            console.rule(f"Email #{email_id}")
            console.print(f"[dim]{received}[/dim]")
            console.print(f"From: [cyan]{sender or '(unknown)'}[/cyan]")
            if subject:
                console.print(f"Subject: {subject}")
            console.print(f"Outcome: [magenta]{outcome}[/magenta]\n")

            match = matcher._match_email_to_application(
                email, applications
            )  # noqa: SLF001
            candidates = match.candidates or []

            if auto_resolve and match.status == "auto_matched" and match.application:
                ok = db.resolve_manual_review_email_match(
                    email_parsed_id=email_id,
                    application_id=int(match.application.get("id")),
                    match_method=str(match.method or "manual"),
                )
                if ok:
                    console.print(
                        f"[green]Auto-resolved[/green] email #{email_id} -> application {match.application.get('id')}"
                    )
                    resolved += 1
                else:
                    console.print(f"[red]Failed[/red] to resolve email #{email_id}")
                    skipped += 1
                continue

            if not candidates:
                console.print("[yellow]No match candidates found.[/yellow]")
                skipped += 1
                continue

            table = Table(title="Top Candidates", border_style="dim")
            table.add_column("Pick", style="dim", justify="right")
            table.add_column("App ID", style="cyan", justify="right")
            table.add_column("Company")
            table.add_column("Title")
            table.add_column("Applied", style="dim")
            table.add_column("Score", style="dim", justify="right")

            for idx, (app, score) in enumerate(candidates[:3], start=1):
                table.add_row(
                    str(idx),
                    str(app.get("id")),
                    str(app.get("company_name") or ""),
                    str(app.get("job_title") or app.get("title") or ""),
                    str(app.get("date_applied") or ""),
                    f"{float(score):.2f}",
                )
            console.print(table)

            try:
                choice = Prompt.ask(
                    "Select 1-3, type an application id, (s)kip, or (q)uit",
                    default="s",
                ).strip()
            except EOFError:
                choice = "q"

            if choice.lower() in {"q", "quit"}:
                break
            if choice.lower() in {"s", "skip", ""}:
                skipped += 1
                continue

            application_id: int
            if choice.isdigit() and int(choice) in {1, 2, 3}:
                pick = int(choice) - 1
                application_id = int(candidates[pick][0].get("id"))
            elif choice.isdigit():
                application_id = int(choice)
            else:
                console.print("[yellow]Unrecognized input; skipping.[/yellow]")
                skipped += 1
                continue

            ok = db.resolve_manual_review_email_match(
                email_parsed_id=email_id,
                application_id=application_id,
            )
            if ok:
                console.print(
                    f"[green]Resolved[/green] email #{email_id} -> application {application_id}"
                )
                resolved += 1
            else:
                console.print(
                    f"[red]Failed[/red] to resolve email #{email_id} -> application {application_id}"
                )

        console.print()
        console.print(
            f"Resolved: [bold]{resolved}[/bold]  Skipped: [bold]{skipped}[/bold]"
        )
        return 0

    finally:
        db.close()
