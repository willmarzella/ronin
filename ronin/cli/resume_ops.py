"""CLI helpers for resume variant build + Seek upload automation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from rich.console import Console

from ronin.cli.config_cmd import set_config_key
from ronin.config import get_ronin_home, load_config, load_env
from ronin.profile_store import (
    load_profile_yaml_raw,
    upsert_resume_profile,
    write_profile_yaml_raw,
)
from ronin.resume_variants import ARCHETYPES, ResumeVariantManager
from ronin.seek.resume_uploader import SeekResumeUploadError, SeekResumeUploader


console = Console()


def _markdown_to_text(md: str) -> str:
    """Very small markdown-to-text fallback for cover-letter context."""
    lines: List[str] = []
    for raw in (md or "").splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if line.startswith("-") or line.startswith("*"):
            line = line[1:].strip()
        # Collapse basic link syntax.
        line = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)
        lines.append(line)
    # Compress multiple blank lines.
    out: List[str] = []
    blank = 0
    for ln in lines:
        if ln.strip() == "":
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip() + "\n"


def _ensure_resume_text_file(
    *,
    manager: ResumeVariantManager,
    archetype: str,
    resume_profile_name: str,
) -> Path:
    """Write ~/.ronin/resumes/<name>.txt from the variant markdown (best-effort)."""
    md_path = manager.ensure_markdown(archetype)
    md_text = md_path.read_text(encoding="utf-8")
    txt = _markdown_to_text(md_text)

    dest_dir = get_ronin_home() / "resumes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = (dest_dir / f"{resume_profile_name}.txt").resolve()
    dest_path.write_text(txt, encoding="utf-8")
    return dest_path


def log_note(*, note: str = "") -> int:
    """Append a work-experience note to source_log.md (or open it if empty)."""
    import os
    import subprocess

    from ronin.resume_pipeline import append_log

    load_env()
    config = load_config()

    text = str(note or "").strip()
    if not text:
        # No text: open the log in $EDITOR for a deliberate jot.
        from ronin.resume_pipeline import _paths

        log_path = _paths(config)["log"]
        editor = os.environ.get("EDITOR", "nano")
        console.print(f"[dim]Opening[/dim] {log_path} [dim]in {editor}[/dim]")
        try:
            subprocess.run([editor, str(log_path)])
        except Exception as exc:
            console.print(f"[red]Could not open editor:[/red] {exc}")
            return 1
        return 0

    path = append_log(text, config=config)
    console.print(f"[green]Logged[/green] to {path.name}: [dim]{text[:80]}[/dim]")
    console.print(
        "[dim]Folds into your resume on the next[/dim] ronin resume regen "
        "[dim](weekly, or run it now).[/dim]"
    )
    return 0


def regen_variant(
    *,
    variants: Optional[List[str]] = None,
    force: bool = False,
    push: bool = True,
) -> int:
    """Regenerate the tuned resume variants from source.yml via the AI agents."""
    from ronin.resume_pipeline import ResumeRegenError, regen

    load_env()
    try:
        report = regen(variants=variants, force=force, push=push)
    except ResumeRegenError as exc:
        console.print(f"[red]Regen refused (kept existing files):[/red] {exc}")
        return 1
    except Exception as exc:
        console.print(f"[red]Regen failed:[/red] {str(exc)[:240]}")
        return 1

    if report.get("skipped"):
        console.print(
            f"[yellow]Skipped[/yellow] — {report.get('reason')} "
            "(use --force to regen anyway)"
        )
        return 0

    written = report.get("written") or []
    if written:
        console.print(
            f"[green]Regenerated[/green] {', '.join(f'{v}.yml' for v in written)}"
            + (" [dim](folded new log notes)[/dim]" if report.get("ingested_notes") else "")
        )
    failures = report.get("failures") or {}
    for variant, reason in failures.items():
        console.print(f"[red]Kept existing[/red] {variant}.yml — {str(reason)[:160]}")
    return 1 if failures and not written else 0


def refresh_seek(*, variant: str = "c", dry_run: bool = False, force: bool = False) -> int:
    """Weekly Seek profile refresh from the variant yaml (recency touch)."""
    from ronin.seek.profile_refresh import refresh
    from ronin.seek.profile_updater import SeekProfileAutomationError

    load_env()
    try:
        report = refresh(variant=variant, dry_run=dry_run, force=force)
    except SeekProfileAutomationError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    except Exception as exc:
        console.print(f"[red]Seek refresh failed:[/red] {str(exc)[:240]}")
        return 1

    mode = report.get("mode")
    if dry_run:
        console.print(f"[yellow]Dry run[/yellow] — would run a [bold]{mode}[/bold] update")
        return 0
    if mode == "full":
        console.print(f"[green]Seek profile updated[/green] (full apply from {variant}.yml)")
    else:
        console.print("[green]Seek recency touched[/green] (no content change; timestamp bumped)")
    return 0


def build_pdfs(*, archetypes: List[str]) -> int:
    load_env()
    config = load_config()
    manager = ResumeVariantManager(config)

    ok = 0
    for archetype in archetypes:
        pdf = manager.build_pdf(archetype)
        if not pdf:
            console.print(
                f"[red]PDF build failed or missing for[/red] {archetype} (check pdflatex + resume repo paths)"
            )
            ok = 1
        else:
            console.print(f"[green]Built[/green] {pdf}")
    return ok


def debug(url: str = "") -> int:
    """Open Playwright Inspector on the Seek resumes page."""
    load_env()
    config = load_config()
    uploader = SeekResumeUploader(config=config)
    try:
        uploader.debug_pause(url=url)
        return 0
    except SeekResumeUploadError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1


def upload_variants(
    *,
    archetypes: List[str],
    dry_run: bool = False,
    yes: bool = False,
    force_new: bool = False,
    set_mapping: bool = True,
    purge_existing: bool = False,
    as_profile: str = "",
) -> int:
    """Build PDFs for archetypes and upload/replace them in Seek.

    Args:
        as_profile: Upload under this profile.yaml resume name instead of the
            variant's own name. Needed when the resume yaml and the registry
            entry are named differently — c.yml is registered as
            ``contract_aggressive``. Single variant only.

    Side effects (unless dry_run):
        - updates ~/.ronin/profile.yaml with seek_resume_id per archetype
        - updates ~/.ronin/config.yaml resume_variants.seek_profile_mapping
        - writes ~/.ronin/resumes/<resume profile>.txt for cover letter context
    """

    load_env()
    config = load_config()

    as_profile = str(as_profile or "").strip()
    if as_profile and len(archetypes) != 1:
        console.print(
            "[red]--as takes exactly one variant[/red] "
            f"(got {len(archetypes)}: {', '.join(archetypes)})"
        )
        return 1

    # Default mapping: archetype -> resume profile name (same string).
    # We intentionally do NOT read resume_variants.seek_profile_mapping here,
    # because it may currently point to "default" and we'd risk overwriting a
    # single resume slot repeatedly.
    resume_profile_names = (
        {archetypes[0]: as_profile} if as_profile else {a: a for a in archetypes}
    )

    if not yes:
        console.print("\n[bold]Resume variant upload plan:[/bold]")
        for a in archetypes:
            console.print(f"- {a} -> resume profile '{resume_profile_names[a]}'")

        if purge_existing:
            console.print(
                "[yellow]Will delete ALL existing Seek resumés before uploading.[/yellow]"
            )
        if dry_run:
            console.print(
                "[yellow]Dry run enabled: no Seek or file updates will be made.[/yellow]"
            )

        from rich.prompt import Confirm

        if not Confirm.ask("Continue?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    manager = ResumeVariantManager(config)
    uploader = SeekResumeUploader(config=config)

    if purge_existing and not dry_run:
        if not yes:
            from rich.prompt import Confirm

            if not Confirm.ask(
                "Delete all existing Seek resumés now?",
                default=False,
            ):
                console.print("[yellow]Cancelled.[/yellow]")
                return 0

        console.print("[dim]Deleting existing Seek resumés...[/dim]")
        deleted = uploader.delete_all_resumes(allow_manual_login=True, max_deletes=25)
        console.print(f"[green]Deleted[/green] {deleted} resumé(s) from Seek")

        # After purging, always upload new files (no replace).
        force_new = True

    # Load profile.yaml raw so we can patch IDs in-place.
    profile_path, profile_data, header = load_profile_yaml_raw()

    failures = 0
    successes = 0
    for archetype in archetypes:
        resume_profile = resume_profile_names[archetype]
        pdf = manager.build_pdf(archetype)
        if not pdf:
            console.print(f"[red]Missing PDF for[/red] {archetype} (skipping upload)")
            failures += 1
            continue

        # Determine existing resume id (if any) for replace, and keep whatever
        # text filename the entry already uses — renaming it would orphan the
        # old file and break any hand-set `file:` (c.yml registers as
        # contract_aggressive but keeps c.txt).
        existing_id = ""
        text_file = f"{resume_profile}.txt"
        resumes = profile_data.get("resumes")
        if isinstance(resumes, list):
            for item in resumes:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name") or "") == resume_profile:
                    if not force_new and not purge_existing:
                        existing_id = str(item.get("seek_resume_id") or "").strip()
                    text_file = str(item.get("file") or "").strip() or text_file
                    break

        if dry_run:
            console.print(
                f"[dim]Would upload[/dim] {pdf} [dim]as[/dim] {resume_profile}"
                + (f" [dim](replace {existing_id})[/dim]" if existing_id else "")
            )
            continue

        try:
            new_id = uploader.upload_or_replace(
                pdf_path=Path(pdf),
                resume_id=existing_id,
                allow_manual_login=True,
            )
            _ensure_resume_text_file(
                manager=manager,
                archetype=archetype,
                resume_profile_name=Path(text_file).stem,
            )

            upsert_resume_profile(
                profile_data,
                name=resume_profile,
                file=text_file,
                seek_resume_id=new_id,
                archetype="adaptation",
            )

            # Ensure apply batch uses this resume profile for the archetype.
            # Skipped under --as: that variant is not an archetype, so it has no
            # `apply batch <archetype>` slot to point at.
            if set_mapping and not as_profile:
                set_config_key(
                    f"resume_variants.seek_profile_mapping.{archetype}",
                    f'"{resume_profile}"',
                )

            console.print(
                f"[green]Uploaded[/green] {archetype} -> seek_resume_id={new_id}"
            )
            successes += 1
        except SeekResumeUploadError as exc:
            console.print(f"[red]Seek upload failed for[/red] {archetype}: {exc}")
            failures += 1
        except Exception as exc:
            console.print(
                f"[red]Unexpected error for[/red] {archetype}: {str(exc)[:220]}"
            )
            failures += 1

    if not dry_run and successes > 0:
        write_profile_yaml_raw(profile_path, profile_data, header_text=header)
        console.print(f"\n[green]Updated[/green] {profile_path}")
    elif not dry_run and successes == 0:
        console.print(
            f"\n[yellow]No successful uploads; leaving profile unchanged:[/yellow] {profile_path}"
        )

    return 0 if failures == 0 else 1
