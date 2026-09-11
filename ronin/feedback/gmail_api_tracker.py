"""Gmail API poller, parser, classifier, and application matcher."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from ronin.config import get_ronin_home

try:
    from difflib import SequenceMatcher
except Exception:  # pragma: no cover
    SequenceMatcher = None


OUTCOME_RULES = {
    "rejected": {
        "keywords": [
            "unfortunately",
            "other candidates",
            "not progressing",
            "position has been filled",
            "we will not be",
            "unsuccessful",
            "decided not to proceed",
            "not shortlisted",
            "gone with another",
        ],
        "min_matches": 1,
    },
    "interview_request": {
        "keywords": [
            "availability",
            "phone screen",
            "would like to discuss",
            "schedule",
            "interview",
            "meet with",
            "arrange a time",
            "chat about the role",
            "initial conversation",
            "when are you free",
        ],
        "min_matches": 1,
    },
    "viewed": {
        "keywords": [
            "your application was viewed",
            "has viewed your application",
            "viewed your profile",
            # Seek notification phrasing (often includes a job link)
            "reviewing applications",
            "new activity in jobs you applied for",
            "profile views",
            "your profile is being discovered",
        ],
        "min_matches": 1,
    },
    "acknowledged": {
        "keywords": [
            "application received",
            "thank you for applying",
            "we have received",
            "application submitted",
            # Common ATS / direct phrasing
            "your recent application",
            "your application to the",
            "your application for the",
        ],
        "min_matches": 1,
    },
}

OUTCOME_PRIORITY = ["interview_request", "rejected", "viewed", "acknowledged"]


@dataclass
class MatchResult:
    """Matching result for a parsed email/call event."""

    status: str
    application: Optional[Dict] = None
    candidates: Optional[List[Tuple[Dict, float]]] = None
    method: str = "unmatched"


class GmailOutcomeTracker:
    """Poll Gmail API and persist parsed outcome signals into the configured DB."""

    SYNC_STATE_KEY = "gmail_outcomes_last_sync"
    LAST_MESSAGE_KEY = "gmail_last_processed_message_id"
    DEFAULT_SCOPE = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(
        self,
        db_manager: object,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        query: str = "newer_than:1d",
        auth_mode: str = "auto",
    ) -> None:
        self.db_manager = db_manager
        self.query = query
        default_credentials = Path.cwd() / "credentials.json"
        default_token = get_ronin_home() / "gmail_token.json"
        self.credentials_path = Path(
            credentials_path or default_credentials
        ).expanduser()
        self.token_path = Path(token_path or default_token).expanduser()
        self.auth_mode = str(auth_mode or "auto")

    def sync(self, max_messages: int = 250, dry_run: bool = False) -> Dict[str, int]:
        """Poll Gmail and persist parsed/matched outcomes."""
        service = self._build_gmail_service()
        applications = self.db_manager.get_recent_applications_for_matching(days=180)

        stats = {
            "emails_scanned": 0,
            "outcome_emails": 0,
            "events_recorded": 0,
            "matched": 0,
            "manual_review": 0,
            "duplicates": 0,
            "ignored": 0,
        }

        response = (
            service.users()
            .messages()
            .list(userId="me", q=self.query, maxResults=max(1, int(max_messages)))
            .execute()
        )
        messages = response.get("messages", [])
        stats["emails_scanned"] = len(messages)
        last_processed_id = self.db_manager.get_sync_state(self.LAST_MESSAGE_KEY)
        newest_seen_id = messages[0].get("id") if messages else None

        for message_ref in messages:
            message_id = message_ref.get("id")
            if not message_id:
                continue
            if last_processed_id and message_id == last_processed_id:
                break

            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            parsed = self._parse_message(message)
            if not parsed:
                continue

            if self.db_manager.is_sender_ignored(
                parsed["sender_address"], parsed["sender_domain"]
            ):
                stats["ignored"] += 1
                continue

            parsed["source_type"] = self._classify_source_type(parsed)
            outcome, confidence = self._classify_outcome(parsed["body_text"])
            parsed["outcome_classification"] = outcome
            parsed["classification_confidence"] = confidence

            if outcome != "other":
                stats["outcome_emails"] += 1

            match = self._match_email_to_application(parsed, applications)
            parsed["matched_application_id"] = (
                match.application.get("id") if match.application else None
            )
            parsed["match_method"] = match.method
            parsed["requires_manual_review"] = int(match.status == "manual_review")

            if dry_run:
                stats["events_recorded"] += 1
                if match.status == "auto_matched" and match.application:
                    stats["matched"] += 1
                elif match.status == "manual_review":
                    stats["manual_review"] += 1
                continue

            inserted_id = self.db_manager.insert_parsed_email(parsed)
            if inserted_id is None:
                stats["duplicates"] += 1
                continue

            stats["events_recorded"] += 1

            if match.status == "auto_matched" and match.application:
                stats["matched"] += 1
                if outcome != "other":
                    self.db_manager.update_application_outcome_stage(
                        application_id=int(match.application["id"]),
                        stage=outcome,
                        outcome_date=parsed["date_received"][:10],
                        outcome_email_id=str(inserted_id),
                    )
                self.db_manager.upsert_known_sender(
                    email_address=parsed["sender_address"],
                    domain=parsed["sender_domain"],
                    company_name=match.application.get("company_name"),
                    sender_type=(
                        "hr_internal" if parsed["source_type"] == "seek" else "unknown"
                    ),
                )
            elif match.status == "manual_review":
                stats["manual_review"] += 1

        if not dry_run:
            self.db_manager.set_sync_state(
                self.SYNC_STATE_KEY,
                datetime.now(timezone.utc).isoformat(),
            )
            if newest_seen_id:
                self.db_manager.set_sync_state(self.LAST_MESSAGE_KEY, newest_seen_id)

        return stats

    def _build_gmail_service(self):
        """Authenticate and build Gmail API client with offline refresh token."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Gmail API dependencies missing. Install google-auth, "
                "google-auth-oauthlib, and google-api-python-client."
            ) from exc

        def _maybe_write_json_from_env(
            path: Path,
            json_key: str,
            b64_key: str,
            label: str,
        ) -> None:
            if path.exists():
                return

            raw = os.environ.get(json_key) or ""
            if not raw:
                b64 = os.environ.get(b64_key) or ""
                if b64:
                    try:
                        raw = base64.b64decode(b64).decode("utf-8")
                    except Exception:
                        try:
                            raw = base64.urlsafe_b64decode(b64 + "==").decode(
                                "utf-8", errors="replace"
                            )
                        except Exception:
                            raw = ""

            if not raw:
                return

            try:
                json.loads(raw)
            except Exception as exc:
                raise ValueError(f"{label} is not valid JSON") from exc

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding="utf-8")
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass

        _maybe_write_json_from_env(
            path=self.credentials_path,
            json_key="RONIN_GMAIL_CREDENTIALS_JSON",
            b64_key="RONIN_GMAIL_CREDENTIALS_B64",
            label="RONIN_GMAIL_CREDENTIALS_JSON",
        )
        _maybe_write_json_from_env(
            path=self.token_path,
            json_key="RONIN_GMAIL_TOKEN_JSON",
            b64_key="RONIN_GMAIL_TOKEN_B64",
            label="RONIN_GMAIL_TOKEN_JSON",
        )

        if not self.credentials_path.exists():
            raise FileNotFoundError(
                "Gmail credentials.json not found. Place OAuth credentials at "
                f"{self.credentials_path}."
            )

        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.token_path),
                self.DEFAULT_SCOPE,
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path),
                    self.DEFAULT_SCOPE,
                )

                mode = (
                    (
                        os.environ.get("RONIN_GMAIL_AUTH_MODE")
                        or self.auth_mode
                        or "auto"
                    )
                    .strip()
                    .lower()
                )
                if not mode or mode not in {"auto", "local_server", "console"}:
                    mode = "auto"

                interactive = False
                try:
                    interactive = sys.stdin.isatty()
                except Exception:
                    interactive = False

                if not interactive:
                    raise RuntimeError(
                        "Gmail OAuth token missing and no interactive TTY detected. "
                        "Run `ronin feedback sync` once interactively to create the token, "
                        f"or copy an existing token file to {self.token_path}."
                    )

                if mode == "console":
                    creds = flow.run_console()
                elif mode == "local_server":
                    creds = flow.run_local_server(port=0)
                else:
                    # auto: try local server (best UX), then fall back to console.
                    try:
                        creds = flow.run_local_server(port=0)
                    except Exception:
                        creds = flow.run_console()

            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        return build("gmail", "v1", credentials=creds)

    def _parse_message(self, message: Dict) -> Optional[Dict]:
        """Extract sender/content metadata from one Gmail message payload."""
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        header_map = {h.get("name", ""): h.get("value", "") for h in headers}

        sender_name, sender_address = parseaddr(header_map.get("From", ""))
        sender_address = (sender_address or sender_name or "").strip().lower()
        if not sender_address:
            return None

        sender_domain = sender_address.split("@", 1)[1] if "@" in sender_address else ""
        subject = header_map.get("Subject", "")
        date_received = self._extract_message_datetime(message, header_map)
        body_text, body_html = self._extract_bodies(payload)

        return {
            "gmail_message_id": message.get("id"),
            "date_received": date_received,
            "sender_address": sender_address,
            "sender_domain": sender_domain,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "raw_urls": self._extract_urls(body_text + "\n" + body_html),
        }

    def _extract_message_datetime(self, message: Dict, headers: Dict) -> str:
        internal_ms = message.get("internalDate")
        if internal_ms:
            try:
                dt = datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass

        raw_date = headers.get("Date", "")
        try:
            from email.utils import parsedate_to_datetime

            return parsedate_to_datetime(raw_date).astimezone(timezone.utc).isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()

    def _extract_bodies(self, payload: Dict) -> Tuple[str, str]:
        text_chunks: List[str] = []
        html_chunks: List[str] = []

        def walk(part: Dict) -> None:
            mime_type = part.get("mimeType", "")
            body = part.get("body", {})
            data = body.get("data")
            if data:
                try:
                    decoded = base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="replace"
                    )
                except Exception:
                    decoded = ""
                if mime_type == "text/plain":
                    text_chunks.append(decoded)
                elif mime_type == "text/html":
                    html_chunks.append(decoded)

            for child in part.get("parts", []) or []:
                walk(child)

        walk(payload)

        body_html = "\n".join(html_chunks)
        if text_chunks:
            body_text = "\n".join(text_chunks)
        elif body_html:
            soup = BeautifulSoup(body_html, "html.parser")
            body_text = soup.get_text(separator=" ", strip=True)
        else:
            body_text = ""

        return body_text, body_html

    def _extract_urls(self, text: str) -> List[str]:
        pattern = re.compile(r"https?://[^\s\)\]\>\"]+")
        return pattern.findall(text or "")

    def _classify_source_type(self, parsed_email: Dict) -> str:
        sender = parsed_email.get("sender_address", "")
        domain = parsed_email.get("sender_domain", "")
        body = (parsed_email.get("body_text") or "").lower()
        if "seek.com.au" in sender or "seek.com.au" in domain or " seek " in body:
            return "seek"
        if any(token in domain for token in ["recruit", "talent", "agency", "staff"]):
            return "agency"
        if domain:
            return "direct"
        return "unknown"

    def _classify_outcome(self, body_text: str) -> Tuple[str, float]:
        """Rule-based stage classifier using lowercased body text."""
        text = (body_text or "").lower()
        matched: Dict[str, int] = {}

        for category, rule in OUTCOME_RULES.items():
            keywords = rule["keywords"]
            hits = sum(1 for keyword in keywords if keyword in text)
            if hits >= int(rule.get("min_matches", 1)):
                matched[category] = hits

        if not matched:
            return "other", 0.0

        selected = None
        for category in OUTCOME_PRIORITY:
            if category in matched:
                selected = category
                break
        if not selected:
            return "other", 0.0

        total_keywords = len(OUTCOME_RULES[selected]["keywords"])
        confidence = (
            round(matched[selected] / total_keywords, 3) if total_keywords else 0.0
        )
        return selected, confidence

    def _extract_seek_job_id(self, parsed_email: Dict) -> Optional[str]:
        haystacks = [
            parsed_email.get("body_text", ""),
            parsed_email.get("body_html", ""),
            "\n".join(parsed_email.get("raw_urls", [])),
        ]
        patterns = [r"jobId=(\d+)", r"/job/(\d+)"]
        for haystack in haystacks:
            for pattern in patterns:
                match = re.search(pattern, haystack or "", flags=re.IGNORECASE)
                if match:
                    return match.group(1)
        return None

    def _match_email_to_application(
        self, parsed_email: Dict, applications: List[Dict]
    ) -> MatchResult:
        """Cascade matcher for deterministic Seek and fuzzy non-Seek emails."""
        if not applications:
            return MatchResult(status="unmatched", method="unmatched")

        source_type = parsed_email.get("source_type", "unknown")
        if source_type == "seek":
            seek_job_id = self._extract_seek_job_id(parsed_email)
            if seek_job_id:
                exact = self.db_manager.get_application_by_seek_job_id(seek_job_id)
                if exact:
                    return MatchResult(
                        status="auto_matched",
                        application=exact,
                        method="seek_job_id",
                    )

        sender_address = parsed_email.get("sender_address", "")
        sender_domain = parsed_email.get("sender_domain", "")
        known = self.db_manager.lookup_known_sender(sender_address)
        outcome = (
            str(parsed_email.get("outcome_classification") or "other").strip().lower()
        )
        domain_root = self._extract_root_domain(sender_domain)

        candidates = list(applications)
        if known and known.get("company_name"):
            known_company = known["company_name"]
            candidates = [
                app
                for app in candidates
                if self._fuzzy_match(app.get("company_name", ""), known_company) > 0.7
            ]
        elif domain_root:
            domain_filtered = [
                app
                for app in candidates
                if self._fuzzy_match(app.get("company_name", ""), domain_root) > 0.5
            ]
            if domain_filtered:
                candidates = domain_filtered
            elif outcome != "other":
                # Outcome signal but no domain match; fall back to global scoring.
                candidates = list(applications)

        if not candidates and outcome == "other":
            return MatchResult(status="unmatched", method="unmatched")

        subject = str(parsed_email.get("subject", "") or "")
        body_text = str(parsed_email.get("body_text", "") or "")
        body_snippet = body_text[:800]

        # Keep a full-text lowercase blob for keyword/tech-tag overlap.
        body_blob_lower = f"{subject} {body_text}".lower()
        scored: List[Tuple[Dict, float]] = []

        sent_dt = None
        email_date = parsed_email.get("date_received", "")
        try:
            sent_dt = datetime.fromisoformat(str(email_date).replace("Z", "+00:00"))
        except Exception:
            sent_dt = None

        for app in candidates:
            title = app.get("job_title") or app.get("title") or ""
            title_sim = max(
                self._token_jaccard(subject, title),
                self._token_jaccard(body_snippet, title),
            )
            company_sim = 0.0
            if domain_root:
                company_sim = self._fuzzy_match(
                    app.get("company_name", ""), domain_root
                )

            score = title_sim + (company_sim * 0.15)

            applied_date = app.get("date_applied")
            if sent_dt and applied_date:
                try:
                    applied = datetime.fromisoformat(
                        str(applied_date) + "T00:00:00+00:00"
                    )
                    days_diff = (sent_dt - applied).days
                    if 0 <= days_diff <= 30:
                        score += 0.2
                    elif 30 < days_diff <= 60:
                        score += 0.1
                except Exception:
                    pass

            if score > 0:
                scored.append((app, score))

        for idx, (app, score) in enumerate(scored):
            tech_tags = self._safe_json_load(app.get("tech_stack_tags"), [])
            overlap = sum(
                1
                for tag in tech_tags
                if isinstance(tag, str)
                and tag.lower()
                and tag.lower() in body_blob_lower
            )
            scored[idx] = (app, score + overlap * 0.1)

        scored.sort(key=lambda pair: pair[1], reverse=True)
        if not scored:
            if outcome != "other":
                recent = sorted(
                    applications,
                    key=lambda row: str(row.get("date_applied") or ""),
                    reverse=True,
                )[:3]
                return MatchResult(
                    status="manual_review",
                    candidates=[(app, 0.0) for app in recent],
                    method="manual_fallback",
                )
            return MatchResult(status="unmatched", method="unmatched")

        best = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0.0
        if best[1] > 0.5 and (len(scored) == 1 or (best[1] - second_score) > 0.12):
            return MatchResult(
                status="auto_matched",
                application=best[0],
                candidates=scored[:3],
                method="domain_title_date",
            )
        if outcome != "other":
            return MatchResult(
                status="manual_review",
                candidates=scored[:3],
                method="manual",
            )
        return MatchResult(status="unmatched", method="unmatched")

    def _extract_root_domain(self, sender_domain: str) -> str:
        domain = (sender_domain or "").lower().strip()
        if not domain:
            return ""
        tokens = [token for token in domain.split(".") if token]
        if len(tokens) >= 3 and tokens[-1] in {"au", "uk"}:
            return tokens[-3]
        if len(tokens) >= 2:
            return tokens[-2]
        return tokens[0]

    def _token_jaccard(self, left: str, right: str) -> float:
        left_tokens = set(re.findall(r"[a-z0-9]+", (left or "").lower()))
        right_tokens = set(re.findall(r"[a-z0-9]+", (right or "").lower()))
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / union if union else 0.0

    def _fuzzy_match(self, left: str, right: str) -> float:
        left_norm = (left or "").strip().lower()
        right_norm = (right or "").strip().lower()
        if not left_norm or not right_norm:
            return 0.0

        try:
            import Levenshtein  # type: ignore

            return float(Levenshtein.ratio(left_norm, right_norm))
        except Exception:
            if SequenceMatcher:
                return float(SequenceMatcher(a=left_norm, b=right_norm).ratio())
            return 0.0

    @staticmethod
    def _safe_json_load(payload, fallback):
        """Parse JSON payloads stored as strings in DB rows."""
        if payload is None:
            return fallback
        if isinstance(payload, (dict, list)):
            return payload
        if not isinstance(payload, str):
            return fallback
        raw = payload.strip()
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except Exception:
            return fallback
