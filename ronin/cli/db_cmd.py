"""Database maintenance CLI commands (backup, etc)."""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.table import Table

from ronin.backup import backup_database
from ronin.config import load_config, load_env
from ronin.db import get_db_manager

console = Console()


def backup_db(output_dir: Optional[str] = None, include_spool: bool = True) -> int:
    """Create a point-in-time DB backup."""
    load_env()
    config = load_config()

    result = backup_database(
        config=config,
        output_dir=output_dir,
        include_spool=include_spool,
    )

    console.print("\n[bold blue]Ronin DB Backup[/bold blue]\n")
    console.print(f"Backend: [bold]{result.backend}[/bold]")
    console.print(f"Output:  [bold]{result.output_dir}[/bold]\n")

    if result.created_files:
        console.print("Created:")
        for path in result.created_files:
            console.print(f"  [green]✓[/green] {path}")

    if result.errors:
        console.print("\nErrors:")
        for err in result.errors:
            console.print(f"  [red]✗[/red] {err}")
        return 1

    console.print("\n[green]Backup complete.[/green]")
    return 0


def migrate_db(
    only: str = "all",
    limit: int = 0,
    dry_run: bool = False,
    enable_embeddings: bool = False,
) -> int:
    """Run safe DB migrations/backfills for existing users."""
    load_env()
    config = load_config()

    console.print("\n[bold blue]Ronin DB Migrate[/bold blue]\n")
    console.print(
        f"Backend: [bold]{config.get('database', {}).get('backend', 'sqlite')}[/bold]"
    )
    console.print(f"Mode:    {'dry-run' if dry_run else 'write'}")
    console.print(f"Only:    {only}\n")

    db = get_db_manager(config=config)
    try:
        if only not in {"all", "applications", "archetypes"}:
            raise ValueError("--only must be one of: all, applications, archetypes")

        if only in {"all", "applications"}:
            stats = db.backfill_applications_from_applied_jobs(
                limit=int(limit or 0),
                dry_run=bool(dry_run),
            )

            table = Table(title="Backfill Applications", border_style="dim")
            table.add_column("Metric", style="dim")
            table.add_column("Value", justify="right")
            for key in [
                "applied_jobs",
                "applications_total",
                "missing",
                "inserted",
            ]:
                table.add_row(key.replace("_", " ").title(), str(stats.get(key, 0)))
            console.print(table)
            console.print()

        if only in {"all", "archetypes"}:
            from ronin.analyzer.archetype_classifier import ArchetypeClassifier

            analysis_cfg = config.get("analysis", {})
            classifier = ArchetypeClassifier(
                enable_embeddings=bool(enable_embeddings),
                embedding_model_name=analysis_cfg.get(
                    "embedding_model", "all-MiniLM-L6-v2"
                ),
            )

            rows = db.get_applications_missing_archetype(limit=int(limit or 0))
            processed = 0
            updated = 0
            skipped = 0

            for row in rows:
                application_id = int(row.get("id"))
                title = str(row.get("job_title") or row.get("title") or "")
                jd_text = str(
                    row.get("job_description_text") or row.get("description") or ""
                )
                if not jd_text.strip():
                    skipped += 1
                    continue

                processed += 1
                result = classifier.classify(jd_text=jd_text, job_title=title)
                primary = str(result.get("archetype_primary") or "").strip().lower()
                scores = result.get("archetype_scores") or {}
                if not isinstance(scores, dict):
                    scores = {}

                if dry_run:
                    updated += 1
                    continue

                ok = db.update_application_archetype(
                    application_id=application_id,
                    archetype_primary=primary,
                    archetype_scores=scores,
                )
                if ok:
                    updated += 1

            table = Table(title="Backfill Archetypes", border_style="dim")
            table.add_column("Metric", style="dim")
            table.add_column("Value", justify="right")
            table.add_row("Candidates", str(len(rows)))
            table.add_row("Processed", str(processed))
            table.add_row("Updated" + (" (dry-run)" if dry_run else ""), str(updated))
            table.add_row("Skipped (no text)", str(skipped))
            console.print(table)

        return 0
    except Exception as exc:
        console.print(f"[red]Migration failed:[/red] {exc}")
        return 1
    finally:
        try:
            db.close()
        except Exception:
            pass
