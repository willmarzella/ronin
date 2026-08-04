"""Extended `ronin apply` subcommands for queue, batching, and drift ops."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from ronin.application_queue import ApplicationQueueService
from ronin.analyzer.archetype_classifier import ArchetypeClassifier, is_protected_company
from ronin.applier import SeekApplier
from ronin.config import load_config, load_env
from ronin.contact_intel import (
    RecruiterIntelService,
    build_linkedin_lookup_url,
    build_linkedin_dm_message,
    build_outreach_email,
    write_linkedin_dm_draft,
)
from ronin.db import get_db_manager
from ronin.feedback.drift import DriftEngine, run_weekly_drift_jobs


console = Console()
ARCHETYPE_PROFILES = {"builder", "fixer", "operator", "translator"}


def _redact_dsn(dsn: str) -> str:
    """Remove secrets from a Postgres DSN for display."""
    raw = (dsn or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        scheme = parsed.scheme or "postgres"
        user = parsed.username or ""
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        dbname = (parsed.path or "").lstrip("/")
        auth = f"{user}@" if user else ""
        return f"{scheme}://{auth}{host}{port}/{dbname}".rstrip("/")
    except Exception:
        return "postgres://<redacted>"


def show_queue(limit: int = 200) -> int:
    """Show queued applications grouped by archetype."""
    load_env()
    config = load_config()
    threshold = float(config.get("application", {}).get("queue_threshold", 0.15))
    db = get_db_manager(config=config)
    try:
        summary = db.get_queue_summary()
        table = Table(title="Application Queue", border_style="dim")
        table.add_column("Archetype", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Avg archetype score", justify="right")

        display_order = ["builder", "fixer", "operator", "translator", "market_intel"]
        for key in display_order:
            values = summary.get(key)
            if not values:
                continue
            label = "Market Intel" if key == "market_intel" else key.capitalize()
            table.add_row(
                label,
                str(int(values.get("count", 0))),
                f"{float(values.get('avg_score', 0.0)):.2f}",
            )

        if table.row_count == 0:
            console.print("[yellow]No queued roles found.[/yellow]")
            return 0

        console.print(table)

        # Optional detail table for quick inspection.
        variants = {row.get("archetype"): row for row in db.list_resume_variants()}
        jobs = db.get_queued_jobs(limit=limit)
        if jobs:
            detail = Table(
                title=f"Top Queued Roles (threshold={threshold:.2f})",
                border_style="dim",
            )
            detail.add_column("ID", style="dim", justify="right")
            detail.add_column("Review", style="yellow")
            detail.add_column("Arch", style="magenta")
            detail.add_column("p", justify="right")
            detail.add_column("align", justify="right")
            detail.add_column("fit", justify="right")
            detail.add_column("Score", justify="right")
            detail.add_column("Title", style="cyan")
            detail.add_column("Company", style="green")

            for row in jobs[: min(len(jobs), 15)]:
                archetype = (row.get("archetype_primary") or "unknown").strip().lower()
                scores = db._safe_json_load(row.get("archetype_scores"), {})
                primary_score = 0.0
                if isinstance(scores, dict) and archetype in scores:
                    try:
                        primary_score = float(scores[archetype])
                    except Exception:
                        primary_score = 0.0
                if primary_score <= 0:
                    try:
                        primary_score = float(row.get("score", 0) or 0) / 100.0
                    except Exception:
                        primary_score = 0.0

                alignment = 0.5
                variant = variants.get(archetype)
                if variant:
                    try:
                        alignment = float(variant.get("alignment_score") or 0.5)
                    except Exception:
                        alignment = 0.5
                combined = primary_score * alignment

                detail.add_row(
                    str(row.get("id")),
                    "yes" if int(row.get("selection_needs_review") or 0) else "",
                    archetype.capitalize(),
                    f"{primary_score:.2f}",
                    f"{alignment:.2f}",
                    f"{combined:.2f}",
                    str(row.get("score", 0)),
                    row.get("title", "")[:38],
                    row.get("company_name", "")[:24],
                )
            console.print()
            console.print(detail)

        return 0
    finally:
        db.close()


def review_selections(limit: int = 25) -> int:
    """Interactively review and override close-call archetype selections."""
    from rich.prompt import Prompt

    load_env()
    config = load_config()
    threshold = float(config.get("application", {}).get("queue_threshold", 0.15))

    # Best-effort: flush spool before review.
    try:
        from ronin.spool_sync import sync_spool_to_remote

        sync_spool_to_remote(config=config, dry_run=False)
    except Exception:
        pass

    db = get_db_manager(config=config)
    try:
        variants = {row.get("archetype"): row for row in db.list_resume_variants()}
        jobs = db.get_close_call_jobs(limit=max(1, int(limit)))
        if not jobs:
            console.print("[green]No close-call selections to review.[/green]")
            return 0

        table = Table(title="Close-Call Selections", border_style="dim")
        table.add_column("Pick", style="dim", justify="right")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Current", style="magenta")
        table.add_column("Top2", style="dim")
        table.add_column("fit", justify="right")
        table.add_column("Title", style="cyan")
        table.add_column("Company", style="green")

        scored: List[Dict] = []
        for idx, row in enumerate(jobs, start=1):
            scores = db._safe_json_load(row.get("archetype_scores"), {})
            if not isinstance(scores, dict) or not scores:
                scores = {}
            ranked = sorted(
                scores.items(), key=lambda item: float(item[1]), reverse=True
            )
            current = (row.get("archetype_primary") or "unknown").strip().lower()
            primary_score = float(scores.get(current, 0.0) or 0.0)
            alignment = float(
                (variants.get(current) or {}).get("alignment_score") or 0.5
            )
            combined = primary_score * alignment
            top2 = ", ".join([f"{name}:{float(val):.2f}" for name, val in ranked[:2]])
            scored.append(
                {
                    "row": row,
                    "ranked": ranked,
                    "current": current,
                    "combined": combined,
                }
            )
            table.add_row(
                str(idx),
                str(row.get("id")),
                current.capitalize(),
                top2 or "(no scores)",
                f"{combined:.2f}",
                str(row.get("title") or "")[:38],
                str(row.get("company_name") or "")[:24],
            )

        console.print(table)
        console.print(
            "\n[dim]Override sets archetype_primary/resume_archetype/resume_profile, clears selection_needs_review, "
            "and re-evaluates below_threshold using the queue threshold.[/dim]"
        )

        while True:
            choice = Prompt.ask("Pick 1-{} or (q)uit".format(len(scored)), default="q")
            if choice.strip().lower() in {"q", "quit"}:
                break
            if not choice.isdigit():
                continue
            pick = int(choice)
            if pick < 1 or pick > len(scored):
                continue

            selected = scored[pick - 1]
            row = selected["row"]
            current = selected["current"]

            new_arch = (
                Prompt.ask(
                    "Select archetype",
                    choices=["builder", "fixer", "operator", "translator"],
                    default=(
                        current
                        if current in {"builder", "fixer", "operator", "translator"}
                        else "builder"
                    ),
                )
                .strip()
                .lower()
            )

            scores = db._safe_json_load(row.get("archetype_scores"), {})
            primary_score = 0.0
            if isinstance(scores, dict):
                primary_score = float(scores.get(new_arch, 0.0) or 0.0)
            alignment = float(
                (variants.get(new_arch) or {}).get("alignment_score") or 0.5
            )
            combined = primary_score * alignment
            intel_only = 1 if combined < threshold else 0

            # Bespoke-channel companies and the current employer never re-queue.
            if is_protected_company(str(row.get("company_name") or "")):
                intel_only = 1

            ok = db.update_record(
                int(row.get("id")),
                {
                    "archetype_primary": new_arch,
                    "resume_archetype": new_arch,
                    "resume_profile": new_arch,
                    "selection_needs_review": 0,
                    # below_threshold: analytical demotion based on queue
                    # threshold. Not the same as market_intelligence_only,
                    # which reflects the Seek apply-button structure.
                    "below_threshold": intel_only,
                },
            )
            if ok:
                console.print(
                    f"[green]Updated[/green] job {row.get('id')} -> {new_arch} "
                    f"(p={primary_score:.2f} align={alignment:.2f} fit={combined:.2f})"
                )
            else:
                console.print(
                    f"[red]Failed[/red] to update job {row.get('id')} (db update returned false)"
                )

        return 0

    finally:
        db.close()


def show_ghosts(limit: int = 50) -> int:
    """List ghosted applications (no signal after 30+ days)."""
    from datetime import date

    load_env()
    config = load_config()
    db = get_db_manager(config=config)
    try:
        rows = db.get_ghosted_applications(limit=max(1, int(limit)))
        if not rows:
            console.print("[green]No ghosted applications found.[/green]")
            return 0

        table = Table(title="Ghosted Applications", border_style="dim")
        table.add_column("Applied", style="dim")
        table.add_column("Days", justify="right", style="dim")
        table.add_column("Company", style="green")
        table.add_column("Title", style="cyan")
        table.add_column("Outcome", style="magenta")
        table.add_column("Commit", style="dim")

        today = date.today()
        for row in rows:
            applied = str(row.get("date_applied") or "")
            days = ""
            try:
                if applied:
                    days = str((today - date.fromisoformat(applied)).days)
            except Exception:
                days = ""
            table.add_row(
                applied,
                days,
                str(row.get("company_name") or "")[:28],
                str(row.get("job_title") or row.get("title") or "")[:46],
                str(row.get("outcome_stage") or "applied"),
                str(row.get("resume_commit_hash") or "")[:12],
            )
        console.print(table)
        return 0
    finally:
        db.close()


def show_corpus(limit: int = 30) -> int:
    """Run basic corpus analysis (normalized job title counts)."""
    load_env()
    config = load_config()
    db = get_db_manager(config=config)
    try:
        rows = db.get_applications(limit=0)
        source = "applications"
        if not rows:
            # Early-stage users may have jobs but no application records yet.
            rows = db.get_jobs_corpus(limit=0)
            source = "jobs"
        if not rows:
            console.print("[yellow]No jobs/applications found in corpus.[/yellow]")
            return 0

        def normalize(title: str) -> str:
            text = (title or "").strip().lower()
            if not text:
                return "unknown"
            text = re.sub(r"\s+", " ", text)
            for prefix in [
                "senior ",
                "lead ",
                "junior ",
                "principal ",
                "staff ",
                "head of ",
                "sr. ",
                "sr ",
            ]:
                if text.startswith(prefix):
                    text = text[len(prefix) :].strip()
            text = re.sub(r"\b(ii|iii|iv|v|1|2|3)\b$", "", text).strip()
            text = re.sub(r"[^a-z0-9\s\+\-]", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text or "unknown"

        counter: Counter = Counter()
        for row in rows:
            title = row.get("job_title") or row.get("title") or ""
            counter.update([normalize(str(title))])

        total = sum(counter.values())
        table = Table(
            title=f"Corpus: Top Normalized Titles ({source})",
            border_style="dim",
        )
        table.add_column("Title", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Share", justify="right", style="dim")

        for title, count in counter.most_common(max(1, int(limit))):
            share = (count / total) if total else 0.0
            table.add_row(title[:52], str(count), f"{share * 100:.1f}%")

        console.print(table)
        noun = "applications" if source == "applications" else "jobs"
        console.print(
            f"\n[dim]Total {noun}: {total} | Unique titles: {len(counter)}[/dim]"
        )

        db_location = ""
        try:
            if hasattr(db, "db_path"):
                db_location = str(getattr(db, "db_path"))
            elif hasattr(db, "dsn"):
                db_location = _redact_dsn(str(getattr(db, "dsn")))
        except Exception:
            db_location = ""
        if db_location:
            console.print(f"[dim]DB: {db_location}[/dim]")
        return 0
    finally:
        db.close()


def sample_labels(count: int = 50, output_path: str = "labels_sample.jsonl") -> int:
    """Export a sample of JDs for manual labeling."""
    load_env()
    config = load_config()
    db = get_db_manager(config=config)
    try:
        jobs = db.get_jobs_for_labeling(limit=0)
        if not jobs:
            console.print("[yellow]No job descriptions available to sample.[/yellow]")
            return 0

        classifier = ArchetypeClassifier(
            enable_embeddings=bool(
                config.get("analysis", {}).get("enable_embeddings", True)
            ),
            embedding_model_name=config.get("analysis", {}).get(
                "embedding_model", "all-MiniLM-L6-v2"
            ),
        )

        def normalize(title: str) -> str:
            text = (title or "").strip().lower()
            if not text:
                return "unknown"
            text = re.sub(r"\s+", " ", text)
            for prefix in [
                "senior ",
                "lead ",
                "junior ",
                "principal ",
                "staff ",
                "head of ",
                "sr. ",
                "sr ",
            ]:
                if text.startswith(prefix):
                    text = text[len(prefix) :].strip()
            text = re.sub(r"\b(ii|iii|iv|v|1|2|3)\b$", "", text).strip()
            text = re.sub(r"[^a-z0-9\s\+\-]", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text or "unknown"

        scored: List[Dict] = []
        for row in jobs:
            title = str(row.get("title") or "")
            jd_text = str(row.get("description") or "")
            scores = classifier.score_jd(jd_text=jd_text, job_title=title)
            predicted = max(scores, key=scores.get) if scores else "builder"
            sorted_scores = sorted(
                scores.items(), key=lambda item: float(item[1]), reverse=True
            )
            top_score = float(sorted_scores[0][1]) if sorted_scores else 0.0
            second_score = float(sorted_scores[1][1]) if len(sorted_scores) > 1 else 0.0
            margin = top_score - second_score

            enriched = dict(row)
            enriched["_predicted"] = predicted
            enriched["_scores"] = scores
            enriched["_margin"] = margin
            enriched["_needs_review"] = int(margin < 0.10)
            enriched["_norm_title"] = normalize(title)
            enriched["_company"] = (
                str(row.get("company_name") or "").strip().lower() or "unknown"
            )
            scored.append(enriched)

        # Priority: rare archetypes + close calls.
        priority_rows: List[Dict] = []
        for row in scored:
            if row.get("_predicted") in {"fixer", "translator"}:
                priority_rows.append(row)
        for row in scored:
            if int(row.get("_needs_review") or 0):
                priority_rows.append(row)

        seen: set[str] = set()
        priority_unique: List[Dict] = []
        for row in priority_rows:
            key = str(row.get("job_id") or row.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            priority_unique.append(row)

        # Greedy fill: prefer title/company diversity.
        def pick_diverse(
            candidates: List[Dict], limit_n: int, selected: List[Dict]
        ) -> List[Dict]:
            title_counts: Dict[str, int] = {}
            company_counts: Dict[str, int] = {}
            for s in selected:
                t = str(s.get("_norm_title") or "unknown")
                c = str(s.get("_company") or "unknown")
                title_counts[t] = title_counts.get(t, 0) + 1
                company_counts[c] = company_counts.get(c, 0) + 1

            remaining = list(candidates)
            chosen: List[Dict] = []
            while remaining and len(chosen) < max(0, int(limit_n)):

                def cost(r: Dict) -> tuple:
                    t = str(r.get("_norm_title") or "unknown")
                    c = str(r.get("_company") or "unknown")
                    return (
                        title_counts.get(t, 0) * 2 + company_counts.get(c, 0),
                        float(r.get("_margin") or 0.0),
                        str(r.get("_norm_title") or ""),
                        str(r.get("_company") or ""),
                        str(r.get("job_id") or r.get("id") or ""),
                    )

                remaining.sort(key=cost)
                pick = remaining.pop(0)
                chosen.append(pick)
                t = str(pick.get("_norm_title") or "unknown")
                c = str(pick.get("_company") or "unknown")
                title_counts[t] = title_counts.get(t, 0) + 1
                company_counts[c] = company_counts.get(c, 0) + 1
            return chosen

        target = min(max(1, int(count)), len(scored))
        selected: List[Dict] = []
        selected.extend(pick_diverse(priority_unique, limit_n=target, selected=[]))
        if len(selected) < target:
            selected_keys = {
                str(r.get("job_id") or r.get("id") or "") for r in selected
            }
            remaining = [
                r
                for r in scored
                if str(r.get("job_id") or r.get("id") or "") not in selected_keys
            ]
            selected.extend(
                pick_diverse(
                    remaining,
                    limit_n=(target - len(selected)),
                    selected=selected,
                )
            )

        out_path = Path(output_path).expanduser()
        if not out_path.is_absolute():
            out_path = (Path.cwd() / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as handle:
            for row in selected[:target]:
                payload = {
                    "db_id": row.get("id"),
                    "job_id": row.get("job_id"),
                    "title": row.get("title"),
                    "company_name": row.get("company_name"),
                    "description": row.get("description"),
                    "suggested_archetype": row.get("_predicted"),
                    "suggested_scores": row.get("_scores"),
                    "suggested_margin": float(row.get("_margin") or 0.0),
                    "suggested_needs_review": int(row.get("_needs_review") or 0),
                    "manual_label": "",
                    "notes": "",
                }
                handle.write(json.dumps(payload) + "\n")

        console.print(f"[green]Wrote sample labels file:[/green] {out_path}")
        console.print(
            "[dim]Fill manual_label with builder/fixer/operator/translator, then run: ronin apply validate-labels <file>[/dim]"
        )
        return 0
    finally:
        db.close()


def validate_labels(labels_path: str) -> int:
    """Validate archetype classifier agreement vs a manual-labeled JSONL file."""
    load_env()
    config = load_config()

    path = Path(labels_path).expanduser()
    if not path.exists():
        console.print(f"[red]Labels file not found:[/red] {path}")
        return 1

    classifier = ArchetypeClassifier(
        enable_embeddings=bool(
            config.get("analysis", {}).get("enable_embeddings", True)
        ),
        embedding_model_name=config.get("analysis", {}).get(
            "embedding_model", "all-MiniLM-L6-v2"
        ),
    )

    db = get_db_manager(config=config)

    total = 0
    correct = 0
    disagreements: List[Dict] = []

    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue

                manual = (
                    item.get("manual_label")
                    or item.get("label")
                    or item.get("manual")
                    or ""
                )
                manual = str(manual).strip().lower()
                if manual not in {"builder", "fixer", "operator", "translator"}:
                    continue

                job_id = str(item.get("job_id") or "").strip()
                title = str(item.get("title") or "").strip()
                jd_text = (
                    item.get("jd_text")
                    or item.get("description")
                    or item.get("job_description_text")
                    or ""
                )
                jd_text = str(jd_text or "")

                if not jd_text.strip() and job_id:
                    job = db.get_job_by_job_id(job_id)
                    if job:
                        title = title or str(job.get("title") or "").strip()
                        jd_text = str(job.get("description") or "")

                if not jd_text.strip():
                    continue

                total += 1
                scores = classifier.score_jd(jd_text=jd_text, job_title=title)
                predicted = max(scores, key=scores.get) if scores else "builder"
                if predicted == manual:
                    correct += 1
                else:
                    disagreements.append(
                        {
                            "job_id": job_id,
                            "title": title,
                            "predicted": predicted,
                            "predicted_score": float(scores.get(predicted, 0.0)),
                            "manual": manual,
                            "manual_score": float(scores.get(manual, 0.0)),
                            "snippet": jd_text[:220],
                        }
                    )
    finally:
        try:
            db.close()
        except Exception:
            pass

    if total == 0:
        console.print(
            "[yellow]No labeled rows found.[/yellow] Expected JSONL with description/jd_text + manual_label."
        )
        return 1

    agreement = correct / total
    console.print(
        f"\n[bold]Agreement:[/bold] {agreement * 100:.1f}% ({correct}/{total})\n"
    )

    if disagreements:
        table = Table(title="Disagreements (sample)", border_style="dim")
        table.add_column("Job", style="dim")
        table.add_column("Pred", style="magenta")
        table.add_column("p", justify="right", style="dim")
        table.add_column("Manual", style="cyan")
        table.add_column("m", justify="right", style="dim")
        table.add_column("Snippet")
        for row in disagreements[:10]:
            table.add_row(
                str(row.get("job_id") or "")[-6:],
                row["predicted"],
                f"{row['predicted_score']:.2f}",
                row["manual"],
                f"{row['manual_score']:.2f}",
                row["snippet"].replace("\n", " ")[:72],
            )
        console.print(table)

        out_path = path.with_suffix(path.suffix + ".disagreements.jsonl")
        with open(out_path, "w", encoding="utf-8") as out:
            for row in disagreements:
                out.write(json.dumps(row) + "\n")
        console.print(f"\n[dim]Wrote full disagreements to {out_path}[/dim]")

    if agreement < 0.75:
        console.print(
            "\n[yellow]Below 75% threshold. Expand seed patterns and re-run validation.[/yellow]"
        )
        return 1

    return 0


def sync_queue(limit: int = 0) -> int:
    """Recompute variant alignment + queue gating thresholds."""
    load_env()
    config = load_config()

    # If we're using a remote Postgres DB, flush any locally spooled rows first.
    spool_stats = None
    try:
        from ronin.spool_sync import sync_spool_to_remote

        spool_stats = sync_spool_to_remote(config=config, dry_run=False)
    except Exception as exc:
        logger.debug(f"Spool sync unavailable: {exc}")

    service = ApplicationQueueService(config=config)
    try:
        if spool_stats and not spool_stats.get("skipped"):
            table = Table(title="Spool Flush", show_header=False, border_style="dim")
            table.add_column("Metric", style="dim")
            table.add_column("Value", style="bold")
            if spool_stats.get("error"):
                table.add_row("Result", f"[red]{spool_stats.get('error')}[/red]")
            else:
                table.add_row("Jobs in spool", str(spool_stats.get("spool_jobs", 0)))
                table.add_row(
                    "Applications in spool",
                    str(spool_stats.get("spool_applications", 0)),
                )
                table.add_row(
                    "Variants in spool",
                    str(spool_stats.get("spool_variants", 0)),
                )
                table.add_row(
                    "Jobs inserted",
                    str(spool_stats.get("jobs_inserted", 0)),
                )
                table.add_row(
                    "Job statuses updated",
                    str(spool_stats.get("jobs_status_updated", 0)),
                )
                table.add_row(
                    "Applications inserted",
                    str(spool_stats.get("applications_inserted", 0)),
                )
                table.add_row(
                    "Variants upserted",
                    str(spool_stats.get("variants_upserted", 0)),
                )
            console.print(table)
            console.print()

        stats = service.recompute_queue(limit=limit)
        table = Table(title="Queue Sync", show_header=False, border_style="dim")
        table.add_column("Metric", style="dim")
        table.add_column("Value", style="bold")
        table.add_row("Evaluated", str(stats.get("evaluated", 0)))
        table.add_row("Updated", str(stats.get("updated", 0)))
        table.add_row("Market-intel only", str(stats.get("market_intelligence", 0)))
        table.add_row("Manual review", str(stats.get("manual_review", 0)))
        console.print(table)
        return 0
    finally:
        service.close()


def batch_apply(
    archetype: str,
    limit: int = 0,
    yes: bool = False,
    auto_profile: bool = False,
    dry_run_profile: bool = False,
) -> int:
    """Apply to all queued jobs for a selected archetype."""
    load_env()
    config = load_config()
    db = get_db_manager(config=config)

    queue_service = ApplicationQueueService(config=config, db_manager=db)
    variants = queue_service.refresh_resume_variants()
    selected_variant = variants.get(archetype) or db.get_resume_variant(archetype)
    resume_commit_hash = (
        selected_variant.get("current_commit_hash") if selected_variant else None
    )
    seek_profile_override = archetype

    jobs = db.get_queued_jobs(archetype=archetype, limit=limit)
    if not jobs:
        console.print(f"[yellow]No queued {archetype} roles found.[/yellow]")
        return 0

    preview = Table(title=f"Queued {archetype.capitalize()} Roles", border_style="dim")
    preview.add_column("Title", style="cyan")
    preview.add_column("Company", style="green")
    preview.add_column("Score", justify="right")
    for row in jobs:
        preview.add_row(
            row.get("title", "")[:55],
            row.get("company_name", "")[:30],
            str(row.get("score", 0)),
        )
    console.print(preview)

    seek_auto_enabled = bool(
        (config.get("seek_profile", {}) or {})
        .get("automation", {})
        .get("enabled", False)
    )
    should_auto_profile = bool(auto_profile or seek_auto_enabled)

    if should_auto_profile:
        console.print(
            "\n[bold]Seek profile automation:[/bold] "
            f"Ronin will switch your Seek profile to [cyan]{archetype}[/cyan] before applying."
        )
        console.print(
            "[dim]If this is your first run, a browser window will open for login. "
            "Keep it open until Ronin finishes the update.[/dim]"
        )
    else:
        console.print(
            "\n[bold]Seek profile state check:[/bold] "
            f"set your Seek profile to [cyan]{archetype}[/cyan] before continuing."
        )

    if not yes and not Confirm.ask("Continue with this batch?", default=False):
        console.print("[yellow]Batch cancelled.[/yellow]")
        return 0

    if should_auto_profile:
        try:
            from ronin.seek.profile_updater import (
                SeekProfileUpdater,
                load_template_from_config,
            )

            updater = SeekProfileUpdater(config=config)
            template = load_template_from_config(config, archetype)
            updater.apply_archetype(
                archetype=archetype,
                template=template,
                dry_run=bool(dry_run_profile),
                allow_manual_login=True,
            )
            if dry_run_profile:
                console.print(
                    "[yellow]Profile automation dry-run complete (no changes saved).[/yellow]"
                )
            else:
                try:
                    from ronin.seek.profile_drift import store_profile_state

                    store_profile_state(
                        db,
                        archetype,
                        source="apply.batch",
                        note="batch auto-profile before apply",
                    )
                except Exception:
                    pass
                console.print("[green]Seek profile updated.[/green]")
        except Exception as exc:
            console.print(
                f"[red]Seek profile automation failed.[/red] {str(exc)[:220]}"
            )
            console.print(
                "[dim]Tip: run `ronin profile debug` to discover selectors and configure "
                "seek_profile.automation.selectors in ~/.ronin/config.yaml.[/dim]"
            )
            return 1

    batch_id = db.create_application_batch(archetype=archetype, profile_state=archetype)
    if batch_id is None:
        console.print("[red]Could not create application batch record.[/red]")
        return 1

    results = _apply_records(
        jobs=jobs,
        db=db,
        profile_state=archetype,
        batch_id=batch_id,
        resume_variant_sent=archetype,
        resume_commit_hash=resume_commit_hash,
        resume_profile_override=seek_profile_override,
    )
    db.finalize_application_batch(
        batch_id=batch_id, application_count=results["applied"]
    )

    table = Table(title="Batch Result", show_header=False, border_style="dim")
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold")
    table.add_row("Batch ID", str(batch_id))
    table.add_row("Applied", f"[green]{results['applied']}[/green]")
    table.add_row("Stale", f"[yellow]{results['stale']}[/yellow]")
    table.add_row("Failed", f"[red]{results['failed']}[/red]")
    table.add_row("Total", str(len(jobs)))
    console.print()
    console.print(table)
    console.print(
        f"\n[green]Applied to {results['applied']} {archetype} roles.[/green] "
        "Wait 3-5 days before switching profile to next archetype."
    )

    db.close()
    return 0 if results["failed"] == 0 else 1


def show_apply_status() -> int:
    """Display funnel metrics grouped by month, archetype, and versions."""
    load_env()
    db = get_db_manager()
    metrics = db.get_funnel_metrics()

    overview = metrics.get("overview", {})
    table = Table(title="Funnel Overview", show_header=False, border_style="dim")
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold")

    total = int(overview.get("total_applied") or 0)
    responses = int(overview.get("any_response") or 0)
    viewed = int(overview.get("viewed") or 0)
    interviews = int(overview.get("interviews") or 0)
    rejected = int(overview.get("rejected") or 0)
    ghost = int(overview.get("ghost") or 0)

    table.add_row("Total applications", str(total))
    table.add_row("Any response", str(responses))
    table.add_row("Viewed", str(viewed))
    table.add_row("Interviews", str(interviews))
    table.add_row("Rejected", str(rejected))
    table.add_row("Ghosted", str(ghost))
    if total:
        table.add_row("Response rate", f"{(responses / total) * 100:.1f}%")
        table.add_row("Interview rate", f"{(interviews / total) * 100:.1f}%")
        table.add_row("Rejection rate", f"{(rejected / total) * 100:.1f}%")
        table.add_row("Ghost rate", f"{(ghost / total) * 100:.1f}%")

    console.print(table)

    by_month = metrics.get("by_month", [])
    if by_month:
        month_table = Table(title="Monthly", border_style="dim")
        month_table.add_column("Month", style="cyan")
        month_table.add_column("Applied", justify="right")
        month_table.add_column("View rate", justify="right")
        month_table.add_column("Interview rate", justify="right")
        for row in by_month[:12]:
            month_table.add_row(
                row.get("month") or "unknown",
                str(row.get("applied", 0)),
                f"{row.get('view_rate', 0)}%",
                f"{row.get('interview_rate', 0)}%",
            )
        console.print()
        console.print(month_table)

    by_arch = metrics.get("by_archetype", [])
    if by_arch:
        arch_table = Table(title="By Archetype", border_style="dim")
        arch_table.add_column("Archetype", style="magenta")
        arch_table.add_column("Applied", justify="right")
        arch_table.add_column("Interview rate", justify="right")
        for row in by_arch:
            arch_table.add_row(
                (row.get("archetype_primary") or "unknown").capitalize(),
                str(row.get("applied", 0)),
                f"{row.get('interview_rate', 0)}%",
            )
        console.print()
        console.print(arch_table)

    db.close()
    return 0


def show_versions(min_apps: int = 1) -> int:
    """Show resume performance by commit hash version."""
    load_env()
    db = get_db_manager()
    rows = db.get_funnel_metrics().get("by_version", [])
    filtered = [row for row in rows if int(row.get("applications", 0)) >= min_apps]

    if not filtered:
        console.print("[yellow]No resume version data available yet.[/yellow]")
        return 0

    table = Table(title="Resume Version Performance", border_style="dim")
    table.add_column("Archetype", style="magenta")
    table.add_column("Commit", style="cyan")
    table.add_column("Apps", justify="right")
    table.add_column("View", justify="right")
    table.add_column("Interview", justify="right")
    table.add_column("Reject", justify="right")

    for row in filtered:
        table.add_row(
            (row.get("archetype") or "unknown").capitalize(),
            (row.get("version") or "unknown")[:12],
            str(row.get("applications", 0)),
            f"{row.get('view_rate', 0)}%",
            f"{row.get('interview_rate', 0)}%",
            f"{row.get('rejection_rate', 0)}%",
        )
    console.print(table)
    db.close()
    return 0


def show_drift(run_checks: bool = False) -> int:
    """Show current drift metrics and optionally run weekly drift checks now."""
    load_env()
    db = get_db_manager()

    if run_checks:
        run_weekly_drift_jobs(db_manager=db)

    engine = DriftEngine(db_manager=db)
    try:
        table = Table(title="Drift Metrics", border_style="dim")
        table.add_column("Archetype", style="magenta")
        table.add_column("Window", style="cyan")
        table.add_column("JD count", justify="right")
        table.add_column("Shift", justify="right")

        for archetype in ["builder", "fixer", "operator", "translator"]:
            row = db.get_most_recent_centroid(archetype)
            if not row:
                continue
            table.add_row(
                archetype.capitalize(),
                f"{row.get('window_start')} → {row.get('window_end')}",
                str(row.get("jd_count", 0)),
                f"{float(row.get('shift_from_previous') or 0.0):.4f}",
            )

        if table.row_count:
            console.print(table)
        else:
            console.print("[yellow]No centroid data available yet.[/yellow]")

        alerts = db.get_unacknowledged_alerts()
        if alerts:
            alert_table = Table(title="Active Alerts", border_style="dim")
            alert_table.add_column("ID", style="dim")
            alert_table.add_column("Archetype", style="magenta")
            alert_table.add_column("Type", style="cyan")
            alert_table.add_column("Metric", justify="right")
            for row in alerts[:20]:
                alert_table.add_row(
                    str(row.get("id")),
                    (row.get("archetype") or "unknown").capitalize(),
                    row.get("alert_type") or "unknown",
                    f"{float(row.get('metric_value') or 0.0):.4f}",
                )
            console.print()
            console.print(alert_table)
        return 0
    finally:
        engine.close()
        db.close()


def show_alerts() -> int:
    """Show all unacknowledged drift alerts with details snippets."""
    load_env()
    db = get_db_manager()
    rows = db.get_unacknowledged_alerts()
    if not rows:
        console.print("[green]No active alerts.[/green]")
        return 0

    table = Table(title="Unacknowledged Alerts", border_style="dim")
    table.add_column("ID", style="dim")
    table.add_column("Archetype", style="magenta")
    table.add_column("Type", style="cyan")
    table.add_column("Metric", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Created", style="dim")
    for row in rows:
        table.add_row(
            str(row.get("id")),
            (row.get("archetype") or "unknown").capitalize(),
            row.get("alert_type") or "unknown",
            f"{float(row.get('metric_value') or 0.0):.4f}",
            f"{float(row.get('threshold_value') or 0.0):.4f}",
            str(row.get("created_at") or ""),
        )
    console.print(table)
    db.close()
    return 0


def _looks_like_staffing_agency(name: str) -> bool:
    text = str(name or "").strip().lower()
    if not text:
        return False
    markers = ["recruit", "staff", "talent", "agency", "search", "labour"]
    return any(token in text for token in markers)


def _is_plausible_person_name(name: str) -> bool:
    parts = [p for p in str(name or "").strip().split() if p]
    if len(parts) < 2 or len(parts) > 3:
        return False
    stop = {
        "and",
        "you",
        "me",
        "on",
        "or",
        "the",
        "for",
        "to",
        "of",
        "in",
        "with",
        "our",
        "your",
    }
    if any(p.lower() in stop for p in parts):
        return False
    return all(p[:1].isupper() and len(p) >= 2 for p in parts)


def manage_contacts(
    limit: int = 50,
    source: str = "",
    refresh: bool = False,
    refresh_limit: int = 150,
    send_email: bool = False,
    dry_run_email: bool = False,
    yes: bool = False,
    cta_phone: str = "",
    open_linkedin: bool = False,
    open_linkedin_limit: int = 5,
    write_linkedin_drafts: bool = True,
    seed_recruiter_email: str = "",
    seed_recruiter_name: str = "",
    seed_recruiter_company: str = "",
) -> int:
    """Run recruiter contact extraction and show/send ranked outreach targets."""
    load_env()
    config = load_config()
    db = get_db_manager(config=config)
    try:
        intel = RecruiterIntelService(db_manager=db, config=config)

        seed_email = str(seed_recruiter_email or "").strip().lower()
        if seed_email:
            if "@" not in seed_email:
                console.print(
                    "[red]Invalid --seed-recruiter-email value (must contain @).[/red]"
                )
                return 1
            seed_domain = seed_email.split("@", 1)[1]
            seed_company = str(seed_recruiter_company or "").strip()
            if not seed_company:
                seed_company = seed_domain.split(".", 1)[0].upper()
            recruiter_id = db.upsert_recruiter_contact(
                full_name=str(seed_recruiter_name or "").strip(),
                email=seed_email,
                phone="",
                linkedin_url="",
                company_name=seed_company,
                domain=seed_domain,
                source="manual_seed",
                confidence=0.95,
                notes="seeded via ronin apply contacts",
            )
            if recruiter_id:
                console.print(
                    "[green]Seeded recruiter[/green] "
                    f"id={recruiter_id} email={seed_email} company={seed_company}"
                )
            else:
                console.print(
                    "[red]Failed to seed recruiter contact.[/red] "
                    "Check DB logs for details."
                )
                return 1

        if refresh:
            refresh_stats = intel.backfill_recent_jobs(
                limit=max(1, int(refresh_limit)),
                source=str(source or "").strip().lower(),
                only_missing=True,
            )
            console.print(
                "[dim]Contact refresh:"
                f" jobs={refresh_stats.get('jobs_seen', 0)},"
                f" jobs_with_contacts={refresh_stats.get('jobs_with_contacts', 0)},"
                f" links={refresh_stats.get('links_created', 0)},"
                f" llm_jobs={refresh_stats.get('llm_jobs_used', 0)}"
                "[/dim]"
            )

        rows = db.get_recruiter_outreach_candidates(
            limit=max(1, int(limit)),
            source=str(source or "").strip().lower(),
        )
        if not rows:
            console.print("[yellow]No recruiter outreach candidates found.[/yellow]")
            console.print(
                "[dim]Try: ronin apply contacts --refresh --refresh-limit 300[/dim]"
            )
            return 0

        table = Table(
            title="Recruiter Outreach Queue (Agency-first, then direct)",
            border_style="dim",
        )
        table.add_column("Stage", style="magenta")
        table.add_column("Contact", style="cyan")
        table.add_column("Primary Action", style="green")
        table.add_column("LinkedIn Lookup", style="dim")
        table.add_column("Job", style="white")
        table.add_column("Company", style="yellow")
        table.add_column("Score", justify="right")
        table.add_column("Last Outreach", style="dim")

        email_targets: List[Dict] = []
        linkedin_targets: List[Dict] = []
        displayed = 0
        for row in rows:
            recruiter_company = str(row.get("recruiter_company_name") or "")
            company_name = str(row.get("company_name") or "")
            agency_stage = bool(
                row.get("job_company_is_agency")
            ) or _looks_like_staffing_agency(
                recruiter_company or company_name
            )
            stage_label = "agency" if agency_stage else "direct"

            full_name = str(row.get("full_name") or "").strip()
            explicit_email = str(row.get("email") or "").strip()
            inferred_email = str(row.get("inferred_email") or "").strip()
            linkedin_url = str(row.get("linkedin_url") or "").strip()
            title = str(row.get("title") or "").strip()

            # Skip low-signal historical artifacts (no contact channel + non-person name).
            if (
                not explicit_email
                and not inferred_email
                and not linkedin_url
                and not _is_plausible_person_name(full_name)
            ):
                continue

            primary_action = "LinkedIn search"
            linkedin_lookup = linkedin_url or build_linkedin_lookup_url(
                name=full_name,
                company=company_name,
                title=title,
            )
            if explicit_email:
                primary_action = f"Email: {explicit_email}"
            elif inferred_email:
                primary_action = f"Email (inferred) + LinkedIn DM: {inferred_email}"
            elif linkedin_url:
                primary_action = "LinkedIn DM"
            elif full_name or company_name:
                primary_action = "LinkedIn lookup + infer email"

            table.add_row(
                stage_label,
                full_name or "(unknown recruiter)",
                primary_action,
                linkedin_lookup[:58],
                str(row.get("title") or "")[:38],
                company_name[:24],
                str(row.get("score") or 0),
                str(row.get("last_outreach_at") or "")[:19],
            )
            displayed += 1

            target_email = explicit_email or inferred_email
            if target_email:
                email_targets.append({**row, "target_email": target_email})

            if not agency_stage:
                linkedin_targets.append(
                    {
                        **row,
                        "full_name": full_name,
                        "company_name": company_name,
                        "title": title,
                        "linkedin_lookup": linkedin_lookup,
                    }
                )

        if displayed == 0:
            console.print(
                "[yellow]No high-confidence recruiter contacts yet.[/yellow] "
                "[dim]Enable contact_intel.use_llm or run more searches.[/dim]"
            )
            return 0

        console.print(table)
        console.print(
            "\n[dim]Sequence:"
            " agency recruiter known -> email;"
            " else JD email;"
            " else LinkedIn lookup + inferred email suggestion."
            "[/dim]"
        )

        outreach_cfg = (
            (config.get("contact_intel", {}) or {}).get("outreach", {})
            if isinstance(config, dict)
            else {}
        )
        resolved_phone = (
            str(cta_phone or "").strip()
            or str(outreach_cfg.get("cta_phone") or "").strip()
        )
        sender_name = "Candidate"
        try:
            from ronin.profile import load_profile

            profile = load_profile()
            sender_name = str(profile.personal.name or "").strip() or sender_name
        except Exception:
            pass

        if write_linkedin_drafts and linkedin_targets:
            draft_paths: List[str] = []
            for idx, row in enumerate(linkedin_targets, start=1):
                lookup_url = str(row.get("linkedin_lookup") or "").strip()
                message = build_linkedin_dm_message(
                    candidate=row,
                    sender_name=sender_name,
                    cta_phone=resolved_phone,
                )
                job_id = str(row.get("job_id") or "")
                recruiter_id = int(row.get("recruiter_id") or 0)
                name_slug = re.sub(
                    r"[^A-Za-z0-9_.\-]+",
                    "_",
                    str(row.get("full_name") or "hiring_manager"),
                )
                prefix = f"{idx:02d}_{job_id}_{name_slug}"
                path = write_linkedin_dm_draft(
                    base_dir="data/linkedin_dm_drafts",
                    filename_prefix=prefix,
                    lookup_url=lookup_url,
                    candidate=row,
                    message=message,
                )
                draft_paths.append(path)
                db.log_outreach_event(
                    job_id=job_id,
                    recruiter_id=recruiter_id,
                    channel="linkedin_draft",
                    target=lookup_url,
                    subject="",
                    body=message,
                    status="drafted",
                )
            console.print(
                "[green]LinkedIn DM drafts created:[/green] "
                f"{len(draft_paths)} in data/linkedin_dm_drafts/"
            )
            if draft_paths:
                console.print(f"[dim]Example draft: {draft_paths[0]}[/dim]")

        if open_linkedin and linkedin_targets:
            import webbrowser

            opened = 0
            seen = set()
            for row in linkedin_targets:
                lookup_url = str(row.get("linkedin_lookup") or "").strip()
                if not lookup_url or lookup_url in seen:
                    continue
                webbrowser.open(lookup_url, new=2)
                seen.add(lookup_url)
                opened += 1
                if opened >= max(1, int(open_linkedin_limit)):
                    break
            console.print(
                f"[green]Opened {opened} LinkedIn lookup tab(s).[/green]"
            )

        if not send_email:
            return 0

        if not email_targets:
            console.print(
                "[yellow]No email targets available. Use LinkedIn actions from the queue above.[/yellow]"
            )
            return 0

        if not yes:
            go = Confirm.ask(
                f"Send outreach emails to {len(email_targets)} targets?",
                default=False,
            )
            if not go:
                console.print("[yellow]Email send cancelled.[/yellow]")
                return 0

        from ronin.gmail_outreach import GmailOutreachSender

        tracking_gmail = (
            (config.get("tracking", {}) or {}).get("gmail", {})
            if isinstance(config, dict)
            else {}
        )

        sender = GmailOutreachSender(
            credentials_path=str(tracking_gmail.get("credentials_path") or ""),
            token_path=str(tracking_gmail.get("token_path") or ""),
            auth_mode=str(tracking_gmail.get("auth_mode") or "auto"),
        )

        sent = 0
        failed = 0
        for row in email_targets:
            to_address = str(row.get("target_email") or "").strip()
            if not to_address:
                continue

            try:
                subject, body = build_outreach_email(
                    candidate=row,
                    sender_name=sender_name,
                    cta_phone=resolved_phone,
                )
                result = sender.send_plain_email(
                    to_address=to_address,
                    subject=subject,
                    body_text=body,
                    dry_run=bool(dry_run_email),
                )
                status = "dry_run" if bool(dry_run_email) else "sent"
                db.log_outreach_event(
                    job_id=str(row.get("job_id") or ""),
                    recruiter_id=int(row.get("recruiter_id") or 0),
                    channel="email",
                    target=to_address,
                    subject=subject,
                    body=body,
                    status=status,
                    sent_at=None,
                )
                sent += 1
                console.print(
                    f"[green]✓[/green] {status} -> {to_address} "
                    f"[dim]({result.get('message_id', '')})[/dim]"
                )
            except Exception as exc:
                failed += 1
                db.log_outreach_event(
                    job_id=str(row.get("job_id") or ""),
                    recruiter_id=int(row.get("recruiter_id") or 0),
                    channel="email",
                    target=to_address,
                    status="failed",
                    error_message=str(exc),
                )
                console.print(f"[red]✗[/red] {to_address} [dim]{exc}[/dim]")

        console.print(
            f"\n[bold]Email outreach complete:[/bold] sent={sent}, failed={failed}, "
            f"dry_run={1 if dry_run_email else 0}"
        )
        return 0 if failed == 0 else 1
    finally:
        db.close()


def classify_file(file_path: str) -> int:
    """Classify a local JD file and print archetype weights."""
    load_env()
    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        return 1

    text = path.read_text(encoding="utf-8")
    classifier = ArchetypeClassifier(enable_embeddings=True)
    result = classifier.classify(jd_text=text, job_title=path.stem)

    table = Table(title=f"Archetype Weights — {path.name}", border_style="dim")
    table.add_column("Archetype", style="magenta")
    table.add_column("Score", justify="right")
    for archetype, score in sorted(
        result["archetype_scores"].items(), key=lambda item: item[1], reverse=True
    ):
        table.add_row(archetype.capitalize(), f"{float(score):.3f}")

    console.print(table)
    console.print(
        f"\nPrimary: [bold cyan]{result['archetype_primary']}[/bold cyan] | "
        f"job_type={result.get('job_type')} | "
        f"seniority={result.get('seniority_level')}"
    )
    return 0


def log_call() -> int:
    """Open local phone call intake form."""
    load_env()
    try:
        from ronin.feedback.phone_intake import run_phone_call_intake
    except ModuleNotFoundError:
        console.print(
            "[red]Flask is required for call intake.[/red] "
            "Install dependencies with `pip install -r requirements.txt`."
        )
        return 1

    console.print(
        "[green]Starting call intake on http://localhost:5001/log-call[/green]"
    )
    run_phone_call_intake(host="127.0.0.1", port=5001, open_browser=True)
    return 0


def _apply_records(
    jobs: List[Dict],
    db,
    profile_state: str,
    batch_id: Optional[int],
    resume_variant_sent: str,
    resume_commit_hash: Optional[str],
    resume_profile_override: str = "",
) -> Dict[str, int]:
    """Apply to a list of queued roles and persist batch metadata."""
    applied = 0
    failed = 0
    stale = 0

    applier = SeekApplier()
    try:
        if not applier.login():
            raise RuntimeError("Seek login required. Refresh session and retry.")

        for record in jobs:
            resolved_profile = str(resume_profile_override or "").strip().lower()
            if resolved_profile not in ARCHETYPE_PROFILES:
                job_archetype = (
                    str(
                        record.get("resume_archetype")
                        or record.get("archetype_primary")
                        or ""
                    )
                    .strip()
                    .lower()
                )
                resolved_profile = (
                    job_archetype if job_archetype in ARCHETYPE_PROFILES else "builder"
                )

            result = applier.apply_to_job(
                job_id=record.get("job_id", ""),
                job_description=record.get("description", ""),
                score=int(record.get("score", 0) or 0),
                key_tools=record.get("key_tools", ""),
                company_name=record.get("company_name", ""),
                title=record.get("title", ""),
                resume_profile=resolved_profile,
                work_type=record.get("work_type", ""),
            )

            if result == "APPLIED":
                applied += 1
                db.update_record(record["id"], {"status": "APPLIED"})
                db.mark_job_applied(
                    record_id=int(record["id"]),
                    batch_id=batch_id,
                    profile_state=profile_state,
                    resume_variant_sent=resume_variant_sent,
                    resume_commit_hash=resume_commit_hash,
                )
                app_record = dict(record)
                app_record.update(
                    {
                        "resume_variant_sent": resume_variant_sent,
                        "resume_commit_hash": resume_commit_hash,
                        "profile_state_at_application": profile_state,
                        "application_batch_id": batch_id,
                        "date_applied": None,
                    }
                )
                db.record_application_submission(app_record)
                console.print(
                    f"[green]✓[/green] {record.get('title', '')[:44]} @ {record.get('company_name', '')[:24]}"
                )
            elif result == "STALE":
                stale += 1
                db.update_record(record["id"], {"status": "STALE"})
                console.print(
                    f"[yellow]○[/yellow] {record.get('title', '')[:44]} [dim](expired)[/dim]"
                )
            else:
                failed += 1
                db.update_record(record["id"], {"status": "APP_ERROR"})
                console.print(f"[red]✗[/red] {record.get('title', '')[:44]}")

    except Exception as exc:
        logger.error(f"Batch apply failed: {exc}")
        failed += len(jobs)
    finally:
        applier.cleanup()

    return {"applied": applied, "failed": failed, "stale": stale}


# ---------------------------------------------------------------------------
# External (agent-led) applications — Phase 1 report + Phase 2 apply loop
# ---------------------------------------------------------------------------


def apply_external(
    limit: int = 10,
    min_score: int = 0,
    dry_run: Optional[bool] = None,
    report: bool = False,
    yes: bool = False,
) -> int:
    """Report on, or apply to, external (link-out) jobs via the agent applier.

    Args:
        limit: Max external jobs to process in this run.
        min_score: Only apply to jobs at/above this analyzer score.
        dry_run: Force dry-run on/off. None uses agent_apply.dry_run config.
        report: If True, only print the external-coverage report and exit.
        yes: Skip the confirmation prompt before a LIVE (non-dry-run) run.

    Returns:
        Process exit code (0 on success).
    """
    load_env()
    config = load_config()
    db = get_db_manager(config=config)

    # -- Report mode: size how much of the pipeline is link-out ------------
    rows = db.get_external_jobs_report()
    total_external = sum(int(r.get("external_count", 0) or 0) for r in rows)
    total_applied = sum(int(r.get("applied_count", 0) or 0) for r in rows)

    table = Table(title="External (link-out) jobs by company")
    table.add_column("Company", style="cyan", no_wrap=True)
    table.add_column("External", justify="right")
    table.add_column("Applied", justify="right")
    table.add_column("Top score", justify="right")
    for r in rows[:40]:
        table.add_row(
            str(r.get("company_name", "Unknown"))[:38],
            str(r.get("external_count", 0)),
            str(r.get("applied_count", 0)),
            str(r.get("top_score", "") or ""),
        )
    console.print(table)
    console.print(
        f"[bold]{total_external}[/bold] external jobs captured "
        f"({total_applied} applied). These are invisible to the Seek Quick "
        f"Apply path."
    )
    if not total_external:
        console.print(
            "[yellow]No external jobs captured yet.[/yellow] Enable "
            "[bold]scraping.capture_external: true[/bold] and run a search first."
        )
    if report:
        return 0

    # -- Apply mode --------------------------------------------------------
    jobs = db.get_pending_external_jobs(limit=limit, min_score=min_score)
    if not jobs:
        console.print("[yellow]No pending external jobs to apply to.[/yellow]")
        return 0

    from ronin.applier.agent_applier import (
        STATUS_APPLIED,
        STATUS_DRY_RUN,
        STATUS_STALE,
        AgentApplier,
    )

    # Agent status -> persisted job status. NEEDS_HUMAN and BLOCKED are terminal
    # for automation and are NOT queue-eligible, so they stop being retried;
    # a spent step budget is a transient failure and stays retryable.
    _TERMINAL_STATUS = {
        "NEEDS_HUMAN": "NEEDS_HUMAN",
        "BLOCKED": "BLOCKED",
        "STEP_BUDGET_EXHAUSTED": "APP_ERROR",
        "APP_ERROR": "APP_ERROR",
    }

    applier = AgentApplier(dry_run=dry_run)
    mode = "DRY-RUN" if applier.dry_run else "LIVE"
    console.print(
        f"[bold]{len(jobs)}[/bold] external job(s) queued · mode: "
        f"[{'yellow' if applier.dry_run else 'red'}]{mode}[/]"
    )
    if not applier.dry_run and not yes:
        if not Confirm.ask(
            "LIVE mode will SUBMIT real applications under your name. Continue?",
            default=False,
        ):
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    applied = dry = failed = 0
    try:
        for record in jobs:
            job_id = record.get("job_id", "")
            title = record.get("title", "")
            company = record.get("company_name", "")
            resume_profile = (
                str(record.get("resume_profile") or "builder").strip().lower()
            )
            console.print(
                f"[dim]→ {title[:44]} @ {company[:24]} ({job_id})[/dim]"
            )
            try:
                result = applier.apply_to_job(
                    job_id=job_id,
                    job_description=record.get("description", ""),
                    score=int(record.get("score", 0) or 0),
                    key_tools=record.get("key_tools", ""),
                    company_name=company,
                    title=title,
                    resume_profile=resume_profile,
                    work_type=record.get("work_type", ""),
                    apply_url=record.get("apply_url"),
                    job_url=record.get("url"),
                )
            except Exception as exc:
                logger.error(f"Agent apply crashed for {job_id}: {exc}")
                result = "APP_ERROR"

            if result == STATUS_APPLIED:
                applied += 1
                db.update_job_status(job_id, "APPLIED")
                console.print(f"[green]✓ applied[/green] {title[:44]}")
            elif result == STATUS_DRY_RUN:
                dry += 1
                # Do NOT mark applied — dry-run stopped before submit.
                console.print(f"[yellow]◐ dry-run reached submit[/yellow] {title[:44]}")
            elif result == STATUS_STALE:
                db.update_job_status(job_id, "STALE")
                console.print(f"[yellow]○ expired[/yellow] {title[:44]}")
            else:
                failed += 1
                # Persist the REAL outcome. Collapsing everything to APP_ERROR
                # left the job queue-eligible, so a job blocked on something
                # automation cannot fix (no LinkedIn session, captcha) was
                # retried on every run, forever, with the reason discarded.
                db.update_job_status(job_id, _TERMINAL_STATUS.get(result, "APP_ERROR"))
                console.print(f"[red]✗ {result}[/red] {title[:44]}")
    finally:
        applier.cleanup()

    console.print(
        f"\n[bold]Done.[/bold] applied={applied} dry_run={dry} failed={failed}"
    )
    return 0
