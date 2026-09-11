"""Local Flask intake form for logging phone call outcomes."""

from __future__ import annotations

import threading
import webbrowser
from datetime import date
from typing import Optional

from flask import Flask, redirect, render_template_string, request

from ronin.db import get_db_manager
from ronin.feedback.gmail_api_tracker import GmailOutcomeTracker

CALL_FORM_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Ronin Call Intake</title>
    <style>
      body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; margin: 24px; }
      form { max-width: 720px; display: grid; gap: 12px; }
      input, select, textarea { width: 100%; padding: 8px; font-size: 14px; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      button { width: 180px; padding: 10px 14px; background: #0f766e; color: white; border: 0; border-radius: 6px; }
      .hint { color: #4b5563; font-size: 13px; }
      .ok { color: #065f46; font-weight: 600; }
    </style>
  </head>
  <body>
    <h1>Phone Call Log</h1>
    {% if success %}
      <p class="ok">Saved successfully.</p>
    {% endif %}
    <form method="post" action="/log-call">
      <div class="row">
        <label>Phone Number
          <input name="phone" type="text" placeholder="Optional" />
        </label>
        <label>Date
          <input name="date" type="date" value="{{ default_date }}" required />
        </label>
      </div>
      <div class="row">
        <label>Company Name
          <input name="company" type="text" required />
        </label>
        <label>Job Title
          <input name="title" type="text" required />
        </label>
      </div>
      <label>Outcome
        <select name="outcome" required>
          <option value="screening_call">screening_call</option>
          <option value="interview">interview</option>
          <option value="rejection">rejection</option>
          <option value="other">other</option>
        </select>
      </label>
      <label>Notes
        <textarea name="notes" rows="4" placeholder="Optional context"></textarea>
      </label>
      <button type="submit">Save Call</button>
      <p class="hint">Calls are matched against recent applications using the same cascade as email matching.</p>
    </form>
  </body>
</html>
"""


def create_phone_intake_app(db_manager: Optional[object] = None) -> Flask:
    """Create Flask app for call intake logging endpoint."""
    app = Flask(__name__)
    manager = db_manager or get_db_manager()
    matcher = GmailOutcomeTracker(db_manager=manager)

    @app.route("/log-call", methods=["GET", "POST"])
    def log_call():
        if request.method == "POST":
            company = request.form.get("company", "").strip()
            title = request.form.get("title", "").strip()
            outcome = request.form.get("outcome", "other").strip()
            call_date = request.form.get("date", date.today().isoformat()).strip()
            notes = request.form.get("notes", "").strip()
            phone = request.form.get("phone", "").strip()

            applications = manager.get_recent_applications_for_matching(days=180)
            pseudo_email = {
                "source_type": "direct",
                "sender_address": "",
                "sender_domain": "",
                "subject": f"{company} {title}",
                "body_text": f"{company} {title} {notes}",
                "body_html": "",
                "raw_urls": [],
                "date_received": f"{call_date}T12:00:00+00:00",
            }
            match = matcher._match_email_to_application(  # noqa: SLF001
                pseudo_email,
                applications,
            )

            matched_id = match.application.get("id") if match.application else None
            manager.record_phone_call(
                phone_number=phone or None,
                company_name=company,
                job_title=title,
                outcome=outcome,
                notes=notes,
                call_date=call_date,
                matched_application_id=matched_id,
            )
            return redirect("/log-call?success=1")

        success = request.args.get("success") == "1"
        return render_template_string(
            CALL_FORM_HTML,
            success=success,
            default_date=date.today().isoformat(),
        )

    return app


def run_phone_call_intake(
    host: str = "127.0.0.1",
    port: int = 5001,
    open_browser: bool = True,
) -> None:
    """Start local call intake web form server."""
    app = create_phone_intake_app()
    url = f"http://{host}:{port}/log-call"

    if open_browser:
        timer = threading.Timer(0.5, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()

    app.run(host=host, port=port, debug=False)
