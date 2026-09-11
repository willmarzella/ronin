"""Unified CLI entry point for Ronin.

Dispatches subcommands to their respective modules:

    ronin setup [--step STEP]
    ronin search
    ronin apply
    ronin apply queue
    ronin apply batch <archetype>
    ronin apply status
    ronin apply drift
    ronin apply classify <file>
    ronin apply log-call
    ronin apply sync
    ronin apply versions
    ronin apply alerts
    ronin apply contacts [--refresh] [--send-email]
    ronin profile set <archetype>
    ronin profile debug
    ronin resume build <archetype|all>
    ronin resume upload <archetype|all> [--force-new]
    ronin resume debug [--url URL]
    ronin run
    ronin feedback sync [--max-messages N] [--dry-run]
    ronin feedback report [--min-samples N]
    ronin telegram bot [--token TOKEN] [--chat-id CHAT_ID]
    ronin telegram send-status [--token TOKEN] [--chat-id CHAT_ID]
    ronin worker start
    ronin worker once
    ronin config set --key KEY --value VALUE
    ronin status
    ronin schedule install [--interval HOURS] [--task TASK] [--at HH:MM] [--weekdays]
    ronin schedule uninstall
    ronin schedule status
"""

import argparse
import sys

from loguru import logger

__version__ = "2.0.0"


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with all subcommands.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="ronin",
        description="Ronin — AI-Powered Job Automation Platform",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -- setup ---------------------------------------------------------------
    setup_parser = subparsers.add_parser("setup", help="Run setup wizard")
    setup_parser.add_argument(
        "--step",
        type=str,
        default=None,
        help="Run a specific setup step instead of the full wizard",
    )

    # -- search --------------------------------------------------------------
    subparsers.add_parser("search", help="Run job search")

    # -- log (quick-capture work wins into source_log.md) --------------------
    log_parser = subparsers.add_parser(
        "log",
        help="Append a work-experience note for the weekly resume agents",
    )
    log_parser.add_argument(
        "note",
        nargs="*",
        help="The note text (quotes optional). Empty opens source_log.md instead.",
    )

    # -- apply ---------------------------------------------------------------
    apply_parser = subparsers.add_parser(
        "apply",
        help="Run job applications and queue/batch workflows",
    )
    apply_sub = apply_parser.add_subparsers(dest="apply_action")

    apply_sub.add_parser("run", help="Legacy mode: apply to all pending jobs")

    apply_queue = apply_sub.add_parser(
        "queue",
        help="Show queued applications grouped by archetype",
    )
    apply_queue.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max queued rows to preview (default: 200)",
    )

    apply_batch = apply_sub.add_parser(
        "batch",
        help="Apply to all queued jobs for an archetype",
    )
    apply_batch.add_argument(
        "archetype",
        choices=["builder", "fixer", "operator", "translator"],
        help="Archetype batch to apply",
    )
    apply_batch.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max jobs to apply in this batch",
    )
    apply_batch.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    apply_batch.add_argument(
        "--auto-profile",
        action="store_true",
        help="Auto-switch Seek profile to this archetype before applying (Playwright)",
    )
    apply_batch.add_argument(
        "--dry-run-profile",
        action="store_true",
        help="When used with --auto-profile, do not save profile changes",
    )

    apply_sub.add_parser("status", help="Show funnel metrics and conversion rates")

    apply_external = apply_sub.add_parser(
        "external",
        help="Report on / apply to external (link-out) jobs via the agent applier",
    )
    apply_external.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max external jobs to process (default: 10)",
    )
    apply_external.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Only apply to external jobs at/above this score (default: 0)",
    )
    apply_external.add_argument(
        "--report",
        action="store_true",
        help="Only show the external-coverage report; do not apply",
    )
    apply_external.add_argument(
        "--live",
        action="store_true",
        help="Disable dry-run and SUBMIT real applications (default: dry-run)",
    )
    apply_external.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run (fill + traverse, never submit). This is the default.",
    )
    apply_external.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt before a LIVE run",
    )

    # ------------------------------------------------------------------ ats
    ats_parser = subparsers.add_parser(
        "ats", help="Inspect and profile unrecognised ATS platforms"
    )
    ats_sub = ats_parser.add_subparsers(dest="ats_action", required=True)
    ats_review_parser = ats_sub.add_parser(
        "review", help="List ATS hosts the agent did not recognise"
    )
    ats_review_parser.add_argument(
        "--status",
        default="",
        help="Filter by workflow status (new/drafted/done/ignored)",
    )
    ats_draft_parser = ats_sub.add_parser(
        "draft", help="Draft a candidate ATS profile from captured page evidence"
    )
    ats_draft_parser.add_argument("host", help="Host to draft a profile for")

    apply_corpus = apply_sub.add_parser(
        "corpus",
        help="Show corpus analysis (normalized job title counts)",
    )
    apply_corpus.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max title rows to show (default: 30)",
    )

    apply_sample = apply_sub.add_parser(
        "sample-labels",
        help="Export a JD sample JSONL for manual labeling",
    )
    apply_sample.add_argument(
        "--count",
        type=int,
        default=50,
        help="How many JDs to sample (default: 50)",
    )
    apply_sample.add_argument(
        "--output",
        type=str,
        default="labels_sample.jsonl",
        help="Output JSONL file path (default: labels_sample.jsonl)",
    )

    apply_validate = apply_sub.add_parser(
        "validate-labels",
        help="Run classifier agreement against a labeled JSONL file",
    )
    apply_validate.add_argument(
        "file",
        help="Path to labels JSONL (must include description/jd_text + manual_label)",
    )

    apply_drift = apply_sub.add_parser(
        "drift",
        help="Show drift metrics and active alerts",
    )
    apply_drift.add_argument(
        "--run-checks",
        action="store_true",
        help="Run weekly drift checks before displaying metrics",
    )

    apply_classify = apply_sub.add_parser(
        "classify",
        help="Score a single JD file and return archetype weights",
    )
    apply_classify.add_argument("file", help="Path to JD text/markdown file")

    apply_sub.add_parser(
        "log-call",
        help="Open local phone call intake form in browser",
    )

    apply_sync = apply_sub.add_parser(
        "sync",
        help="Force sync queue gating and resume variant alignments",
    )
    apply_sync.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max jobs to re-evaluate during sync",
    )

    apply_review = apply_sub.add_parser(
        "review",
        help="Review and override close-call archetype selections",
    )
    apply_review.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max close-call rows to review (default: 25)",
    )

    apply_ghosts = apply_sub.add_parser(
        "ghosts",
        help="List ghosted applications (no signal after 30+ days)",
    )
    apply_ghosts.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max ghosted applications to show (default: 50)",
    )

    apply_versions = apply_sub.add_parser(
        "versions",
        help="Show resume commit-hash performance comparison",
    )
    apply_versions.add_argument(
        "--min-apps",
        type=int,
        default=15,
        help="Minimum applications per version row (default: 15)",
    )

    apply_sub.add_parser(
        "alerts",
        help="Show all unacknowledged drift alerts",
    )

    apply_contacts = apply_sub.add_parser(
        "contacts",
        help="Extract recruiter contacts and show ranked outreach targets",
    )
    apply_contacts.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max outreach candidates to display (default: 50)",
    )
    apply_contacts.add_argument(
        "--source",
        type=str,
        default="",
        help="Optional source filter (e.g. seek, linkedin)",
    )
    apply_contacts.add_argument(
        "--refresh",
        action="store_true",
        help="Run contact extraction on recent jobs before listing targets",
    )
    apply_contacts.add_argument(
        "--refresh-limit",
        type=int,
        default=150,
        help="Max jobs to scan when --refresh is enabled (default: 150)",
    )
    apply_contacts.add_argument(
        "--send-email",
        action="store_true",
        help="Send outreach emails to ranked contacts (explicit opt-in)",
    )
    apply_contacts.add_argument(
        "--dry-run-email",
        action="store_true",
        help="Prepare/log outreach emails without sending",
    )
    apply_contacts.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt for email sending",
    )
    apply_contacts.add_argument(
        "--cta-phone",
        type=str,
        default="",
        help="Override CTA phone number in outreach message",
    )
    apply_contacts.add_argument(
        "--open-linkedin",
        action="store_true",
        help="Open top LinkedIn people search URLs in browser tabs",
    )
    apply_contacts.add_argument(
        "--open-linkedin-limit",
        type=int,
        default=5,
        help="Max LinkedIn tabs to open when --open-linkedin is set (default: 5)",
    )
    apply_contacts.add_argument(
        "--no-linkedin-drafts",
        action="store_true",
        help="Do not generate LinkedIn DM draft files",
    )
    apply_contacts.add_argument(
        "--seed-recruiter-email",
        type=str,
        default="",
        help="Manually add/track a known recruiter email (e.g. jonny.church@pra.com.au)",
    )
    apply_contacts.add_argument(
        "--seed-recruiter-name",
        type=str,
        default="",
        help="Optional recruiter full name when using --seed-recruiter-email",
    )
    apply_contacts.add_argument(
        "--seed-recruiter-company",
        type=str,
        default="",
        help="Optional company/agency name when using --seed-recruiter-email",
    )

    # -- profile -------------------------------------------------------------
    profile_parser = subparsers.add_parser(
        "profile",
        help="Automate Seek profile switching for batching",
    )
    profile_sub = profile_parser.add_subparsers(dest="profile_action")

    profile_set = profile_sub.add_parser(
        "set",
        help="Set your Seek profile to an archetype template",
    )
    profile_set.add_argument(
        "archetype",
        choices=["builder", "fixer", "operator", "translator"],
        help="Template archetype to apply",
    )
    profile_set.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    profile_set.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not save changes (best-effort)",
    )

    profile_sync = profile_sub.add_parser(
        "sync",
        help="Set Seek profile to dominant archetype when drift is detected",
    )
    profile_sync.add_argument(
        "--lookback-days",
        type=int,
        default=14,
        help="Lookback window for recent application dominance (default: 14)",
    )
    profile_sync.add_argument(
        "--min-recent-samples",
        type=int,
        default=8,
        help="Minimum recent applications required before preferring recent signal (default: 8)",
    )
    profile_sync.add_argument(
        "--min-queue-samples",
        type=int,
        default=4,
        help="Minimum queued jobs required before preferring queue signal (default: 4)",
    )
    profile_sync.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    profile_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Show drift decision without applying profile updates",
    )

    profile_refresh = profile_sub.add_parser(
        "refresh",
        help="Weekly Seek refresh from c.yml; touches recency when unchanged",
    )
    profile_refresh.add_argument(
        "--variant",
        default="c",
        help="Variant yaml to publish (default: c)",
    )
    profile_refresh.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the plan without writing to Seek",
    )
    profile_refresh.add_argument(
        "--force",
        action="store_true",
        help="Force a full apply even if content is unchanged",
    )

    profile_debug = profile_sub.add_parser(
        "debug",
        help="Open Playwright Inspector to discover selectors",
    )
    profile_debug.add_argument(
        "--url",
        type=str,
        default="",
        help="Optional URL to open (defaults to seek_profile.automation.profile_url)",
    )

    # -- resume --------------------------------------------------------------
    resume_parser = subparsers.add_parser(
        "resume",
        help="Build resume variant PDFs and upload/replace them in Seek",
    )
    resume_sub = resume_parser.add_subparsers(dest="resume_action")

    resume_build = resume_sub.add_parser(
        "build",
        help="Build resume PDFs from the nested resume/ repo",
    )
    resume_build.add_argument(
        "archetype",
        help="Which variant(s) to build: an archetype (builder/fixer/operator/"
        "translator), a custom role variant (e.g. solutions_engineer), or 'all'",
    )

    resume_regen = resume_sub.add_parser(
        "regen",
        help="Regenerate tuned resume variant(s) from source.yml via AI agents",
    )
    resume_regen.add_argument(
        "--variant",
        action="append",
        dest="variants",
        help=(
            "Variant to regenerate; repeatable. Default: builder, fixer, "
            "operator, translator. source.yml and c.yml are hand-owned poles "
            "and cannot be named here."
        ),
    )
    resume_regen.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if source.yml + log are unchanged",
    )
    resume_regen.add_argument(
        "--no-push",
        action="store_true",
        help="Commit locally but do not git push",
    )

    resume_upload = resume_sub.add_parser(
        "upload",
        help="Upload or replace resume PDFs in Seek (Playwright)",
    )
    resume_upload.add_argument(
        "archetype",
        help="Which variant(s) to upload: an archetype (builder/fixer/operator/"
        "translator), a custom role variant (e.g. solutions_engineer), or 'all'",
    )
    resume_upload.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    resume_upload.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not upload or write config/profile files",
    )
    resume_upload.add_argument(
        "--force-new",
        action="store_true",
        help="Always upload a new resume (do not attempt replace)",
    )
    resume_upload.add_argument(
        "--purge-existing",
        action="store_true",
        help="Delete all existing Seek resumés before uploading",
    )
    resume_upload.add_argument(
        "--no-set-mapping",
        action="store_true",
        help="Do not update resume_variants.seek_profile_mapping in ~/.ronin/config.yaml",
    )
    resume_upload.add_argument(
        "--as",
        dest="as_profile",
        default="",
        help="Register under this profile.yaml resume name instead of the "
        "variant name (e.g. `upload c --as contract_aggressive`). One variant only.",
    )

    resume_sync = resume_sub.add_parser(
        "sync",
        help="Refresh ~/.ronin/resumes/*.txt from the compiled variant markdown",
    )
    resume_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written without touching any file",
    )

    resume_debug = resume_sub.add_parser(
        "debug",
        help="Open Playwright Inspector on the Seek resumes page",
    )
    resume_debug.add_argument(
        "--url",
        type=str,
        default="",
        help="Optional URL to open (defaults to seek_profile.automation.resumes_url)",
    )

    # -- status --------------------------------------------------------------
    subparsers.add_parser("status", help="Show status dashboard")

    # -- telegram ------------------------------------------------------------
    telegram_parser = subparsers.add_parser(
        "telegram",
        help="Telegram bot and push notifications",
    )
    telegram_sub = telegram_parser.add_subparsers(dest="telegram_action")

    telegram_bot = telegram_sub.add_parser(
        "bot",
        help="Run long-poll Telegram bot",
    )
    telegram_bot.add_argument(
        "--token",
        type=str,
        default="",
        help="Telegram bot token (fallback: env/config)",
    )
    telegram_bot.add_argument(
        "--chat-id",
        type=str,
        default="",
        help="Restrict bot replies to one chat id (recommended)",
    )
    telegram_bot.add_argument(
        "--poll-timeout",
        type=int,
        default=45,
        help="Long-poll timeout seconds (default: 45)",
    )
    telegram_bot.add_argument(
        "--once",
        action="store_true",
        help="Process at most one polling cycle and exit",
    )

    telegram_send = telegram_sub.add_parser(
        "send-status",
        help="Send current status snapshot to Telegram",
    )
    telegram_send.add_argument(
        "--token",
        type=str,
        default="",
        help="Telegram bot token (fallback: env/config)",
    )
    telegram_send.add_argument(
        "--chat-id",
        type=str,
        default="",
        help="Target chat id (fallback: env/config)",
    )
    telegram_send.add_argument(
        "--no-concerns",
        action="store_true",
        help="Send snapshot without concern summary",
    )

    # -- run -----------------------------------------------------------------
    subparsers.add_parser(
        "run",
        help="Run search then apply if jobs are pending",
    )

    # -- feedback ------------------------------------------------------------
    feedback_parser = subparsers.add_parser(
        "feedback",
        help="Sync Gmail outcomes and show feedback analytics",
    )
    feedback_sub = feedback_parser.add_subparsers(dest="feedback_action")

    feedback_sync = feedback_sub.add_parser(
        "sync",
        help="Parse Gmail for application outcomes",
    )
    feedback_sync.add_argument(
        "--max-messages",
        type=int,
        default=250,
        help="Max Gmail messages to inspect per sync (default: 250)",
    )
    feedback_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and match without writing to the database",
    )

    feedback_report = feedback_sub.add_parser(
        "report",
        help="Show outcome conversion report",
    )
    feedback_report.add_argument(
        "--min-samples",
        type=int,
        default=2,
        help="Minimum sample size per bucket (default: 2)",
    )

    feedback_review = feedback_sub.add_parser(
        "review",
        help="Resolve emails requiring manual match review",
    )
    feedback_review.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max manual-review emails to show (default: 25)",
    )
    feedback_review.add_argument(
        "--auto",
        action="store_true",
        help="Auto-resolve any emails with a single clear match",
    )

    feedback_ignore = feedback_sub.add_parser(
        "ignore",
        help="Manage sender ignore list",
    )
    ignore_sub = feedback_ignore.add_subparsers(dest="ignore_action")

    ignore_add = ignore_sub.add_parser("add", help="Add an ignore rule")
    ignore_add.add_argument(
        "--domain",
        type=str,
        default="",
        help="Ignore sender domain (e.g. example.com)",
    )
    ignore_add.add_argument(
        "--address",
        type=str,
        default="",
        help="Ignore sender address (e.g. person@example.com)",
    )
    ignore_add.add_argument(
        "--reason",
        type=str,
        default="",
        help="Optional note for why this sender is ignored",
    )

    ignore_list = ignore_sub.add_parser("list", help="List ignore rules")
    ignore_list.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max rows to display (default: 200)",
    )

    # -- worker --------------------------------------------------------------
    worker_parser = subparsers.add_parser(
        "worker",
        help="Run remote worker scheduler jobs",
    )
    worker_sub = worker_parser.add_subparsers(dest="worker_action")
    worker_sub.add_parser("start", help="Start APScheduler worker loop")
    worker_sub.add_parser("once", help="Run one worker cycle immediately")
    worker_sub.add_parser("gmail", help="Run one Gmail polling + parsing cycle")
    worker_sub.add_parser("drift", help="Run drift checks once")

    # -- config --------------------------------------------------------------
    config_parser = subparsers.add_parser(
        "config",
        help="Edit ~/.ronin/config.yaml",
    )
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_set = config_sub.add_parser("set", help="Set a config key")
    config_set.add_argument(
        "--key",
        type=str,
        required=True,
        help='Dot path, e.g. "search.date_range"',
    )
    config_set.add_argument(
        "--value",
        type=str,
        required=True,
        help='YAML scalar, e.g. "4", "true", "hello"',
    )

    # -- db ------------------------------------------------------------------
    db_parser = subparsers.add_parser(
        "db",
        help="Database maintenance commands",
    )
    db_sub = db_parser.add_subparsers(dest="db_action")

    db_backup = db_sub.add_parser("backup", help="Create a point-in-time backup")
    db_backup.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write backups (default: ~/.ronin/backups)",
    )
    db_backup.add_argument(
        "--no-spool",
        action="store_true",
        help="Do not include the local spool DB in the backup",
    )

    db_migrate = db_sub.add_parser(
        "migrate",
        help="Backfill applications/archetypes for existing users",
    )
    db_migrate.add_argument(
        "--only",
        type=str,
        default="all",
        choices=["all", "applications", "archetypes"],
        help="Which migration to run (default: all)",
    )
    db_migrate.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max rows to process per step (default: 0 = no limit)",
    )
    db_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute what would change without writing",
    )
    db_migrate.add_argument(
        "--enable-embeddings",
        action="store_true",
        help="Use embedding-assisted archetype scoring (slower)",
    )

    # -- schedule ------------------------------------------------------------
    schedule_parser = subparsers.add_parser(
        "schedule", help="Manage scheduled automation"
    )
    schedule_sub = schedule_parser.add_subparsers(
        dest="schedule_action", help="Schedule actions"
    )

    install_parser = schedule_sub.add_parser(
        "install", help="Install scheduled automation"
    )
    install_parser.add_argument(
        "--interval",
        type=int,
        default=2,
        metavar="HOURS",
        help="Run interval in hours (default: 2)",
    )
    install_parser.add_argument(
        "--task",
        type=str,
        default="search",
        choices=["search", "run", "apply"],
        dest="scheduled_command",
        help="Ronin subcommand to schedule (default: search)",
    )
    install_parser.add_argument(
        "--at",
        type=str,
        default=None,
        metavar="HH:MM",
        help="Time-of-day to run (24h). If set, overrides --interval",
    )
    install_parser.add_argument(
        "--weekdays",
        action="store_true",
        help="When used with --at, run Monday-Friday only",
    )

    uninstall_parser = schedule_sub.add_parser("uninstall", help="Remove a schedule")
    uninstall_parser.add_argument(
        "--task",
        type=str,
        default="search",
        choices=["search", "run", "apply"],
        dest="scheduled_command",
        help="Ronin subcommand schedule to remove (default: search)",
    )

    status_parser = schedule_sub.add_parser("status", help="Check schedule status")
    status_parser.add_argument(
        "--task",
        type=str,
        default="search",
        choices=["search", "run", "apply"],
        dest="scheduled_command",
        help="Ronin subcommand schedule to inspect (default: search)",
    )

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate module."""
    from ronin.config import load_env

    load_env()

    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    logger.debug(f"CLI command: {args.command}")

    if args.command == "setup":
        from ronin.cli.setup import run_setup

        run_setup(step=args.step)

    elif args.command == "search":
        from ronin.cli.search import main as search_main

        search_main()

    elif args.command == "log":
        from ronin.cli.resume_ops import log_note

        rc = log_note(note=" ".join(getattr(args, "note", []) or []))
        if rc != 0:
            sys.exit(rc)

    elif args.command == "apply":
        apply_action = getattr(args, "apply_action", None)
        if apply_action in (None, "run"):
            from ronin.cli.apply import main as apply_main

            apply_main()
        elif apply_action == "queue":
            from ronin.cli.apply_ops import show_queue

            rc = show_queue(limit=getattr(args, "limit", 200))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "batch":
            from ronin.cli.apply_ops import batch_apply

            rc = batch_apply(
                archetype=getattr(args, "archetype"),
                limit=int(getattr(args, "limit", 0) or 0),
                yes=bool(getattr(args, "yes", False)),
                auto_profile=bool(getattr(args, "auto_profile", False)),
                dry_run_profile=bool(getattr(args, "dry_run_profile", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "status":
            from ronin.cli.apply_ops import show_apply_status

            rc = show_apply_status()
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "external":
            from ronin.cli.apply_ops import apply_external

            # --live overrides the config dry_run default; --dry-run forces it.
            # Neither flag → None → use agent_apply.dry_run (defaults True).
            dry_run_flag = None
            if bool(getattr(args, "live", False)):
                dry_run_flag = False
            elif bool(getattr(args, "dry_run", False)):
                dry_run_flag = True
            rc = apply_external(
                limit=int(getattr(args, "limit", 10) or 10),
                min_score=int(getattr(args, "min_score", 0) or 0),
                dry_run=dry_run_flag,
                report=bool(getattr(args, "report", False)),
                yes=bool(getattr(args, "yes", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "corpus":
            from ronin.cli.apply_ops import show_corpus

            rc = show_corpus(limit=int(getattr(args, "limit", 30) or 30))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "sample-labels":
            from ronin.cli.apply_ops import sample_labels

            rc = sample_labels(
                count=int(getattr(args, "count", 50) or 50),
                output_path=str(getattr(args, "output", "labels_sample.jsonl")),
            )
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "validate-labels":
            from ronin.cli.apply_ops import validate_labels

            rc = validate_labels(str(getattr(args, "file")))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "drift":
            from ronin.cli.apply_ops import show_drift

            rc = show_drift(run_checks=bool(getattr(args, "run_checks", False)))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "classify":
            from ronin.cli.apply_ops import classify_file

            rc = classify_file(getattr(args, "file"))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "log-call":
            from ronin.cli.apply_ops import log_call

            rc = log_call()
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "sync":
            from ronin.cli.apply_ops import sync_queue

            rc = sync_queue(limit=int(getattr(args, "limit", 0) or 0))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "review":
            from ronin.cli.apply_ops import review_selections

            rc = review_selections(limit=int(getattr(args, "limit", 25) or 25))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "ghosts":
            from ronin.cli.apply_ops import show_ghosts

            rc = show_ghosts(limit=int(getattr(args, "limit", 50) or 50))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "versions":
            from ronin.cli.apply_ops import show_versions

            rc = show_versions(min_apps=int(getattr(args, "min_apps", 15) or 15))
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "alerts":
            from ronin.cli.apply_ops import show_alerts

            rc = show_alerts()
            if rc != 0:
                sys.exit(rc)
        elif apply_action == "contacts":
            from ronin.cli.apply_ops import manage_contacts

            rc = manage_contacts(
                limit=int(getattr(args, "limit", 50) or 50),
                source=str(getattr(args, "source", "") or ""),
                refresh=bool(getattr(args, "refresh", False)),
                refresh_limit=int(getattr(args, "refresh_limit", 150) or 150),
                send_email=bool(getattr(args, "send_email", False)),
                dry_run_email=bool(getattr(args, "dry_run_email", False)),
                yes=bool(getattr(args, "yes", False)),
                cta_phone=str(getattr(args, "cta_phone", "") or ""),
                open_linkedin=bool(getattr(args, "open_linkedin", False)),
                open_linkedin_limit=int(getattr(args, "open_linkedin_limit", 5) or 5),
                write_linkedin_drafts=not bool(
                    getattr(args, "no_linkedin_drafts", False)
                ),
                seed_recruiter_email=str(
                    getattr(args, "seed_recruiter_email", "") or ""
                ),
                seed_recruiter_name=str(getattr(args, "seed_recruiter_name", "") or ""),
                seed_recruiter_company=str(
                    getattr(args, "seed_recruiter_company", "") or ""
                ),
            )
            if rc != 0:
                sys.exit(rc)
        else:
            parser.parse_args(["apply", "--help"])
            return

    elif args.command == "ats":
        from ronin.cli.ats_ops import ats_draft, ats_review

        ats_action = getattr(args, "ats_action", None)
        if ats_action == "review":
            rc = ats_review(status=str(getattr(args, "status", "") or ""))
        elif ats_action == "draft":
            rc = ats_draft(host=str(args.host))
        else:
            parser.parse_args(["ats", "--help"])
            return
        if rc != 0:
            sys.exit(rc)

    elif args.command == "profile":
        from ronin.cli.profile_ops import debug as profile_debug
        from ronin.cli.profile_ops import set_profile

        action = getattr(args, "profile_action", None)
        if action == "set":
            rc = set_profile(
                archetype=str(getattr(args, "archetype")),
                yes=bool(getattr(args, "yes", False)),
                dry_run=bool(getattr(args, "dry_run", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif action == "sync":
            # Drift-sync was removed with the profile refactor; import lazily so
            # `profile set` keeps working without it.
            from ronin.cli.profile_ops import sync_profile

            rc = sync_profile(
                yes=bool(getattr(args, "yes", False)),
                dry_run=bool(getattr(args, "dry_run", False)),
                lookback_days=int(getattr(args, "lookback_days", 14) or 14),
                min_recent_samples=int(getattr(args, "min_recent_samples", 8) or 8),
                min_queue_samples=int(getattr(args, "min_queue_samples", 4) or 4),
            )
            if rc != 0:
                sys.exit(rc)
        elif action == "refresh":
            from ronin.cli.resume_ops import refresh_seek

            rc = refresh_seek(
                variant=str(getattr(args, "variant", "c") or "c"),
                dry_run=bool(getattr(args, "dry_run", False)),
                force=bool(getattr(args, "force", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif action == "debug":
            rc = profile_debug(url=str(getattr(args, "url", "")))
            if rc != 0:
                sys.exit(rc)
        else:
            parser.parse_args(["profile", "--help"])
            return

    elif args.command == "run":
        from ronin.cli.run import main as run_main

        run_main()

    elif args.command == "resume":
        from ronin.cli.resume_ops import build_pdfs
        from ronin.cli.resume_ops import debug as resume_debug
        from ronin.cli.resume_ops import upload_variants

        action = getattr(args, "resume_action", None)
        archetype = str(getattr(args, "archetype", "") or "").strip().lower()
        if action == "build":
            archetypes = (
                ["builder", "fixer", "operator", "translator"]
                if archetype == "all"
                else [archetype]
            )
            rc = build_pdfs(archetypes=archetypes)
            if rc != 0:
                sys.exit(rc)
        elif action == "upload":
            archetypes = (
                ["builder", "fixer", "operator", "translator"]
                if archetype == "all"
                else [archetype]
            )
            rc = upload_variants(
                archetypes=archetypes,
                dry_run=bool(getattr(args, "dry_run", False)),
                yes=bool(getattr(args, "yes", False)),
                force_new=bool(getattr(args, "force_new", False)),
                purge_existing=bool(getattr(args, "purge_existing", False)),
                set_mapping=not bool(getattr(args, "no_set_mapping", False)),
                as_profile=str(getattr(args, "as_profile", "") or ""),
            )
            if rc != 0:
                sys.exit(rc)
        elif action == "regen":
            from ronin.cli.resume_ops import regen_variant

            rc = regen_variant(
                variants=getattr(args, "variants", None),
                force=bool(getattr(args, "force", False)),
                push=not bool(getattr(args, "no_push", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif action == "sync":
            from ronin.cli.resume_ops import sync_resume_texts

            rc = sync_resume_texts(dry_run=bool(getattr(args, "dry_run", False)))
            if rc != 0:
                sys.exit(rc)
        elif action == "debug":
            rc = resume_debug(url=str(getattr(args, "url", "")))
            if rc != 0:
                sys.exit(rc)
        else:
            parser.parse_args(["resume", "--help"])
            return

    elif args.command == "feedback":
        from ronin.cli.feedback import (
            review_manual_matches,
            show_feedback_report,
            sync_gmail_outcomes,
        )

        if args.feedback_action == "sync":
            rc = sync_gmail_outcomes(
                max_messages=getattr(args, "max_messages", 250),
                dry_run=bool(getattr(args, "dry_run", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif args.feedback_action == "report":
            rc = show_feedback_report(
                min_samples=getattr(args, "min_samples", 2),
            )
            if rc != 0:
                sys.exit(rc)
        elif args.feedback_action == "review":
            rc = review_manual_matches(
                limit=int(getattr(args, "limit", 25) or 25),
                auto_resolve=bool(getattr(args, "auto", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif args.feedback_action == "ignore":
            from ronin.cli.feedback import add_sender_ignore, list_sender_ignores

            ignore_action = getattr(args, "ignore_action", None)
            if ignore_action == "add":
                rc = add_sender_ignore(
                    sender_domain=str(getattr(args, "domain", "")),
                    sender_address=str(getattr(args, "address", "")),
                    reason=str(getattr(args, "reason", "")),
                )
                if rc != 0:
                    sys.exit(rc)
            elif ignore_action == "list":
                rc = list_sender_ignores(limit=int(getattr(args, "limit", 200)))
                if rc != 0:
                    sys.exit(rc)
            else:
                parser.parse_args(["feedback", "ignore", "--help"])
                return
        else:
            parser.parse_args(["feedback", "--help"])
            return

    elif args.command == "worker":
        from rich.console import Console

        from ronin.worker import (
            poll_and_process_gmail,
            run_weekly_drift,
            run_worker_once,
            run_worker_scheduler,
        )

        console = Console(stderr=True)
        action = getattr(args, "worker_action", None)
        if action == "start":
            console.print("[bold blue]Starting worker scheduler...[/bold blue]")
            try:
                run_worker_scheduler()
            except Exception as exc:
                console.print(f"[red]Worker start failed:[/red] {exc}")
                sys.exit(1)
        elif action == "once":
            console.print("[bold blue]Running one worker cycle...[/bold blue]")
            try:
                result = run_worker_once()
                console.print(result)
            except Exception as exc:
                console.print(f"[red]Worker run failed:[/red] {exc}")
                sys.exit(1)
        elif action == "gmail":
            console.print("[bold blue]Running Gmail worker cycle...[/bold blue]")
            try:
                result = poll_and_process_gmail()
                console.print(result)
            except Exception as exc:
                console.print(f"[red]Worker run failed:[/red] {exc}")
                sys.exit(1)
        elif action == "drift":
            console.print("[bold blue]Running drift worker cycle...[/bold blue]")
            try:
                result = run_weekly_drift()
                console.print(result)
            except Exception as exc:
                console.print(f"[red]Worker run failed:[/red] {exc}")
                sys.exit(1)
        else:
            parser.parse_args(["worker", "--help"])
            return

    elif args.command == "status":
        from ronin.cli.status import show_status

        show_status()

    elif args.command == "telegram":
        from ronin.cli.telegram_ops import run_bot, send_status_update

        action = getattr(args, "telegram_action", None)
        if action == "bot":
            rc = run_bot(
                token=str(getattr(args, "token", "") or ""),
                chat_id=str(getattr(args, "chat_id", "") or ""),
                poll_timeout=int(getattr(args, "poll_timeout", 45) or 45),
                once=bool(getattr(args, "once", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif action == "send-status":
            rc = send_status_update(
                token=str(getattr(args, "token", "") or ""),
                chat_id=str(getattr(args, "chat_id", "") or ""),
                with_concerns=not bool(getattr(args, "no_concerns", False)),
            )
            if rc != 0:
                sys.exit(rc)
        else:
            parser.parse_args(["telegram", "--help"])
            return

    elif args.command == "config":
        if args.config_action == "set":
            from rich.console import Console

            from ronin.cli.config_cmd import set_config_key

            console = Console(stderr=True)
            path = set_config_key(args.key, args.value)
            console.print(f"[green]Updated[/green] {path}")
        else:
            parser.parse_args(["config", "--help"])
            return

    elif args.command == "schedule":
        _handle_schedule(args, parser)

    elif args.command == "db":
        from ronin.cli.db_cmd import backup_db, migrate_db

        action = getattr(args, "db_action", None)
        if action == "backup":
            rc = backup_db(
                output_dir=getattr(args, "output_dir", None),
                include_spool=not bool(getattr(args, "no_spool", False)),
            )
            if rc != 0:
                sys.exit(rc)
        elif action == "migrate":
            rc = migrate_db(
                only=str(getattr(args, "only", "all")),
                limit=int(getattr(args, "limit", 0) or 0),
                dry_run=bool(getattr(args, "dry_run", False)),
                enable_embeddings=bool(getattr(args, "enable_embeddings", False)),
            )
            if rc != 0:
                sys.exit(rc)
        else:
            parser.parse_args(["db", "--help"])
            return


def _handle_schedule(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Dispatch schedule sub-actions.

    Args:
        args: Parsed CLI arguments.
        parser: Root parser (used to print help on missing sub-action).
    """
    from rich.console import Console

    from ronin.scheduler import (
        get_schedule_status,
        install_schedule,
        uninstall_schedule,
    )

    console = Console(stderr=True)

    if args.schedule_action is None:
        parser.parse_args(["schedule", "--help"])
        return

    if args.schedule_action == "install":
        interval: int = args.interval
        command: str = getattr(args, "scheduled_command", "search")
        at_time: str | None = getattr(args, "at", None)
        weekdays_only: bool = bool(getattr(args, "weekdays", False))
        console.print(
            (
                f"[bold blue]Installing schedule: ronin {command} at {at_time}...[/bold blue]"
                if at_time
                else f"[bold blue]Installing schedule: ronin {command} (every {interval}h)...[/bold blue]"
            )
        )
        if install_schedule(
            interval_hours=interval,
            command=command,
            at_time=at_time,
            weekdays_only=weekdays_only,
        ):
            console.print("[green]Schedule installed successfully[/green]")
        else:
            console.print("[red]Failed to install schedule[/red]")
            sys.exit(1)

    elif args.schedule_action == "uninstall":
        command: str = getattr(args, "scheduled_command", "search")
        console.print("[bold blue]Removing scheduled search...[/bold blue]")
        if uninstall_schedule(command=command):
            console.print("[green]Schedule removed[/green]")
        else:
            console.print("[red]Failed to remove schedule[/red]")
            sys.exit(1)

    elif args.schedule_action == "status":
        command: str = getattr(args, "scheduled_command", "search")
        status = get_schedule_status(command=command)
        if status["installed"]:
            console.print(f"[green]Installed[/green] on {status['platform']}")
            console.print(f"  Interval: every {status['interval_hours']}h")
            if status.get("next_run"):
                console.print(f"  Next run: {status['next_run']}")
        else:
            console.print("[yellow]Not installed[/yellow]")


if __name__ == "__main__":
    main()
