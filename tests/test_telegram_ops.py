"""Regression tests for Telegram status operations."""

from __future__ import annotations

import json
from datetime import datetime
from datetime import time as dt_time

from ronin.cli import telegram_ops


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.sent = []

    def send_message(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


class _FakeCursor:
    def __init__(self, rows) -> None:
        self._rows = rows

    def execute(self, _query: str) -> None:
        return None

    def fetchall(self):
        return self._rows


class _FakeDbManager:
    def __init__(self, rows) -> None:
        self._rows = rows
        self.conn = self

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows)

    def close(self) -> None:
        return None


def test_status_message_includes_apply_blockers(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_ops,
        "_collect_window_stats",
        lambda _start, _end: {"searched": 4, "queued": 2, "applied": 1},
    )
    monkeypatch.setattr(
        telegram_ops,
        "_collect_pending_not_applied_breakdown",
        lambda: {
            "total_pending": 5,
            "manual_apply_required": 1,
            "market_intelligence_only": 2,
            "needs_review": 1,
            "application_error_retry": 0,
            "ready_queue": 1,
        },
    )

    snapshot = {
        "jobs_stats": {
            "total_jobs": 20,
            "by_status": {"DISCOVERED": 5, "APPLIED": 14, "APP_ERROR": 1},
        },
        "queue_summary": {
            "builder": {"count": 1},
            "fixer": {"count": 0},
            "operator": {"count": 0},
            "translator": {"count": 0},
            "market_intel": {"count": 2},
        },
        "outcome_stats": {"total": 7, "resolved": 4, "conversion_rate": 0.5},
        "funnel_metrics": {
            "overview": {"total_applied": 14, "any_response": 3, "interviews": 1}
        },
        "alerts": [],
        "last_job_at": "2026-03-02T14:00:00",
        "last_apply_at": "2026-03-02T15:00:00",
    }

    message = telegram_ops._build_status_message(snapshot)

    assert "Ronin check-in" in message
    assert (
        "- Pending: 5 (2 market-intel hold, 1 manual only, 1 needs review, 1 ready)"
        in message
    )
    assert "- Today: 4 new | 2 queued | 1 applied" in message
    assert "- Assistant note:" in message


def test_end_of_day_message_uses_brief_risk_line(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_ops,
        "_build_status_message",
        lambda _snapshot: "Ronin check-in (2026-03-02)\n- Pending: 2 (2 market-intel hold)",
    )

    snapshot = {
        "queue_summary": {
            "builder": {"count": 0},
            "fixer": {"count": 0},
            "operator": {"count": 0},
            "translator": {"count": 0},
            "market_intel": {"count": 2},
        },
        "funnel_metrics": {
            "overview": {"total_applied": 25, "any_response": 0, "interviews": 0}
        },
        "alerts": [{"id": 1}],
    }

    message = telegram_ops._build_end_of_day_message(snapshot)

    assert "End-of-day check-in" in message
    assert "- Risk:" in message
    assert "Concerns:" not in message


def test_daily_status_sends_once_per_day(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "telegram_daily_status.json"
    monkeypatch.setattr(telegram_ops, "_daily_status_state_path", lambda: state_path)
    monkeypatch.setattr(telegram_ops, "_collect_snapshot", lambda: {"ok": True})
    monkeypatch.setattr(telegram_ops, "_build_end_of_day_message", lambda _s: "daily")

    client = _FakeTelegramClient()
    sent_first = telegram_ops._maybe_send_daily_status_update(
        client=client,
        chat_id="123",
        schedule_time=dt_time(hour=17, minute=0),
        now=datetime(2026, 3, 2, 17, 5),
    )
    sent_second = telegram_ops._maybe_send_daily_status_update(
        client=client,
        chat_id="123",
        schedule_time=dt_time(hour=17, minute=0),
        now=datetime(2026, 3, 2, 20, 30),
    )

    assert sent_first is True
    assert sent_second is False
    assert client.sent == [("123", "daily")]
    saved = json.loads(state_path.read_text())
    assert saved["123"] == "2026-03-02"


def test_daily_status_does_not_send_before_trigger(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "telegram_daily_status.json"
    monkeypatch.setattr(telegram_ops, "_daily_status_state_path", lambda: state_path)
    monkeypatch.setattr(telegram_ops, "_collect_snapshot", lambda: {"ok": True})
    monkeypatch.setattr(telegram_ops, "_build_end_of_day_message", lambda _s: "daily")

    client = _FakeTelegramClient()
    sent = telegram_ops._maybe_send_daily_status_update(
        client=client,
        chat_id="123",
        schedule_time=dt_time(hour=17, minute=0),
        now=datetime(2026, 3, 2, 16, 59),
    )

    assert sent is False
    assert client.sent == []
    assert not state_path.exists()


def test_daily_status_sends_at_threshold_next_day_and_per_chat(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "telegram_daily_status.json"
    monkeypatch.setattr(telegram_ops, "_daily_status_state_path", lambda: state_path)
    monkeypatch.setattr(telegram_ops, "_collect_snapshot", lambda: {"ok": True})
    monkeypatch.setattr(telegram_ops, "_build_end_of_day_message", lambda _s: "daily")

    client = _FakeTelegramClient()
    sent_a_day1 = telegram_ops._maybe_send_daily_status_update(
        client=client,
        chat_id="A",
        schedule_time=dt_time(hour=17, minute=0),
        now=datetime(2026, 3, 2, 17, 0),
    )
    sent_b_day1 = telegram_ops._maybe_send_daily_status_update(
        client=client,
        chat_id="B",
        schedule_time=dt_time(hour=17, minute=0),
        now=datetime(2026, 3, 2, 17, 0),
    )
    sent_a_day2 = telegram_ops._maybe_send_daily_status_update(
        client=client,
        chat_id="A",
        schedule_time=dt_time(hour=17, minute=0),
        now=datetime(2026, 3, 3, 17, 0),
    )

    assert sent_a_day1 is True
    assert sent_b_day1 is True
    assert sent_a_day2 is True
    assert client.sent == [("A", "daily"), ("B", "daily"), ("A", "daily")]


def test_pending_breakdown_prioritizes_app_error(monkeypatch) -> None:
    rows = [
        ("APP_ERROR", 1, 1, 1),
        ("DISCOVERED", 1, 1, 0),
        ("DISCOVERED", 0, 0, 0),
        ("DISCOVERED", 1, 0, 1),
        ("DISCOVERED", 1, 0, 0),
    ]
    monkeypatch.setattr(
        telegram_ops,
        "get_db_manager",
        lambda: _FakeDbManager(rows),
    )

    breakdown = telegram_ops._collect_pending_not_applied_breakdown()

    assert breakdown["total_pending"] == 5
    assert breakdown["application_error_retry"] == 1
    assert breakdown["market_intelligence_only"] == 1
    assert breakdown["manual_apply_required"] == 1
    assert breakdown["needs_review"] == 1
    assert breakdown["ready_queue"] == 1
