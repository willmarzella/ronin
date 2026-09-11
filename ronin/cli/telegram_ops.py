"""Telegram bot and status push operations."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from loguru import logger
from rich.console import Console

from ronin.config import get_ronin_home, load_config, load_env
from ronin.db import get_db_manager

console = Console()
_daily_sent_cache: Dict[str, str] = {}


def _nested_get(data: Dict, path: List[str], default=None):
    node = data
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def _resolve_telegram_credentials(
    token: str,
    chat_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    load_env()
    config: Dict = {}
    try:
        config = load_config()
    except FileNotFoundError:
        # Containerized deployments can rely entirely on env/secrets without config.yaml.
        config = {}

    resolved_token = (
        str(token or "").strip()
        or str(os.getenv("RONIN_TELEGRAM_BOT_TOKEN") or "").strip()
        or str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        or str(
            _nested_get(config, ["notifications", "telegram", "bot_token"], "")
        ).strip()
    )
    resolved_chat_id = (
        str(chat_id or "").strip()
        or str(os.getenv("RONIN_TELEGRAM_CHAT_ID") or "").strip()
        or str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        or str(
            _nested_get(config, ["notifications", "telegram", "chat_id"], "")
        ).strip()
        or str(
            _nested_get(config, ["notifications", "telegram", "allowed_chat_id"], "")
        ).strip()
    )
    return (
        resolved_token if resolved_token else None,
        resolved_chat_id if resolved_chat_id else None,
    )


class TelegramClient:
    """Small Telegram Bot API client using long polling."""

    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = requests.Session()

    def get_updates(self, offset: int, timeout: int = 45) -> List[Dict]:
        resp = self.session.get(
            f"{self.base_url}/getUpdates",
            params={
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message"],
            },
            timeout=max(30, timeout + 15),
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram getUpdates error: {payload}")
        return payload.get("result", [])

    def send_message(self, chat_id: str, text: str) -> None:
        resp = self.session.post(
            f"{self.base_url}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram sendMessage error: {payload}")


def _to_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _to_int(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_dt(value: object) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _window_bounds(days: int) -> Tuple[datetime, datetime]:
    now = datetime.now()
    start_date = (now - timedelta(days=max(1, int(days)) - 1)).date()
    start = datetime.combine(start_date, dt_time.min)
    end = datetime.combine(now.date() + timedelta(days=1), dt_time.min)
    return start, end


def _window_bounds_previous(days: int) -> Tuple[datetime, datetime]:
    current_start, _ = _window_bounds(days)
    previous_end = current_start
    previous_start = previous_end - timedelta(days=max(1, int(days)))
    return previous_start, previous_end


def _coerce_local_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _is_truthy(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}


def _parse_hhmm_or_default(
    raw: str,
    default_hour: int = 17,
    default_minute: int = 0,
) -> dt_time:
    text = str(raw or "").strip()
    if not text:
        return dt_time(hour=default_hour, minute=default_minute)

    parts = text.split(":")
    if len(parts) != 2:
        logger.warning(
            f"Invalid RONIN_TELEGRAM_DAILY_STATUS_TIME={text!r}; using 17:00."
        )
        return dt_time(hour=default_hour, minute=default_minute)

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except Exception:
        logger.warning(
            f"Invalid RONIN_TELEGRAM_DAILY_STATUS_TIME={text!r}; using 17:00."
        )
        return dt_time(hour=default_hour, minute=default_minute)

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        logger.warning(
            f"Out-of-range RONIN_TELEGRAM_DAILY_STATUS_TIME={text!r}; using 17:00."
        )
        return dt_time(hour=default_hour, minute=default_minute)

    return dt_time(hour=hour, minute=minute)


def _daily_status_state_path() -> Path:
    return get_ronin_home() / "state" / "telegram_daily_status.json"


def _read_daily_status_state() -> Dict[str, str]:
    path = _daily_status_state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        logger.warning(f"Failed reading Telegram daily state at {path}: {exc}")
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            f"Invalid Telegram daily state format at {path}; expected object."
        )
        return {}
    state: Dict[str, str] = {}
    for key, value in payload.items():
        state[str(key)] = str(value)
    return state


def _write_daily_status_state(state: Dict[str, str]) -> None:
    path = _daily_status_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp_path.replace(path)


def _last_daily_sent_for_chat(chat_id: str) -> str:
    if not chat_id:
        return ""
    chat_key = str(chat_id)
    cached = _daily_sent_cache.get(chat_key)
    if cached:
        return str(cached).strip()
    return str(_read_daily_status_state().get(chat_key, "")).strip()


def _mark_daily_sent_for_chat(chat_id: str, sent_date: str) -> None:
    if not chat_id:
        return
    chat_key = str(chat_id)
    _daily_sent_cache[chat_key] = str(sent_date)
    state = _read_daily_status_state()
    state[chat_key] = str(sent_date)
    _write_daily_status_state(state)


def _extract_row_value(row: object, key: str, index: int) -> object:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[index]
    except Exception:
        return None


def _collect_window_stats(start: datetime, end: datetime) -> Dict[str, int]:
    """Collect searched/queued/applied counts inside a datetime window."""
    db = get_db_manager()
    try:
        cursor = db.conn.cursor()
        start_iso = start.isoformat()
        start_date = start.date().isoformat()

        # New jobs discovered by search runs in this window.
        cursor.execute(
            (
                """
            SELECT created_at, status, quick_apply, market_intelligence_only
            FROM jobs
            WHERE created_at IS NOT NULL
              AND created_at >= %s
        """
                if "psycopg" in db.conn.__class__.__module__
                else """
            SELECT created_at, status, quick_apply, market_intelligence_only
            FROM jobs
            WHERE created_at IS NOT NULL
              AND created_at >= ?
        """
            ),
            (start_iso,),
        )
        searched = 0
        queued = 0
        for row in cursor.fetchall():
            created_raw = _extract_row_value(row, "created_at", 0)
            quick_apply = _to_int(_extract_row_value(row, "quick_apply", 2))
            market_intel = _to_int(
                _extract_row_value(row, "market_intelligence_only", 3)
            )

            created_dt = _coerce_local_naive(_safe_dt(created_raw))
            if not created_dt or created_dt < start or created_dt >= end:
                continue
            searched += 1
            if quick_apply == 1 and market_intel == 0:
                queued += 1

        # Application submissions in this window.
        cursor.execute(
            (
                """
            SELECT date_applied, applied_at
            FROM applications
            WHERE (date_applied IS NOT NULL AND date_applied >= %s)
               OR (applied_at IS NOT NULL AND applied_at >= %s)
        """
                if "psycopg" in db.conn.__class__.__module__
                else """
            SELECT date_applied, applied_at
            FROM applications
            WHERE (date_applied IS NOT NULL AND date_applied >= ?)
               OR (applied_at IS NOT NULL AND applied_at >= ?)
        """
            ),
            (start_date, start_iso),
        )
        applied = 0
        for row in cursor.fetchall():
            date_applied = _extract_row_value(row, "date_applied", 0)
            applied_at = _extract_row_value(row, "applied_at", 1)

            applied_dt = _coerce_local_naive(_safe_dt(applied_at))
            if not applied_dt and date_applied:
                applied_dt = _safe_dt(f"{date_applied}T00:00:00")
            if not applied_dt or applied_dt < start or applied_dt >= end:
                continue
            applied += 1

        return {"searched": searched, "queued": queued, "applied": applied}
    finally:
        db.close()


def _collect_pending_not_applied_breakdown() -> Dict[str, int]:
    """Explain why jobs are still pending instead of applied."""
    db = get_db_manager()
    try:
        cursor = db.conn.cursor()
        cursor.execute(
            """
            SELECT status, quick_apply, market_intelligence_only, selection_needs_review
            FROM jobs
            WHERE status IN ('DISCOVERED', 'APP_ERROR')
        """
        )

        breakdown = {
            "total_pending": 0,
            "manual_apply_required": 0,
            "market_intelligence_only": 0,
            "needs_review": 0,
            "application_error_retry": 0,
            "ready_queue": 0,
        }

        for row in cursor.fetchall():
            status = str(_extract_row_value(row, "status", 0) or "").strip().upper()
            quick_apply = _to_int(_extract_row_value(row, "quick_apply", 1))
            market_intel = _to_int(
                _extract_row_value(row, "market_intelligence_only", 2)
            )
            needs_review = _to_int(_extract_row_value(row, "selection_needs_review", 3))

            breakdown["total_pending"] += 1
            if status == "APP_ERROR":
                breakdown["application_error_retry"] += 1
            elif quick_apply != 1:
                breakdown["manual_apply_required"] += 1
            elif market_intel == 1:
                breakdown["market_intelligence_only"] += 1
            elif needs_review == 1:
                breakdown["needs_review"] += 1
            else:
                breakdown["ready_queue"] += 1

        return breakdown
    finally:
        db.close()


def _build_pending_insight_line(breakdown: Dict[str, int]) -> str:
    total_pending = _to_int(breakdown.get("total_pending"))
    ready_queue = _to_int(breakdown.get("ready_queue"))
    needs_review = _to_int(breakdown.get("needs_review"))
    market_intel = _to_int(breakdown.get("market_intelligence_only"))
    manual_apply = _to_int(breakdown.get("manual_apply_required"))
    app_error = _to_int(breakdown.get("application_error_retry"))

    if total_pending == 0:
        return "No jobs are waiting for apply right now."
    if ready_queue > 0:
        return f"{ready_queue} job(s) are ready in auto-apply queue now."
    if needs_review > 0:
        return "Some jobs need review before they can be applied."
    if market_intel == total_pending:
        return "All pending jobs are market-intel-only (tracked, not auto-applied)."
    if manual_apply == total_pending:
        return "All pending jobs require manual apply (not quick-apply)."
    if app_error > 0:
        return "There are failed application attempts waiting for retry."
    return "Pending jobs are split across queue gates."


def _format_pending_reasons_compact(breakdown: Dict[str, int]) -> str:
    labels = [
        ("market_intelligence_only", "market-intel hold"),
        ("manual_apply_required", "manual only"),
        ("needs_review", "needs review"),
        ("application_error_retry", "retry"),
        ("ready_queue", "ready"),
    ]
    parts: List[str] = []
    for key, label in labels:
        count = _to_int(breakdown.get(key))
        if count > 0:
            parts.append(f"{count} {label}")
    return ", ".join(parts) if parts else "none"


def _build_concerns_summary_line(snapshot: Dict) -> str:
    queue = snapshot.get("queue_summary", {})
    funnel = snapshot.get("funnel_metrics", {}).get("overview", {})
    alerts = snapshot.get("alerts", [])

    auto_queue = sum(
        _to_int((queue.get(key) or {}).get("count"))
        for key in ["builder", "fixer", "operator", "translator"]
    )
    market_intel = _to_int((queue.get("market_intel") or {}).get("count"))
    queue_total = auto_queue + market_intel

    notes: List[str] = []
    if alerts:
        notes.append(f"{len(alerts)} drift alert(s)")
    if auto_queue == 0:
        notes.append("auto-apply queue empty")
    if queue_total >= 5 and market_intel / max(1, queue_total) >= 0.7:
        notes.append("most pending jobs are intel-hold")

    total_applied = _to_int(funnel.get("total_applied"))
    responses = _to_int(funnel.get("any_response"))
    interviews = _to_int(funnel.get("interviews"))
    if total_applied >= 15 and interviews == 0:
        notes.append("no interviews with 15+ applications")
    if total_applied >= 20 and responses == 0:
        notes.append("no responses with 20+ applications")

    if not notes:
        return "- Risk: no critical concerns"
    return "- Risk: " + " | ".join(notes[:3])


def _collect_snapshot() -> Dict:
    db = get_db_manager()
    try:
        jobs_stats = db.get_jobs_stats()
        queue_summary = db.get_queue_summary()
        outcome_stats = db.get_application_outcome_stats()
        funnel_metrics = db.get_funnel_metrics()
        alerts = db.get_unacknowledged_alerts()

        cursor = db.conn.cursor()
        cursor.execute("SELECT MAX(created_at) AS value FROM jobs")
        last_job = cursor.fetchone()
        cursor.execute(
            """
            SELECT MAX(COALESCE(applied_at, date_applied, created_at)) AS value
            FROM applications
        """
        )
        last_apply = cursor.fetchone()

        return {
            "jobs_stats": jobs_stats,
            "queue_summary": queue_summary,
            "outcome_stats": outcome_stats,
            "funnel_metrics": funnel_metrics,
            "alerts": alerts,
            "last_job_at": _extract_row_value(last_job, "value", 0),
            "last_apply_at": _extract_row_value(last_apply, "value", 0),
        }
    finally:
        db.close()


def _format_delta(current: int, previous: int) -> str:
    delta = current - previous
    if previous <= 0:
        return f"{delta:+d} (baseline n/a)"
    pct = (delta / previous) * 100.0
    return f"{delta:+d} ({pct:+.1f}%)"


def _build_weekly_message() -> str:
    current_start, current_end = _window_bounds(7)
    previous_start, previous_end = _window_bounds_previous(7)
    current = _collect_window_stats(current_start, current_end)
    previous = _collect_window_stats(previous_start, previous_end)

    return "\n".join(
        [
            f"Weekly Roundup ({current_start.date().isoformat()} to {(current_end.date() - timedelta(days=1)).isoformat()})",
            f"- searched/new: {current['searched']} ({_format_delta(current['searched'], previous['searched'])} vs prior week)",
            f"- queued: {current['queued']} ({_format_delta(current['queued'], previous['queued'])} vs prior week)",
            f"- applied: {current['applied']} ({_format_delta(current['applied'], previous['applied'])} vs prior week)",
            (
                "Queue conversion: "
                f"{(current['applied'] / current['queued'] * 100.0):.1f}%"
                if current["queued"] > 0
                else "Queue conversion: n/a (no queued jobs)"
            ),
        ]
    )


def _build_status_message(snapshot: Dict) -> str:
    jobs = snapshot.get("jobs_stats", {})
    queue = snapshot.get("queue_summary", {})
    outcome = snapshot.get("outcome_stats", {})
    funnel = snapshot.get("funnel_metrics", {}).get("overview", {})
    alerts = snapshot.get("alerts", [])

    by_status = jobs.get("by_status", {})
    total_jobs = _to_int(jobs.get("total_jobs"))
    discovered = _to_int(by_status.get("DISCOVERED"))
    applied_jobs = _to_int(by_status.get("APPLIED"))
    app_error = _to_int(by_status.get("APP_ERROR"))

    auto_queue = sum(
        _to_int((queue.get(key) or {}).get("count"))
        for key in ["builder", "fixer", "operator", "translator"]
    )
    market_intel = _to_int((queue.get("market_intel") or {}).get("count"))

    total_applied = _to_int(funnel.get("total_applied"))
    responses = _to_int(funnel.get("any_response"))
    interviews = _to_int(funnel.get("interviews"))
    response_rate = (responses / total_applied * 100.0) if total_applied else 0.0
    interview_rate = (interviews / total_applied * 100.0) if total_applied else 0.0

    tracked = _to_int(outcome.get("total"))
    resolved = _to_int(outcome.get("resolved"))
    positive_rate = _to_float(outcome.get("conversion_rate")) * 100.0
    pending = _collect_pending_not_applied_breakdown()
    pending_total = _to_int(pending.get("total_pending"))
    pending_reasons = _format_pending_reasons_compact(pending)

    today_start, today_end = _window_bounds(1)
    week_start, week_end = _window_bounds(7)
    today_stats = _collect_window_stats(today_start, today_end)
    week_stats = _collect_window_stats(week_start, week_end)

    lines = [
        f"Ronin check-in ({today_start.date().isoformat()})",
        (
            "- Today: "
            f"{today_stats['searched']} new | "
            f"{today_stats['queued']} queued | "
            f"{today_stats['applied']} applied"
        ),
        (
            "- 7d pace: "
            f"{week_stats['searched']} new | "
            f"{week_stats['queued']} queued | "
            f"{week_stats['applied']} applied"
        ),
        f"- Pending: {pending_total} ({pending_reasons})",
        f"- Queue now: {auto_queue} auto | {market_intel} intel-hold",
        (
            "- Outcomes: "
            f"{total_applied} apps | "
            f"{response_rate:.1f}% response | "
            f"{interview_rate:.1f}% interview"
        ),
        (
            "- Inventory: "
            f"{total_jobs} tracked | "
            f"{discovered} discovered | "
            f"{applied_jobs} applied | "
            f"{app_error} app_error"
        ),
    ]
    if tracked > 0:
        lines.append(
            f"- Feedback: {resolved}/{tracked} resolved | {positive_rate:.1f}% positive"
        )
    if alerts:
        lines.append(f"- Alerts: {len(alerts)} open")
    lines.append(f"- Assistant note: {_build_pending_insight_line(pending)}")
    lines.append(
        "- Positioning: "
        f"{_positioning_statement(total_applied, response_rate, interview_rate)}"
    )
    return "\n".join(lines)


def _build_end_of_day_message(snapshot: Dict) -> str:
    today_start, _ = _window_bounds(1)
    status_lines = _build_status_message(snapshot).splitlines()
    if status_lines:
        status_lines[0] = f"End-of-day check-in ({today_start.date().isoformat()})"
    status_lines.append(_build_concerns_summary_line(snapshot))
    return "\n".join(status_lines)


def _maybe_send_daily_status_update(
    client: TelegramClient,
    chat_id: str,
    schedule_time: dt_time,
    now: Optional[datetime] = None,
) -> bool:
    target_chat_id = str(chat_id or "").strip()
    if not target_chat_id:
        return False

    current = now or datetime.now()
    send_after = datetime.combine(current.date(), schedule_time)
    if current < send_after:
        return False

    today = current.date().isoformat()
    if _last_daily_sent_for_chat(target_chat_id) == today:
        return False

    snapshot = _collect_snapshot()
    text = _build_end_of_day_message(snapshot)
    client.send_message(target_chat_id, text[:4000])
    _mark_daily_sent_for_chat(target_chat_id, today)
    logger.info(f"Daily Telegram status sent to chat_id={target_chat_id} for {today}.")
    return True


def _positioning_statement(
    total_applied: int,
    response_rate: float,
    interview_rate: float,
) -> str:
    if total_applied < 10:
        return "insufficient data (need at least 10 applications)."
    if interview_rate >= 10 and response_rate >= 25:
        return "strong for current market."
    if interview_rate >= 5 and response_rate >= 15:
        return "reasonable, but can be improved."
    return "weak; resume positioning likely needs revision."


def _build_concerns_message(snapshot: Dict) -> str:
    queue = snapshot.get("queue_summary", {})
    funnel = snapshot.get("funnel_metrics", {}).get("overview", {})
    alerts = snapshot.get("alerts", [])

    concerns: List[str] = []

    auto_queue = sum(
        _to_int((queue.get(key) or {}).get("count"))
        for key in ["builder", "fixer", "operator", "translator"]
    )
    market_intel = _to_int((queue.get("market_intel") or {}).get("count"))
    queue_total = auto_queue + market_intel

    if alerts:
        concerns.append(f"{len(alerts)} drift alerts are unacknowledged.")
        for row in alerts[:3]:
            concerns.append(
                "- "
                f"{str(row.get('alert_type') or 'unknown')} "
                f"({str(row.get('archetype') or 'unknown')}): "
                f"{_to_float(row.get('metric_value')):.4f} vs {_to_float(row.get('threshold_value')):.4f}"
            )

    if auto_queue == 0:
        concerns.append("Auto-apply queue is empty.")
    if queue_total >= 5 and market_intel / max(1, queue_total) >= 0.7:
        concerns.append(
            "Most discovered jobs are market-intel-only; targeting may be too narrow."
        )

    total_applied = _to_int(funnel.get("total_applied"))
    responses = _to_int(funnel.get("any_response"))
    interviews = _to_int(funnel.get("interviews"))
    if total_applied >= 15 and interviews == 0:
        concerns.append("No interviews despite 15+ applications.")
    if total_applied >= 20 and responses == 0:
        concerns.append("No responses despite 20+ applications.")

    if not concerns:
        return "No critical concerns right now."

    return "Concerns:\n" + "\n".join(concerns)


def _build_alerts_message(snapshot: Dict) -> str:
    alerts = snapshot.get("alerts", [])
    if not alerts:
        return "No active alerts."
    lines = ["Active Drift Alerts:"]
    for row in alerts[:20]:
        lines.append(
            f"- #{_to_int(row.get('id'))} "
            f"{str(row.get('archetype') or 'unknown')} "
            f"{str(row.get('alert_type') or 'unknown')} "
            f"{_to_float(row.get('metric_value')):.4f}/{_to_float(row.get('threshold_value')):.4f}"
        )
    return "\n".join(lines)


def _ack_alert(alert_id: int) -> bool:
    db = get_db_manager()
    try:
        return bool(db.acknowledge_alert(int(alert_id)))
    finally:
        db.close()


def _run_drift_now() -> Dict:
    from ronin.feedback.drift import run_weekly_drift_jobs

    db = get_db_manager()
    try:
        return run_weekly_drift_jobs(db_manager=db)
    finally:
        db.close()


def _handle_command(text: str) -> str:
    cmd = (text or "").strip()
    if not cmd:
        return "Empty command. Try /help."

    if cmd.startswith("/start") or cmd.startswith("/help"):
        return (
            "Commands:\n"
            "/status - snapshot\n"
            "/weekly - 7-day roundup (with week-over-week deltas)\n"
            "/concerns - risk summary\n"
            "/alerts - list drift alerts\n"
            "/ack <id> - acknowledge alert\n"
            "/drift - run drift checks now\n"
            "/ping - health check"
        )

    if cmd.startswith("/ping"):
        return "pong"

    if cmd.startswith("/status"):
        return _build_status_message(_collect_snapshot())

    if cmd.startswith("/weekly"):
        return _build_weekly_message()

    if cmd.startswith("/concerns"):
        return _build_concerns_message(_collect_snapshot())

    if cmd.startswith("/alerts"):
        return _build_alerts_message(_collect_snapshot())

    if cmd.startswith("/ack"):
        parts = cmd.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return "Usage: /ack <alert_id>"
        ok = _ack_alert(int(parts[1]))
        return "Alert acknowledged." if ok else "Alert not found."

    if cmd.startswith("/drift"):
        result = _run_drift_now()
        return (
            "Drift checks complete:\n"
            f"- centroids_computed: {result.get('centroids', {}).get('computed', 0)}\n"
            f"- market_shift_alerts: {len(result.get('market_shift_alerts', []))}\n"
            f"- resume_stale_alerts: {len(result.get('resume_stale_alerts', []))}\n"
            f"- rewrite_triggers: {len(result.get('rewrite_triggers', []))}"
        )

    return "Unknown command. Try /help."


def send_status_update(
    token: str = "",
    chat_id: str = "",
    with_concerns: bool = True,
) -> int:
    """Send current status snapshot to the configured Telegram chat."""
    resolved_token, resolved_chat_id = _resolve_telegram_credentials(token, chat_id)
    if not resolved_token:
        console.print(
            "[red]Missing Telegram token.[/red] "
            "Set --token, RONIN_TELEGRAM_BOT_TOKEN, or notifications.telegram.bot_token."
        )
        return 1
    if not resolved_chat_id:
        console.print(
            "[red]Missing Telegram chat id.[/red] "
            "Set --chat-id, RONIN_TELEGRAM_CHAT_ID, or notifications.telegram.chat_id."
        )
        return 1

    client = TelegramClient(resolved_token)
    snapshot = _collect_snapshot()
    text = _build_status_message(snapshot)
    if with_concerns:
        text = f"{text}\n\n{_build_concerns_message(snapshot)}"
    client.send_message(resolved_chat_id, text)
    console.print("[green]Telegram status sent.[/green]")
    return 0


def run_bot(
    token: str = "",
    chat_id: str = "",
    poll_timeout: int = 45,
    once: bool = False,
) -> int:
    """Run Telegram long-poll bot for Ronin status and drift controls."""
    resolved_token, allowed_chat_id = _resolve_telegram_credentials(token, chat_id)
    if not resolved_token:
        console.print(
            "[red]Missing Telegram token.[/red] "
            "Set --token, RONIN_TELEGRAM_BOT_TOKEN, or notifications.telegram.bot_token."
        )
        return 1

    client = TelegramClient(resolved_token)
    offset = 0
    console.print("[green]Telegram bot started.[/green] Ctrl+C to stop.")
    if allowed_chat_id:
        console.print(f"[dim]Allowed chat id: {allowed_chat_id}[/dim]")

    daily_status_enabled = _is_truthy(
        os.getenv("RONIN_TELEGRAM_DAILY_STATUS_ENABLED"),
        default=True,
    )
    daily_status_time = _parse_hhmm_or_default(
        str(os.getenv("RONIN_TELEGRAM_DAILY_STATUS_TIME") or "17:00")
    )
    if daily_status_enabled and not once:
        if allowed_chat_id:
            console.print(
                "[dim]Daily status auto-send: "
                f"{daily_status_time.strftime('%H:%M')} local time[/dim]"
            )
        else:
            logger.warning(
                "Daily Telegram status enabled but no chat_id is configured; "
                "scheduled sends will be skipped."
            )

    try:
        while True:
            if daily_status_enabled and allowed_chat_id and not once:
                try:
                    _maybe_send_daily_status_update(
                        client=client,
                        chat_id=str(allowed_chat_id),
                        schedule_time=daily_status_time,
                    )
                except Exception as exc:
                    logger.warning(f"Daily Telegram status send failed: {exc}")

            updates = client.get_updates(
                offset=offset, timeout=max(5, int(poll_timeout))
            )
            if not updates:
                if once:
                    return 0
                continue

            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                incoming_chat_id = str(chat.get("id", "")).strip()
                text = str(message.get("text", "") or "").strip()
                if not text:
                    continue

                if allowed_chat_id and incoming_chat_id != str(allowed_chat_id):
                    logger.warning(
                        "Ignoring Telegram message from unauthorized chat_id="
                        f"{incoming_chat_id}"
                    )
                    continue

                try:
                    reply = _handle_command(text)
                except Exception as exc:
                    logger.exception(f"Telegram command failed: {exc}")
                    reply = f"Command failed: {exc}"
                client.send_message(incoming_chat_id, reply[:4000])

            if once:
                return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Telegram bot stopped.[/yellow]")
        return 0
    except requests.RequestException as exc:
        console.print(f"[red]Telegram network error:[/red] {exc}")
        time.sleep(2)
        return 1
    except Exception as exc:
        console.print(f"[red]Telegram bot error:[/red] {exc}")
        return 1
