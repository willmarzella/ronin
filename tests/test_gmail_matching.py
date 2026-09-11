#!/usr/bin/env python3
"""Regression checks for Gmail outcome classification + matching.

These tests do not call the Gmail API.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class FakeDb:
    def __init__(self, apps):
        self._apps = list(apps)
        self._known = {}

    # Methods used by GmailOutcomeTracker
    def get_application_by_seek_job_id(self, seek_job_id: str):
        for app in self._apps:
            if str(app.get("seek_job_id")) == str(seek_job_id):
                return app
        return None

    def lookup_known_sender(self, email_address: str):
        return self._known.get(email_address)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_outcome_classifier() -> None:
    from ronin.feedback.gmail_api_tracker import GmailOutcomeTracker

    tracker = GmailOutcomeTracker(db_manager=FakeDb([]))
    stage, conf = tracker._classify_outcome("Unfortunately we will not be progressing.")
    _assert(stage == "rejected", f"Expected rejected, got {stage}")
    _assert(conf > 0, "Expected confidence > 0")

    stage, _ = tracker._classify_outcome(
        "We would like to discuss your application. Are you available for a phone screen?"
    )
    _assert(stage == "interview_request", f"Expected interview_request, got {stage}")

    stage, _ = tracker._classify_outcome("Thanks for applying - application received.")
    _assert(stage == "acknowledged", f"Expected acknowledged, got {stage}")


def test_outcome_fixtures() -> None:
    from ronin.feedback.gmail_api_tracker import GmailOutcomeTracker

    tracker = GmailOutcomeTracker(db_manager=FakeDb([]))
    fixture_path = Path(__file__).parent / "fixtures" / "outcome_emails.jsonl"
    rows = fixture_path.read_text(encoding="utf-8").splitlines()
    _assert(rows, "Fixture file is empty")

    for line in rows:
        payload = json.loads(line)
        name = payload.get("name")
        expected = payload.get("expected")
        body = payload.get("body_text")
        stage, _ = tracker._classify_outcome(body)
        _assert(
            stage == expected,
            f"Fixture {name}: expected {expected}, got {stage}",
        )


def test_seek_job_id_matching() -> None:
    from ronin.feedback.gmail_api_tracker import GmailOutcomeTracker

    apps = [
        {
            "id": 1,
            "seek_job_id": "12345",
            "company_name": "Seek",
            "job_title": "Data Engineer",
        }
    ]
    tracker = GmailOutcomeTracker(db_manager=FakeDb(apps))
    parsed = {
        "source_type": "seek",
        "body_text": "Your application update https://www.seek.com.au/job/12345",
        "body_html": "",
        "raw_urls": ["https://www.seek.com.au/job/12345"],
        "sender_address": "noreply@seek.com.au",
        "sender_domain": "seek.com.au",
        "subject": "Update",
        "date_received": "2026-02-17T00:00:00+00:00",
    }
    match = tracker._match_email_to_application(parsed, apps)
    _assert(
        match.status == "auto_matched", f"Expected auto_matched, got {match.status}"
    )
    _assert(match.method == "seek_job_id", f"Expected seek_job_id, got {match.method}")
    _assert(match.application and match.application.get("id") == 1, "Wrong application")


def test_domain_title_matching() -> None:
    from ronin.feedback.gmail_api_tracker import GmailOutcomeTracker

    apps = [
        {
            "id": 10,
            "seek_job_id": "999",
            "company_name": "Woolworths Group",
            "job_title": "Senior Data Engineer",
            "tech_stack_tags": '["snowflake", "dbt"]',
            "date_applied": "2026-02-01",
        }
    ]
    tracker = GmailOutcomeTracker(db_manager=FakeDb(apps))
    parsed = {
        "source_type": "direct",
        "sender_address": "jane@woolworths.com.au",
        "sender_domain": "woolworths.com.au",
        "subject": "Senior Data Engineer application",
        "body_text": "Hi, about your Data Engineer application (Snowflake/dbt)...",
        "date_received": "2026-02-05T00:00:00+00:00",
    }
    match = tracker._match_email_to_application(parsed, apps)
    _assert(match.status in {"auto_matched", "manual_review"}, "Unexpected status")
    _assert(match.candidates, "Expected candidates")
    if match.status == "auto_matched":
        _assert(match.application and match.application.get("id") == 10, "Wrong app")


def main() -> int:
    try:
        test_outcome_classifier()
        test_outcome_fixtures()
        test_seek_job_id_matching()
        test_domain_title_matching()
        print("PASS: gmail matching")
        return 0
    except Exception as exc:
        print(f"FAIL: gmail matching -- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
