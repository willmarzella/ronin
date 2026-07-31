"""PostgreSQL backend for Ronin job/application storage.

This module mirrors the public API of :class:`ronin.db.SQLiteManager` so the
rest of the codebase can switch backends via a factory (see ``ronin.db``).

We intentionally keep most date/time columns as TEXT to preserve compatibility
with the existing SQLite schema and string-based comparisons.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger


try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

# Shared with the SQLite backend so both honour scraping.capture_external.
from ronin.db import _capture_external_enabled


class PostgresManager:
    """Manager for a PostgreSQL-backed Ronin database."""

    JOB_BOARD_MAPPING = {
        "seek.com.au": "seek",
        "linkedin.com": "linkedin",
        "indeed.com": "indeed",
        "boards.greenhouse.io": "greenhouse",
        "jobs.lever.co": "lever",
    }
    ARCHETYPE_PROFILES = {"builder", "fixer", "operator", "translator"}

    @classmethod
    def _normalize_archetype_name(cls, value: object) -> str:
        name = str(value or "").strip().lower()
        return name if name in cls.ARCHETYPE_PROFILES else ""

    @classmethod
    def _canonical_resume_fields(cls, payload: Dict) -> Dict[str, str]:
        primary = cls._normalize_archetype_name(payload.get("archetype_primary"))
        resume_arch = cls._normalize_archetype_name(payload.get("resume_archetype"))
        resume_profile = cls._normalize_archetype_name(payload.get("resume_profile"))
        canonical = primary or resume_arch or resume_profile or "builder"
        return {
            "archetype_primary": canonical,
            "resume_archetype": canonical,
            "resume_profile": canonical,
        }

    def __init__(
        self,
        dsn: Optional[str] = None,
    ) -> None:
        if psycopg is None:  # pragma: no cover
            raise RuntimeError(
                "Postgres backend selected but psycopg is not installed. "
                "Install with: pip install psycopg[binary]"
            )

        resolved = (
            dsn
            or os.environ.get("RONIN_DATABASE_DSN")
            or os.environ.get("DATABASE_URL")
        )
        if not resolved:
            raise ValueError(
                "Postgres DSN missing. Set RONIN_DATABASE_DSN (or DATABASE_URL), "
                "or pass dsn=... to PostgresManager."
            )

        self.dsn = str(resolved)
        self.conn = psycopg.connect(self.dsn, row_factory=dict_row)
        self.existing_companies: Dict[str, int] = {}

        logger.info(f"Connected to PostgreSQL database: {self._safe_dsn_for_logs()}")
        self._init_schema()

    def _safe_dsn_for_logs(self) -> str:
        raw = self.dsn
        if "://" not in raw:
            return "(dsn)"
        try:
            parsed = urlparse(raw)
            host = parsed.hostname or "host"
            port = parsed.port or 5432
            db = (parsed.path or "/").lstrip("/") or "db"
            user = parsed.username or "user"
            return f"{parsed.scheme}://{user}@{host}:{port}/{db}"
        except Exception:
            return "(dsn)"

    def _init_schema(self) -> None:
        """Initialize database schema and apply additive migrations."""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id BIGSERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                website TEXT,
                linkedin_ref TEXT,
                description TEXT,
                type TEXT,
                created_at TEXT NOT NULL,
                has_active_job INTEGER DEFAULT 0
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id BIGSERIAL PRIMARY KEY,
                job_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                score INTEGER DEFAULT 0,
                key_tools TEXT,
                recommendation TEXT,
                overview TEXT,
                url TEXT,
                source TEXT,
                quick_apply INTEGER DEFAULT 0,
                created_at TEXT,
                pay TEXT,
                type TEXT,
                location TEXT,
                status TEXT DEFAULT 'DISCOVERED',
                keywords TEXT,
                company_id BIGINT REFERENCES companies(id),
                recruiter_id INTEGER,
                open_job INTEGER DEFAULT 0,
                last_modified TEXT,
                job_classification TEXT DEFAULT 'SHORT_TERM',
                resume_profile TEXT DEFAULT 'builder',
                matching_keyword TEXT,
                resume_archetype TEXT DEFAULT 'builder',
                archetype_scores TEXT,
                archetype_primary TEXT,
                embedding_vector BYTEA,
                job_type TEXT DEFAULT 'unknown',
                day_rate_or_salary TEXT,
                seniority_level TEXT DEFAULT 'unknown',
                tech_stack_tags TEXT,
                market_intelligence_only INTEGER DEFAULT 0,
                below_threshold INTEGER DEFAULT 0,
                selection_needs_review INTEGER DEFAULT 0,
                application_batch_id BIGINT,
                resume_commit_hash TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id BIGSERIAL PRIMARY KEY,
                job_id TEXT UNIQUE NOT NULL,
                seek_job_id TEXT,
                title TEXT NOT NULL,
                job_title TEXT,
                description TEXT,
                job_description_text TEXT,
                company_name TEXT,
                source TEXT,
                url TEXT,
                date_scraped TEXT,
                date_applied TEXT,
                job_type TEXT,
                day_rate_or_salary TEXT,
                seniority_level TEXT,
                tech_stack_tags TEXT,
                search_keyword_origin TEXT,
                archetype_scores TEXT,
                archetype_primary TEXT,
                embedding_vector BYTEA,
                resume_profile TEXT DEFAULT 'builder',
                resume_archetype TEXT DEFAULT 'builder',
                resume_variant_sent TEXT,
                resume_commit_hash TEXT,
                profile_state_at_application TEXT,
                application_batch_id BIGINT,
                key_tools TEXT,
                matching_keyword TEXT,
                job_classification TEXT,
                applied_at TEXT,
                outcome TEXT DEFAULT 'PENDING',
                outcome_confidence DOUBLE PRECISION DEFAULT 0,
                outcome_email_message_id TEXT,
                outcome_email_subject TEXT,
                outcome_email_from TEXT,
                outcome_email_received_at TEXT,
                outcome_updated_at TEXT,
                outcome_stage TEXT DEFAULT 'applied',
                outcome_date TEXT,
                outcome_email_id TEXT,
                market_intelligence_only INTEGER DEFAULT 0,
                below_threshold INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                last_modified TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outcome_events (
                id BIGSERIAL PRIMARY KEY,
                message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                sender TEXT,
                subject TEXT,
                received_at TEXT,
                outcome TEXT,
                confidence DOUBLE PRECISION DEFAULT 0,
                match_strategy TEXT,
                matched_application_id BIGINT,
                snippet TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (matched_application_id) REFERENCES applications(id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sender_ignore_list (
                id BIGSERIAL PRIMARY KEY,
                sender_address TEXT,
                sender_domain TEXT,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sender_address),
                UNIQUE(sender_domain)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS email_parsed (
                id BIGSERIAL PRIMARY KEY,
                gmail_message_id TEXT UNIQUE NOT NULL,
                date_received TIMESTAMPTZ NOT NULL,
                sender_address TEXT NOT NULL,
                sender_domain TEXT NOT NULL,
                subject TEXT,
                body_text TEXT,
                body_html TEXT,
                source_type TEXT NOT NULL,
                outcome_classification TEXT,
                classification_confidence DOUBLE PRECISION,
                matched_application_id BIGINT REFERENCES applications(id),
                match_method TEXT,
                requires_manual_review INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS known_senders (
                id BIGSERIAL PRIMARY KEY,
                email_address TEXT NOT NULL,
                domain TEXT NOT NULL,
                company_name TEXT,
                sender_type TEXT DEFAULT 'unknown',
                first_seen_date TEXT NOT NULL,
                UNIQUE(email_address)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recruiters (
                id BIGSERIAL PRIMARY KEY,
                identity_key TEXT UNIQUE NOT NULL,
                full_name TEXT,
                first_name TEXT,
                last_name TEXT,
                email TEXT,
                phone TEXT,
                linkedin_url TEXT,
                company_name TEXT,
                domain TEXT,
                source TEXT,
                confidence DOUBLE PRECISION DEFAULT 0,
                jobs_seen INTEGER DEFAULT 0,
                outreach_state TEXT DEFAULT 'none',
                last_outreach_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS job_recruiter_links (
                id BIGSERIAL PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(job_id),
                recruiter_id BIGINT NOT NULL REFERENCES recruiters(id),
                relationship TEXT DEFAULT 'recruiter',
                confidence DOUBLE PRECISION DEFAULT 0,
                inferred_email TEXT,
                inference_rule TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, recruiter_id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outreach_log (
                id BIGSERIAL PRIMARY KEY,
                job_id TEXT REFERENCES jobs(job_id),
                recruiter_id BIGINT REFERENCES recruiters(id),
                channel TEXT NOT NULL,
                target TEXT,
                subject TEXT,
                body TEXT,
                status TEXT DEFAULT 'planned',
                error_message TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resume_variants (
                id BIGSERIAL PRIMARY KEY,
                archetype TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                current_commit_hash TEXT NOT NULL,
                embedding_vector BYTEA,
                alignment_score DOUBLE PRECISION,
                last_rewritten TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS market_centroids (
                id BIGSERIAL PRIMARY KEY,
                archetype TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                centroid_vector BYTEA NOT NULL,
                jd_count INTEGER NOT NULL,
                shift_from_previous DOUBLE PRECISION,
                top_gained_terms TEXT,
                top_lost_terms TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(archetype, window_start)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS drift_alerts (
                id BIGSERIAL PRIMARY KEY,
                archetype TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                metric_value DOUBLE PRECISION NOT NULL,
                threshold_value DOUBLE PRECISION NOT NULL,
                details TEXT,
                acknowledged INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS application_batches (
                id BIGSERIAL PRIMARY KEY,
                archetype TEXT NOT NULL,
                profile_state TEXT NOT NULL,
                batch_start_date TEXT NOT NULL,
                batch_end_date TEXT,
                application_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS phone_call_log (
                id BIGSERIAL PRIMARY KEY,
                phone_number TEXT,
                company_name TEXT,
                job_title TEXT,
                outcome TEXT,
                notes TEXT,
                call_date TEXT NOT NULL,
                matched_application_id BIGINT REFERENCES applications(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_job_id ON jobs(job_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_pending ON jobs(status, quick_apply, score DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_classification ON jobs(job_classification)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_matching_keyword ON jobs(matching_keyword)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_outcome ON applications(outcome)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_resume_profile ON applications(resume_profile)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_keyword ON applications(matching_keyword)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_outcome_events_message_id ON outcome_events(message_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_archetype_primary ON jobs(archetype_primary)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_market_intel ON jobs(market_intelligence_only)"
        )
        # Idempotent migration for existing postgres deployments that pre-date
        # the column split. Backfills threshold-demoted rows into the new
        # column and clears them from market_intelligence_only.
        cursor.execute(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS below_threshold INTEGER DEFAULT 0"
        )
        cursor.execute(
            "ALTER TABLE applications ADD COLUMN IF NOT EXISTS below_threshold INTEGER DEFAULT 0"
        )
        cursor.execute(
            "UPDATE jobs SET below_threshold = 1, market_intelligence_only = 0 "
            "WHERE market_intelligence_only = 1 AND quick_apply = 1 "
            "AND below_threshold = 0"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_below_threshold ON jobs(below_threshold)"
        )
        # Phase 1 (external apply): apply_type distinguishes Seek Quick Apply
        # from link-out external applies; apply_url holds the external target.
        cursor.execute(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_type TEXT DEFAULT 'quick'"
        )
        cursor.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_url TEXT")
        # Outcome-weighted apply ordering; recomputed by recompute_queue.
        cursor.execute(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority_score DOUBLE PRECISION"
        )
        cursor.execute(
            "UPDATE jobs SET apply_type = "
            "CASE WHEN quick_apply = 1 THEN 'quick' ELSE 'external' END "
            "WHERE apply_type IS NULL"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_apply_type ON jobs(apply_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_seek_job_id ON applications(seek_job_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_stage ON applications(outcome_stage)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_archetype ON applications(archetype_primary)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_commit_hash ON applications(resume_commit_hash)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_email_parsed_received ON email_parsed(date_received)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_email_parsed_match ON email_parsed(matched_application_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_known_senders_domain ON known_senders(domain)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruiters_email ON recruiters(email)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruiters_linkedin ON recruiters(linkedin_url)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruiters_company ON recruiters(company_name)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_recruiter_links_job ON job_recruiter_links(job_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_recruiter_links_recruiter ON job_recruiter_links(recruiter_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_outreach_log_recent ON outreach_log(created_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_outreach_log_job_recruiter ON outreach_log(job_id, recruiter_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_centroids_archetype ON market_centroids(archetype, window_start DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_drift_alerts_open ON drift_alerts(acknowledged, created_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_phone_call_log_date ON phone_call_log(call_date DESC)"
        )

        self.conn.commit()
        logger.debug("Postgres schema initialized")

    def _get_job_source(self, url: str) -> str:
        """Determine job source from URL."""
        try:
            domain = urlparse(url).netloc.lower()
            for board_domain, source in self.JOB_BOARD_MAPPING.items():
                if board_domain in domain:
                    return source
            return "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def _serialize_vector(vector) -> Optional[bytes]:
        """Serialize an embedding vector to bytes for BYTEA storage."""
        if vector is None:
            return None
        if isinstance(vector, (bytes, bytearray)):
            return bytes(vector)
        if isinstance(vector, str):
            return vector.encode("utf-8")
        try:
            return json.dumps([float(v) for v in vector]).encode("utf-8")
        except Exception:
            return None

    @staticmethod
    def _deserialize_vector(vector_blob) -> Optional[List[float]]:
        """Deserialize an embedding vector stored as bytes/json."""
        if vector_blob is None:
            return None
        if isinstance(vector_blob, list):
            return [float(v) for v in vector_blob]
        try:
            if isinstance(vector_blob, (bytes, bytearray, memoryview)):
                payload = bytes(vector_blob).decode("utf-8")
            else:
                payload = str(vector_blob)
            data = json.loads(payload)
            if isinstance(data, list):
                return [float(v) for v in data]
        except Exception:
            return None
        return None

    @staticmethod
    def _to_json_array(value) -> str:
        """Normalize values to a JSON array string."""
        if value is None:
            return "[]"
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                return "[]"
            if trimmed.startswith("["):
                return trimmed
            return json.dumps([trimmed])
        if isinstance(value, list):
            return json.dumps(value)
        return json.dumps([str(value)])

    @staticmethod
    def _safe_json_load(payload, fallback):
        """Safely parse JSON strings with a fallback value."""
        if payload is None:
            return fallback
        if isinstance(payload, (dict, list)):
            return payload
        if not isinstance(payload, str):
            return fallback
        text = payload.strip()
        if not text:
            return fallback
        try:
            value = json.loads(text)
            return value
        except Exception:
            return fallback

    @staticmethod
    def _split_person_name(full_name: str) -> tuple[str, str]:
        parts = [p for p in str(full_name or "").strip().split() if p]
        if not parts:
            return "", ""
        first = parts[0]
        last = parts[-1] if len(parts) > 1 else ""
        return first, last

    @staticmethod
    def _build_recruiter_identity(
        full_name: str = "",
        email: str = "",
        linkedin_url: str = "",
        company_name: str = "",
        domain: str = "",
    ) -> str:
        email_norm = str(email or "").strip().lower()
        if email_norm:
            return f"email:{email_norm}"
        linkedin_norm = str(linkedin_url or "").strip().lower()
        if linkedin_norm:
            return f"linkedin:{linkedin_norm}"
        name_norm = str(full_name or "").strip().lower()
        if name_norm:
            scope = str(company_name or domain or "").strip().lower()
            return f"name:{name_norm}|{scope}"
        return ""

    def job_exists(self, job_id: str) -> bool:
        """Check if a job ID already exists in the database."""
        job_id = str(job_id or "").strip()
        if not job_id:
            return False
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM jobs WHERE job_id = %s LIMIT 1", (job_id,))
        return cursor.fetchone() is not None

    def _get_or_create_company(self, company_name: str) -> Optional[int]:
        """Get existing company ID or create a new one."""
        if not company_name:
            return None

        company_lower = company_name.lower()
        if company_lower in self.existing_companies:
            return self.existing_companies[company_lower]

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id FROM companies WHERE LOWER(name) = LOWER(%s)",
                (company_name,),
            )
            row = cursor.fetchone()
            if row and row.get("id") is not None:
                company_id = int(row["id"])
                self.existing_companies[company_lower] = company_id
                return company_id

            created_at = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO companies (name, created_at)
                VALUES (%s, %s)
                ON CONFLICT(name) DO UPDATE SET name = excluded.name
                RETURNING id
            """,
                (company_name, created_at),
            )
            company_id = int(cursor.fetchone()["id"])
            self.conn.commit()
            self.existing_companies[company_lower] = company_id
            return company_id

        except Exception as e:
            logger.error(f"Error getting/creating company '{company_name}': {e}")
            self.conn.rollback()
            return None

    def insert_job(self, job_data: Dict) -> bool:
        """Insert a job into database if it doesn't exist."""
        job_id = str(job_data.get("job_id") or "").strip()
        if not job_id:
            logger.error("Missing job_id in job_data")
            return False

        if self.job_exists(job_id):
            logger.debug(f"Job {job_id} already exists, skipping")
            return False

        try:
            company_name = job_data.get("company", "")
            analysis_data = job_data.get("analysis", {})
            url = job_data.get("url", "")
            source = job_data.get("source") or self._get_job_source(url)
            company_id = self._get_or_create_company(company_name)

            archetype_scores = analysis_data.get("archetype_scores")
            if isinstance(archetype_scores, dict):
                archetype_scores = json.dumps(archetype_scores)

            embedding_blob = self._serialize_vector(
                analysis_data.get("embedding_vector")
            )
            tech_stack_tags = self._to_json_array(
                analysis_data.get("tech_stack_tags")
                or analysis_data.get("tech_keywords")
                or []
            )
            apply_type = job_data.get("apply_type") or (
                "quick" if job_data.get("quick_apply", False) else "external"
            )
            apply_url = job_data.get("apply_url")
            market_intel = (
                1
                if analysis_data.get("market_intelligence_only")
                or (
                    not job_data.get("quick_apply", False)
                    and not _capture_external_enabled()
                )
                else 0
            )
            needs_review = 1 if analysis_data.get("selection_needs_review") else 0
            canonical_resume = self._canonical_resume_fields(analysis_data)

            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO jobs (
                    job_id, title, description, score, key_tools, recommendation,
                    overview, url, source, quick_apply, apply_type, apply_url,
                    created_at, pay, type,
                    location, status, keywords, company_id, job_classification,
                    resume_profile, matching_keyword, resume_archetype,
                    archetype_scores, archetype_primary, embedding_vector, job_type,
                    day_rate_or_salary, seniority_level, tech_stack_tags,
                    market_intelligence_only, selection_needs_review,
                    application_batch_id, resume_commit_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s
                )
            """,
                (
                    job_id,
                    job_data.get("title", ""),
                    job_data.get("description", ""),
                    analysis_data.get("score", 0),
                    analysis_data.get("key_tools")
                    or analysis_data.get("tech_stack", "N/A"),
                    analysis_data.get("recommendation", ""),
                    analysis_data.get("overview", ""),
                    url,
                    source,
                    1 if job_data.get("quick_apply", False) else 0,
                    apply_type,
                    apply_url,
                    job_data.get("created_at"),
                    job_data.get("pay_rate", ""),
                    job_data.get("work_type", ""),
                    job_data.get("location", ""),
                    "DISCOVERED",
                    ", ".join(analysis_data.get("tech_keywords", [])),
                    company_id,
                    analysis_data.get("job_classification", "SHORT_TERM"),
                    canonical_resume["resume_profile"],
                    job_data.get("matching_keyword", ""),
                    canonical_resume["resume_archetype"],
                    archetype_scores,
                    canonical_resume["archetype_primary"],
                    embedding_blob,
                    analysis_data.get("job_type", "unknown"),
                    analysis_data.get("day_rate_or_salary")
                    or job_data.get("pay_rate", ""),
                    analysis_data.get("seniority_level", "unknown"),
                    tech_stack_tags,
                    market_intel,
                    needs_review,
                    analysis_data.get("application_batch_id"),
                    analysis_data.get("resume_commit_hash"),
                ),
            )

            self.conn.commit()
            logger.debug(f"Inserted new job: {job_id}")
            return True

        except Exception as e:
            logger.error(f"Error inserting job: {e}")
            self.conn.rollback()
            return False

    def batch_insert_jobs(self, jobs_data: List[Dict]) -> Dict[str, int]:
        """Insert multiple jobs into database."""
        new_jobs_count = 0
        duplicate_count = 0
        error_count = 0

        for job in jobs_data:
            try:
                if self.insert_job(job):
                    new_jobs_count += 1
                else:
                    duplicate_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"Failed to insert job: {e}")

        return {
            "new_jobs": new_jobs_count,
            "duplicates": duplicate_count,
            "errors": error_count,
        }

    def get_pending_jobs(self, limit: int = 10) -> List[Dict]:
        """Get jobs that are ready to apply to."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT j.*, c.name as company_name
                FROM jobs j
                LEFT JOIN companies c ON j.company_id = c.id
                WHERE j.status IN ('DISCOVERED', 'APP_ERROR')
                  AND j.quick_apply = 1
                  AND COALESCE(j.market_intelligence_only, 0) = 0
                  AND COALESCE(j.below_threshold, 0) = 0
                ORDER BY j.priority_score DESC NULLS LAST, j.score DESC, j.created_at DESC
                LIMIT %s
            """,
                (int(limit),),
            )

            jobs: List[Dict] = []
            for row in cursor.fetchall():
                job_dict = dict(row)
                job_dict["work_type"] = job_dict.get("type", "")
                job_dict["fields"] = {
                    "Title": job_dict.get("title"),
                    "Company Name": job_dict.get("company_name"),
                    "URL": job_dict.get("url"),
                    "Description": job_dict.get("description"),
                    "Score": job_dict.get("score", 0),
                    "Key Tools": job_dict.get("key_tools", ""),
                    "Job Classification": job_dict.get(
                        "job_classification", "SHORT_TERM"
                    ),
                    "Resume Profile": job_dict.get("resume_profile", "builder"),
                    "Resume Archetype": job_dict.get("resume_archetype", "builder"),
                    "Matching Keyword": job_dict.get("matching_keyword", ""),
                }
                jobs.append(job_dict)

            return jobs
        except Exception as e:
            logger.error(f"Error getting pending jobs: {e}")
            return []

    def get_pending_external_jobs(
        self, limit: int = 10, min_score: int = 0
    ) -> List[Dict]:
        """Get external (link-out) jobs ready for the agent applier."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT j.*, c.name as company_name
                FROM jobs j
                LEFT JOIN companies c ON j.company_id = c.id
                WHERE j.status IN ('DISCOVERED', 'APP_ERROR')
                  AND j.apply_type = 'external'
                  AND COALESCE(j.market_intelligence_only, 0) = 0
                  AND COALESCE(j.below_threshold, 0) = 0
                  AND COALESCE(j.score, 0) >= %s
                ORDER BY j.priority_score DESC NULLS LAST, j.score DESC, j.created_at DESC
                LIMIT %s
            """,
                (int(min_score), int(limit)),
            )
            jobs: List[Dict] = []
            for row in cursor.fetchall():
                job_dict = dict(row)
                job_dict["work_type"] = job_dict.get("type", "")
                job_dict["fields"] = {
                    "Title": job_dict.get("title"),
                    "Company Name": job_dict.get("company_name"),
                    "URL": job_dict.get("url"),
                    "Apply URL": job_dict.get("apply_url"),
                    "Description": job_dict.get("description"),
                    "Score": job_dict.get("score", 0),
                    "Key Tools": job_dict.get("key_tools", ""),
                    "Resume Profile": job_dict.get("resume_profile", "builder"),
                }
                jobs.append(job_dict)
            return jobs
        except Exception as e:
            logger.error(f"Error getting pending external jobs: {e}")
            return []

    def get_external_jobs_report(self) -> List[Dict]:
        """Summarise captured external jobs grouped by company."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT
                    COALESCE(c.name, 'Unknown') AS company_name,
                    COUNT(*) AS external_count,
                    SUM(CASE WHEN j.status = 'APPLIED' THEN 1 ELSE 0 END)
                        AS applied_count,
                    MAX(j.score) AS top_score
                FROM jobs j
                LEFT JOIN companies c ON j.company_id = c.id
                WHERE j.apply_type = 'external'
                GROUP BY COALESCE(c.name, 'Unknown')
                ORDER BY external_count DESC, top_score DESC
            """
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error building external jobs report: {e}")
            return []

    def update_job_status(self, job_id: str, status: str) -> bool:
        """Update the status of a job by job_id."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = %s, last_modified = %s
                WHERE job_id = %s
            """,
                (status, datetime.now().isoformat(), job_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating job status: {e}")
            self.conn.rollback()
            return False

    def update_record(self, record_id: int, fields: dict) -> bool:
        """Update an existing job record by database ID."""
        if not fields:
            return False

        allowed_fields = {
            "status",
            "score",
            "key_tools",
            "recommendation",
            "overview",
            "last_modified",
            "job_classification",
            "resume_profile",
            "title",
            "description",
            "url",
            "pay",
            "type",
            "location",
            "keywords",
            "matching_keyword",
            "resume_archetype",
            "archetype_scores",
            "archetype_primary",
            "embedding_vector",
            "job_type",
            "day_rate_or_salary",
            "seniority_level",
            "tech_stack_tags",
            "market_intelligence_only",
            "below_threshold",
            "selection_needs_review",
            "application_batch_id",
            "resume_commit_hash",
            "priority_score",
        }

        safe_fields = {k: v for k, v in fields.items() if k in allowed_fields}
        if not safe_fields:
            logger.warning(f"No valid fields to update for record {record_id}")
            return False

        if {
            "archetype_primary",
            "resume_archetype",
            "resume_profile",
        } & set(safe_fields.keys()):
            canonical_resume = self._canonical_resume_fields(safe_fields)
            safe_fields["archetype_primary"] = canonical_resume["archetype_primary"]
            safe_fields["resume_archetype"] = canonical_resume["resume_archetype"]
            safe_fields["resume_profile"] = canonical_resume["resume_profile"]

        if "embedding_vector" in safe_fields:
            safe_fields["embedding_vector"] = self._serialize_vector(
                safe_fields["embedding_vector"]
            )

        for json_key in ("archetype_scores", "tech_stack_tags"):
            if json_key in safe_fields:
                value = safe_fields[json_key]
                if isinstance(value, (dict, list)):
                    safe_fields[json_key] = json.dumps(value)

        try:
            set_clause = ", ".join([f"{key} = %s" for key in safe_fields.keys()])
            values = list(safe_fields.values()) + [int(record_id)]
            cursor = self.conn.cursor()
            cursor.execute(f"UPDATE jobs SET {set_clause} WHERE id = %s", values)
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating record {record_id}: {e}")
            self.conn.rollback()
            return False

    def get_jobs_stats(self) -> Dict:
        """Get statistics about jobs in the database."""
        try:
            cursor = self.conn.cursor()
            stats: Dict = {}

            cursor.execute("SELECT COUNT(*) AS count FROM jobs")
            row = cursor.fetchone()
            stats["total_jobs"] = int(row.get("count", 0) if row else 0)

            cursor.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status")
            stats["by_status"] = {
                str(row.get("status")): int(row.get("count", 0))
                for row in cursor.fetchall()
            }

            cursor.execute(
                "SELECT source, COUNT(*) AS count FROM jobs GROUP BY source ORDER BY COUNT(*) DESC"
            )
            stats["by_source"] = {
                str(row.get("source")): int(row.get("count", 0))
                for row in cursor.fetchall()
            }
            return stats

        except Exception as e:
            logger.error(f"Error getting job stats: {e}")
            return {}

    def get_jobs_corpus(self, limit: int = 0) -> List[Dict]:
        """Return job rows for corpus analysis (broad, unfiltered)."""
        try:
            query = (
                "SELECT id, job_id, title, created_at, status, quick_apply, source "
                "FROM jobs ORDER BY created_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT %s"
                params.append(int(limit))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading jobs corpus: {e}")
            return []

    def get_jobs_for_labeling(self, limit: int = 0) -> List[Dict]:
        """Return job rows (with descriptions) for classifier labeling/validation."""
        try:
            query = (
                "SELECT j.id, j.job_id, j.title, j.description, c.name AS company_name, "
                "j.created_at, j.status, j.quick_apply, j.source, j.archetype_primary, j.archetype_scores "
                "FROM jobs j "
                "LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.description IS NOT NULL AND btrim(j.description) <> '' "
                "ORDER BY j.created_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT %s"
                params.append(int(limit))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading jobs for labeling: {e}")
            return []

    def get_job_by_job_id(self, job_id: str):
        """Return a single job row by job_id."""
        if not job_id:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT j.*, c.name AS company_name "
                "FROM jobs j LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.job_id = %s",
                (str(job_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error reading job by job_id {job_id}: {e}")
            return None

    def get_existing_job_ids(self) -> set:
        """Get all existing job IDs."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT job_id FROM jobs")
        return {str(row.get("job_id")) for row in cursor.fetchall()}

    def record_application_submission(self, job_record: Dict) -> bool:
        """Upsert an application snapshot when a job is successfully submitted."""
        job_id = job_record.get("job_id")
        if not job_id:
            logger.warning("Cannot record application submission without job_id")
            return False

        timestamp = datetime.now().isoformat()
        archetype_scores = job_record.get("archetype_scores")
        if isinstance(archetype_scores, dict):
            archetype_scores = json.dumps(archetype_scores)
        embedding_blob = self._serialize_vector(job_record.get("embedding_vector"))
        tech_stack_tags = self._to_json_array(job_record.get("tech_stack_tags") or [])
        date_applied = timestamp[:10]
        canonical_resume = self._canonical_resume_fields(job_record)

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO applications (
                    job_id, seek_job_id, title, job_title, description,
                    job_description_text, company_name, source, url,
                    date_scraped, date_applied, job_type, day_rate_or_salary,
                    seniority_level, tech_stack_tags, search_keyword_origin,
                    archetype_scores, archetype_primary, embedding_vector,
                    resume_profile, resume_archetype, resume_variant_sent,
                    resume_commit_hash, profile_state_at_application,
                    application_batch_id, key_tools, matching_keyword,
                    job_classification, applied_at, outcome_stage,
                    market_intelligence_only, below_threshold,
                    created_at, updated_at, last_modified
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT(job_id) DO UPDATE SET
                    seek_job_id = excluded.seek_job_id,
                    title = excluded.title,
                    job_title = excluded.job_title,
                    description = excluded.description,
                    job_description_text = excluded.job_description_text,
                    company_name = excluded.company_name,
                    source = excluded.source,
                    url = excluded.url,
                    date_scraped = excluded.date_scraped,
                    date_applied = excluded.date_applied,
                    job_type = excluded.job_type,
                    day_rate_or_salary = excluded.day_rate_or_salary,
                    seniority_level = excluded.seniority_level,
                    tech_stack_tags = excluded.tech_stack_tags,
                    search_keyword_origin = excluded.search_keyword_origin,
                    archetype_scores = excluded.archetype_scores,
                    archetype_primary = excluded.archetype_primary,
                    embedding_vector = excluded.embedding_vector,
                    resume_profile = excluded.resume_profile,
                    resume_archetype = excluded.resume_archetype,
                    resume_variant_sent = excluded.resume_variant_sent,
                    resume_commit_hash = excluded.resume_commit_hash,
                    profile_state_at_application = excluded.profile_state_at_application,
                    application_batch_id = excluded.application_batch_id,
                    key_tools = excluded.key_tools,
                    matching_keyword = excluded.matching_keyword,
                    job_classification = excluded.job_classification,
                    applied_at = excluded.applied_at,
                    outcome_stage = excluded.outcome_stage,
                    market_intelligence_only = excluded.market_intelligence_only,
                    below_threshold = excluded.below_threshold,
                    updated_at = excluded.updated_at,
                    last_modified = excluded.last_modified
            """,
                (
                    job_id,
                    job_record.get("seek_job_id") or job_id,
                    job_record.get("title", ""),
                    job_record.get("title", ""),
                    job_record.get("description", ""),
                    job_record.get("description", ""),
                    job_record.get("company_name", ""),
                    job_record.get("source", ""),
                    job_record.get("url", ""),
                    (
                        job_record.get("created_at")[:10]
                        if isinstance(job_record.get("created_at"), str)
                        else None
                    ),
                    date_applied,
                    job_record.get("job_type") or job_record.get("type") or "unknown",
                    job_record.get("day_rate_or_salary") or job_record.get("pay", ""),
                    job_record.get("seniority_level", "unknown"),
                    tech_stack_tags,
                    job_record.get("matching_keyword", ""),
                    archetype_scores,
                    canonical_resume["archetype_primary"],
                    embedding_blob,
                    canonical_resume["resume_profile"],
                    canonical_resume["resume_archetype"],
                    job_record.get("resume_variant_sent")
                    or canonical_resume["archetype_primary"],
                    job_record.get("resume_commit_hash"),
                    job_record.get("profile_state_at_application")
                    or canonical_resume["archetype_primary"],
                    job_record.get("application_batch_id"),
                    job_record.get("key_tools", ""),
                    job_record.get("matching_keyword", ""),
                    job_record.get("job_classification", "SHORT_TERM"),
                    timestamp,
                    "applied",
                    int(bool(job_record.get("market_intelligence_only", 0))),
                    int(bool(job_record.get("below_threshold", 0))),
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error recording application submission for {job_id}: {e}")
            self.conn.rollback()
            return False

    def backfill_applications_from_applied_jobs(
        self,
        limit: int = 0,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Insert missing application rows for jobs already marked APPLIED.

        Idempotent: inserts only rows missing from `applications`.
        """

        stats = {
            "applied_jobs": 0,
            "applications_total": 0,
            "missing": 0,
            "inserted": 0,
            "dry_run": 1 if dry_run else 0,
        }

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE status = 'APPLIED'"
            )
            row = cursor.fetchone() or {}
            stats["applied_jobs"] = int(row.get("count", 0) or 0)

            cursor.execute("SELECT COUNT(*) AS count FROM applications")
            row = cursor.fetchone() or {}
            stats["applications_total"] = int(row.get("count", 0) or 0)

            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM jobs j
                WHERE j.status = 'APPLIED'
                  AND NOT EXISTS (
                    SELECT 1 FROM applications a WHERE a.job_id = j.job_id
                  )
            """
            )
            row = cursor.fetchone() or {}
            stats["missing"] = int(row.get("count", 0) or 0)

            if dry_run or stats["missing"] == 0:
                return stats

            query = (
                "SELECT j.*, c.name AS company_name "
                "FROM jobs j LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.status = 'APPLIED' "
                "AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.job_id = j.job_id) "
                "ORDER BY j.created_at DESC"
            )
            params: list = []
            if limit > 0:
                query += " LIMIT %s"
                params.append(int(limit))

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

            columns = [
                "job_id",
                "seek_job_id",
                "title",
                "job_title",
                "description",
                "job_description_text",
                "company_name",
                "source",
                "url",
                "date_scraped",
                "date_applied",
                "job_type",
                "day_rate_or_salary",
                "seniority_level",
                "tech_stack_tags",
                "search_keyword_origin",
                "archetype_scores",
                "archetype_primary",
                "embedding_vector",
                "resume_profile",
                "resume_archetype",
                "resume_variant_sent",
                "resume_commit_hash",
                "profile_state_at_application",
                "application_batch_id",
                "key_tools",
                "matching_keyword",
                "job_classification",
                "applied_at",
                "outcome_stage",
                "market_intelligence_only",
                "below_threshold",
                "created_at",
                "updated_at",
                "last_modified",
            ]

            placeholders = ", ".join(["%s"] * len(columns))
            insert_sql = (
                f"INSERT INTO applications ({', '.join(columns)}) "
                f"VALUES ({placeholders}) "
                "ON CONFLICT (job_id) DO NOTHING"
            )

            now = datetime.now().isoformat()
            inserted = 0

            for row in rows:
                job = dict(row)
                canonical_resume = self._canonical_resume_fields(job)
                applied_at = job.get("last_modified") or job.get("created_at") or now
                date_scraped = (
                    job.get("created_at")[:10]
                    if isinstance(job.get("created_at"), str)
                    else None
                )
                date_applied = applied_at[:10] if isinstance(applied_at, str) else None

                source = (job.get("source") or "").strip().lower()
                seek_job_id = job.get("job_id") if source == "seek" else None

                cursor.execute(
                    insert_sql,
                    (
                        job.get("job_id"),
                        seek_job_id,
                        job.get("title") or "",
                        job.get("title") or "",
                        job.get("description"),
                        job.get("description"),
                        job.get("company_name"),
                        job.get("source"),
                        job.get("url"),
                        date_scraped,
                        date_applied,
                        job.get("job_type") or job.get("type") or "unknown",
                        job.get("day_rate_or_salary") or job.get("pay") or "",
                        job.get("seniority_level"),
                        job.get("tech_stack_tags"),
                        job.get("matching_keyword") or "",
                        job.get("archetype_scores"),
                        canonical_resume["archetype_primary"],
                        job.get("embedding_vector"),
                        canonical_resume["resume_profile"],
                        canonical_resume["resume_archetype"],
                        None,
                        job.get("resume_commit_hash"),
                        canonical_resume["resume_archetype"],
                        job.get("application_batch_id"),
                        job.get("key_tools"),
                        job.get("matching_keyword"),
                        job.get("job_classification"),
                        applied_at,
                        "applied",
                        int(bool(job.get("market_intelligence_only") or 0)),
                        int(bool(job.get("below_threshold") or 0)),
                        applied_at,
                        now,
                        now,
                    ),
                )
                if cursor.rowcount:
                    inserted += 1

            self.conn.commit()
            stats["inserted"] = inserted
            return stats
        except Exception as e:
            logger.error(f"Error backfilling applications: {e}")
            self.conn.rollback()
            return stats

    def get_applications_missing_archetype(self, limit: int = 0) -> List[Dict]:
        """Return application rows missing archetype_primary."""
        try:
            cursor = self.conn.cursor()
            query = (
                "SELECT * FROM applications "
                "WHERE (archetype_primary IS NULL OR btrim(archetype_primary) = '') "
                "  AND ((job_description_text IS NOT NULL AND btrim(job_description_text) <> '') "
                "       OR (description IS NOT NULL AND btrim(description) <> '')) "
                "ORDER BY applied_at DESC"
            )
            params: list = []
            if limit > 0:
                query += " LIMIT %s"
                params.append(int(limit))

            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading applications missing archetype: {e}")
            return []

    def update_application_archetype(
        self,
        application_id: int,
        archetype_primary: str,
        archetype_scores: Dict,
    ) -> bool:
        """Update archetype fields on an application record."""
        try:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE applications
                SET archetype_primary = %s,
                    archetype_scores = %s,
                    updated_at = %s,
                    last_modified = %s
                WHERE id = %s
            """,
                (
                    str(archetype_primary or "").strip().lower() or None,
                    json.dumps(archetype_scores or {}),
                    now,
                    now,
                    int(application_id),
                ),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating application archetype {application_id}: {e}")
            self.conn.rollback()
            return False

    def get_applications(
        self,
        limit: int = 500,
        outcomes: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Fetch application snapshots for outcome tracking and analysis."""
        try:
            query = "SELECT * FROM applications"
            params: list = []
            if outcomes:
                placeholders = ", ".join(["%s"] * len(outcomes))
                query += f" WHERE outcome IN ({placeholders})"
                params.extend(outcomes)

            query += " ORDER BY applied_at DESC"
            if limit > 0:
                query += " LIMIT %s"
                params.append(int(limit))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading applications: {e}")
            return []

    def record_outcome_event(self, event: Dict) -> bool:
        """Insert a parsed outcome email event and update matched application."""
        required = ["message_id", "outcome"]
        missing = [field for field in required if not event.get(field)]
        if missing:
            logger.warning(f"Outcome event missing required fields: {missing}")
            return False

        timestamp = datetime.now().isoformat()

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO outcome_events (
                    message_id, thread_id, sender, subject, received_at,
                    outcome, confidence, match_strategy, matched_application_id,
                    snippet, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    event.get("message_id"),
                    event.get("thread_id", ""),
                    event.get("sender", ""),
                    event.get("subject", ""),
                    event.get("received_at", ""),
                    event.get("outcome", ""),
                    float(event.get("confidence", 0.0) or 0.0),
                    event.get("match_strategy", ""),
                    event.get("matched_application_id"),
                    event.get("snippet", ""),
                    timestamp,
                ),
            )

            matched_application_id = event.get("matched_application_id")
            if matched_application_id:
                self._update_application_outcome(
                    application_id=int(matched_application_id),
                    outcome=event.get("outcome", "PENDING"),
                    confidence=float(event.get("confidence", 0.0) or 0.0),
                    message_id=event.get("message_id", ""),
                    subject=event.get("subject", ""),
                    sender=event.get("sender", ""),
                    received_at=event.get("received_at", ""),
                )

            self.conn.commit()
            return True

        except Exception as e:
            # If the message_id is already recorded, treat as duplicate.
            logger.debug(
                f"Outcome event {event.get('message_id')} not recorded (duplicate or error): {e}"
            )
            self.conn.rollback()
            return False

    def _update_application_outcome(
        self,
        application_id: int,
        outcome: str,
        confidence: float,
        message_id: str,
        subject: str,
        sender: str,
        received_at: str,
    ) -> None:
        """Apply outcome updates with timestamp/priority guards."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT outcome, outcome_email_received_at
            FROM applications
            WHERE id = %s
        """,
            (application_id,),
        )
        row = cursor.fetchone()
        if not row:
            logger.debug(f"Matched application {application_id} no longer exists")
            return

        current_outcome = row.get("outcome") or "PENDING"
        current_received_at = row.get("outcome_email_received_at")

        if not self._should_update_outcome(
            current_outcome=current_outcome,
            current_received_at=current_received_at,
            new_outcome=outcome,
            new_received_at=received_at,
        ):
            return

        stage = self._map_outcome_to_stage(outcome)
        cursor.execute(
            """
            UPDATE applications
            SET outcome = %s,
                outcome_confidence = %s,
                outcome_email_message_id = %s,
                outcome_email_subject = %s,
                outcome_email_from = %s,
                outcome_email_received_at = %s,
                outcome_updated_at = %s,
                outcome_stage = %s,
                outcome_date = %s,
                updated_at = %s,
                last_modified = %s
            WHERE id = %s
        """,
            (
                outcome,
                float(confidence or 0.0),
                message_id,
                subject,
                sender,
                received_at,
                datetime.now().isoformat(),
                stage,
                (received_at or "")[:10] if received_at else None,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                application_id,
            ),
        )

    @staticmethod
    def _map_outcome_to_stage(outcome: str) -> str:
        """Map legacy outcome (PENDING/CALLBACK/...) to normalized stage."""
        mapping = {
            "PENDING": "applied",
            "CALLBACK": "interview_request",
            "INTERVIEW": "interview_request",
            "REJECTION": "rejected",
            "OFFER": "offer",
        }
        return mapping.get(str(outcome or "").upper(), "applied")

    @staticmethod
    def _should_update_outcome(
        current_outcome: str,
        current_received_at: Optional[str],
        new_outcome: str,
        new_received_at: Optional[str],
    ) -> bool:
        """Return True when the new outcome should replace the current one."""
        priority = {
            "PENDING": 0,
            "REJECTION": 1,
            "CALLBACK": 2,
            "INTERVIEW": 3,
            "OFFER": 4,
        }

        if not current_received_at:
            return True
        if not new_received_at:
            return priority.get(new_outcome, 0) >= priority.get(current_outcome, 0)

        try:
            current_dt = datetime.fromisoformat(str(current_received_at))
            new_dt = datetime.fromisoformat(str(new_received_at))
        except ValueError:
            return priority.get(new_outcome, 0) >= priority.get(current_outcome, 0)

        if new_dt > current_dt:
            return True
        if new_dt < current_dt:
            return False

        return priority.get(new_outcome, 0) >= priority.get(current_outcome, 0)

    def get_application_outcome_stats(self) -> Dict:
        """Return aggregate statistics for tracked application outcomes."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM applications")
            total_row = cursor.fetchone()
            total = int(total_row.get("count", 0) if total_row else 0)

            cursor.execute(
                "SELECT outcome_stage, COUNT(*) AS count FROM applications GROUP BY outcome_stage"
            )
            by_stage = {
                str(row.get("outcome_stage") or "applied"): int(row.get("count", 0))
                for row in cursor.fetchall()
            }

            resolved = total - by_stage.get("applied", 0)
            positive = (
                by_stage.get("viewed", 0)
                + by_stage.get("interview_request", 0)
                + by_stage.get("offer", 0)
            )
            conversion_rate = (positive / resolved) if resolved else 0.0

            by_outcome = {
                "PENDING": by_stage.get("applied", 0),
                "ACKNOWLEDGED": by_stage.get("acknowledged", 0),
                "VIEWED": by_stage.get("viewed", 0),
                "REJECTION": by_stage.get("rejected", 0),
                "INTERVIEW": by_stage.get("interview_request", 0),
                "OFFER": by_stage.get("offer", 0),
                "GHOST": by_stage.get("ghost", 0),
            }

            return {
                "total": total,
                "resolved": resolved,
                "positive": positive,
                "conversion_rate": conversion_rate,
                "by_outcome": by_outcome,
                "by_stage": by_stage,
            }
        except Exception as e:
            logger.error(f"Error reading application outcome stats: {e}")
            return {
                "total": 0,
                "resolved": 0,
                "positive": 0,
                "conversion_rate": 0.0,
                "by_outcome": {},
                "by_stage": {},
            }

    def get_ghosted_applications(self, limit: int = 50) -> List[Dict]:
        """Return applications with no signal after 30+ days (ghosted)."""
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM applications
                WHERE market_intelligence_only = 0
                  AND below_threshold = 0
                  AND outcome_stage = 'applied'
                  AND date_applied IS NOT NULL
                  AND date_applied < %s
                ORDER BY date_applied ASC
                LIMIT %s
            """,
                (cutoff, max(1, int(limit))),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading ghosted applications: {e}")
            return []

    def get_sync_state(self, key: str) -> Optional[str]:
        """Get a sync cursor/state value by key."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value FROM sync_state WHERE key = %s", (key,))
            row = cursor.fetchone()
            return str(row.get("value")) if row else None
        except Exception as e:
            logger.error(f"Error reading sync state '{key}': {e}")
            return None

    def set_sync_state(self, key: str, value: str) -> bool:
        """Upsert a sync cursor/state value by key."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO sync_state (key, value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """,
                (key, value, datetime.now().isoformat()),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error writing sync state '{key}': {e}")
            self.conn.rollback()
            return False

    def get_job_record(self, record_id: int) -> Optional[Dict]:
        """Fetch a single job record by internal database id."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT j.*, c.name AS company_name
                FROM jobs j
                LEFT JOIN companies c ON j.company_id = c.id
                WHERE j.id = %s
            """,
                (int(record_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error fetching job record {record_id}: {e}")
            return None

    def get_application_by_seek_job_id(self, seek_job_id: str) -> Optional[Dict]:
        """Find an application by Seek job identifier."""
        if not seek_job_id:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM applications
                WHERE seek_job_id = %s OR job_id = %s
                ORDER BY applied_at DESC
                LIMIT 1
            """,
                (seek_job_id, seek_job_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(
                f"Error fetching application by seek_job_id {seek_job_id}: {e}"
            )
            return None

    def get_recent_applications_for_matching(self, days: int = 120) -> List[Dict]:
        """Fetch recent applied records used for email/phone matching cascades."""
        window_start = (
            (datetime.now() - timedelta(days=max(1, days))).date().isoformat()
        )
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM applications
                WHERE date_applied >= %s
                   OR applied_at >= %s
                ORDER BY applied_at DESC
            """,
                (window_start, f"{window_start}T00:00:00"),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading recent applications for matching: {e}")
            return []

    def get_queue_summary(self) -> Dict[str, Dict[str, float]]:
        """Return queued application counts grouped by archetype."""
        summary: Dict[str, Dict[str, float]] = {}
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT archetype_primary, archetype_scores, score,
                       market_intelligence_only, below_threshold
                FROM jobs
                WHERE status IN ('DISCOVERED', 'APP_ERROR')
                  AND quick_apply = 1
            """
            )
            rows = cursor.fetchall()
            for row in rows:
                archetype = (row.get("archetype_primary") or "unknown").strip().lower()
                scores = self._safe_json_load(row.get("archetype_scores"), {})
                # Aggregate both "can't apply" buckets into market_intel for
                # the dashboard. Splitting adds noise without changing user
                # action (neither is applyable via auto-apply).
                excluded = bool(row.get("market_intelligence_only")) or bool(
                    row.get("below_threshold")
                )
                bucket = "market_intel" if excluded else archetype
                if bucket not in summary:
                    summary[bucket] = {"count": 0.0, "score_sum": 0.0}

                primary_score = 0.0
                if isinstance(scores, dict) and archetype in scores:
                    try:
                        primary_score = float(scores[archetype])
                    except Exception:
                        primary_score = 0.0
                if primary_score <= 0:
                    try:
                        primary_score = float(row.get("score") or 0) / 100.0
                    except Exception:
                        primary_score = 0.0

                summary[bucket]["count"] += 1
                summary[bucket]["score_sum"] += primary_score

            for bucket, values in summary.items():
                count = values["count"]
                avg = values["score_sum"] / count if count else 0.0
                values["avg_score"] = round(avg, 3)

            return summary
        except Exception as e:
            logger.error(f"Error getting queue summary: {e}")
            return {}

    def get_queue_candidates(self, limit: int = 0) -> List[Dict]:
        """Return discoverable jobs that should be evaluated for queue gating."""
        try:
            query = (
                "SELECT j.*, c.name AS company_name FROM jobs j "
                "LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.status IN ('DISCOVERED', 'APP_ERROR') "
                "AND j.quick_apply = 1 "
                "ORDER BY j.priority_score DESC NULLS LAST, j.score DESC, j.created_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT %s"
                params.append(int(limit))
            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error loading queue candidates: {e}")
            return []

    def get_queued_jobs(
        self, archetype: Optional[str] = None, limit: int = 200
    ) -> List[Dict]:
        """Get queued jobs optionally filtered by archetype."""
        try:
            query = (
                "SELECT j.*, c.name AS company_name FROM jobs j "
                "LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.status IN ('DISCOVERED', 'APP_ERROR') "
                "AND j.quick_apply = 1 AND COALESCE(j.market_intelligence_only, 0) = 0 "
                "AND COALESCE(j.below_threshold, 0) = 0"
            )
            params: List = []
            if archetype:
                query += " AND LOWER(COALESCE(j.archetype_primary, '')) = %s"
                params.append(archetype.strip().lower())
            query += " ORDER BY j.priority_score DESC NULLS LAST, j.score DESC, j.created_at DESC"
            if limit > 0:
                query += " LIMIT %s"
                params.append(int(limit))
            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting queued jobs: {e}")
            return []

    def get_close_call_jobs(self, limit: int = 50) -> List[Dict]:
        """Return queued jobs where variant selection needs manual review."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT j.*, c.name AS company_name
                FROM jobs j
                LEFT JOIN companies c ON j.company_id = c.id
                WHERE j.status IN ('DISCOVERED', 'APP_ERROR')
                  AND j.quick_apply = 1
                  AND COALESCE(j.market_intelligence_only, 0) = 0
                  AND COALESCE(j.below_threshold, 0) = 0
                  AND COALESCE(j.selection_needs_review, 0) = 1
                ORDER BY j.priority_score DESC NULLS LAST, j.score DESC, j.created_at DESC
                LIMIT %s
            """,
                (max(1, int(limit)),),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting close-call jobs: {e}")
            return []

    def create_application_batch(
        self, archetype: str, profile_state: str
    ) -> Optional[int]:
        """Create a new application batch and return its id."""
        started_at = datetime.now().isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO application_batches (archetype, profile_state, batch_start_date)
                VALUES (%s, %s, %s)
                RETURNING id
            """,
                (archetype, profile_state, started_at),
            )
            batch_id = int(cursor.fetchone()["id"])
            self.conn.commit()
            return batch_id
        except Exception as e:
            logger.error(f"Error creating application batch: {e}")
            self.conn.rollback()
            return None

    def finalize_application_batch(self, batch_id: int, application_count: int) -> bool:
        """Mark batch as finished and set final application count."""
        ended_at = datetime.now().isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE application_batches
                SET batch_end_date = %s, application_count = %s
                WHERE id = %s
            """,
                (ended_at, int(application_count), int(batch_id)),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error finalizing application batch {batch_id}: {e}")
            self.conn.rollback()
            return False

    def mark_job_applied(
        self,
        record_id: int,
        batch_id: Optional[int],
        profile_state: str,
        resume_variant_sent: str,
        resume_commit_hash: Optional[str],
    ) -> bool:
        """Persist application metadata back to queued jobs rows."""
        now = datetime.now().isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'APPLIED',
                    last_modified = %s,
                    application_batch_id = %s,
                    resume_archetype = %s,
                    resume_commit_hash = %s
                WHERE id = %s
            """,
                (
                    now,
                    batch_id,
                    resume_variant_sent,
                    resume_commit_hash,
                    int(record_id),
                ),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error marking job {record_id} applied: {e}")
            self.conn.rollback()
            return False

    def get_resume_variant(self, archetype: str) -> Optional[Dict]:
        """Fetch resume variant metadata for one archetype."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM resume_variants WHERE archetype = %s",
                (archetype,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["embedding_vector"] = self._deserialize_vector(
                data.get("embedding_vector")
            )
            return data
        except Exception as e:
            logger.error(f"Error fetching resume variant {archetype}: {e}")
            return None

    def list_resume_variants(self) -> List[Dict]:
        """List all stored resume variant metadata records."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM resume_variants ORDER BY archetype ASC")
            rows = []
            for row in cursor.fetchall():
                data = dict(row)
                data["embedding_vector"] = self._deserialize_vector(
                    data.get("embedding_vector")
                )
                rows.append(data)
            return rows
        except Exception as e:
            logger.error(f"Error listing resume variants: {e}")
            return []

    def upsert_resume_variant(
        self,
        archetype: str,
        file_path: str,
        commit_hash: str,
        alignment_score: Optional[float] = None,
        embedding_vector=None,
        last_rewritten: Optional[str] = None,
    ) -> bool:
        """Upsert resume variant metadata used for drift checks and selection."""
        now = datetime.now().isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO resume_variants (
                    archetype, file_path, current_commit_hash, embedding_vector,
                    alignment_score, last_rewritten, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(archetype) DO UPDATE SET
                    file_path = excluded.file_path,
                    current_commit_hash = excluded.current_commit_hash,
                    embedding_vector = excluded.embedding_vector,
                    alignment_score = excluded.alignment_score,
                    last_rewritten = COALESCE(excluded.last_rewritten, resume_variants.last_rewritten),
                    updated_at = excluded.updated_at
            """,
                (
                    archetype,
                    file_path,
                    commit_hash,
                    self._serialize_vector(embedding_vector),
                    alignment_score,
                    last_rewritten,
                    now,
                    now,
                ),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting resume variant {archetype}: {e}")
            self.conn.rollback()
            return False

    def is_sender_ignored(self, sender_address: str, sender_domain: str) -> bool:
        """Return True when sender address/domain is listed in ignore list."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM sender_ignore_list
                WHERE LOWER(COALESCE(sender_address, '')) = LOWER(%s)
                   OR LOWER(COALESCE(sender_domain, '')) = LOWER(%s)
                LIMIT 1
            """,
                (sender_address or "", sender_domain or ""),
            )
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking sender ignore list: {e}")
            return False

    def add_sender_ignore(
        self,
        sender_address: Optional[str] = None,
        sender_domain: Optional[str] = None,
        reason: str = "",
    ) -> bool:
        """Add or update a sender ignore rule."""
        address = (sender_address or "").strip().lower()
        domain = (sender_domain or "").strip().lower()
        if not address and not domain:
            raise ValueError("sender_address or sender_domain is required")

        try:
            cursor = self.conn.cursor()
            if address:
                cursor.execute(
                    """
                    INSERT INTO sender_ignore_list (sender_address, sender_domain, reason)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(sender_address) DO UPDATE SET
                        sender_domain = excluded.sender_domain,
                        reason = excluded.reason
                """,
                    (address, domain or None, reason or ""),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO sender_ignore_list (sender_address, sender_domain, reason)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(sender_domain) DO UPDATE SET
                        sender_address = excluded.sender_address,
                        reason = excluded.reason
                """,
                    (None, domain, reason or ""),
                )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding sender ignore rule: {e}")
            self.conn.rollback()
            return False

    def list_sender_ignores(self, limit: int = 200) -> List[Dict]:
        """List sender ignore rules newest first."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT id, sender_address, sender_domain, reason, created_at
                FROM sender_ignore_list
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (max(1, int(limit)),),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error listing sender ignore rules: {e}")
            return []

    def upsert_known_sender(
        self,
        email_address: str,
        domain: str,
        company_name: Optional[str],
        sender_type: str = "unknown",
    ) -> bool:
        """Insert or update known sender information after confirmed matches."""
        if not email_address:
            return False
        first_seen = date.today().isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO known_senders (
                    email_address, domain, company_name, sender_type, first_seen_date
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(email_address) DO UPDATE SET
                    domain = excluded.domain,
                    company_name = COALESCE(excluded.company_name, known_senders.company_name),
                    sender_type = COALESCE(excluded.sender_type, known_senders.sender_type)
            """,
                (email_address, domain, company_name, sender_type, first_seen),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting known sender {email_address}: {e}")
            self.conn.rollback()
            return False

    def lookup_known_sender(self, email_address: str) -> Optional[Dict]:
        """Find known sender metadata by exact email address."""
        if not email_address:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM known_senders WHERE LOWER(email_address) = LOWER(%s)",
                (email_address,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error looking up known sender {email_address}: {e}")
            return None

    def get_known_sender_domains(
        self, company_name: str = "", limit: int = 20
    ) -> List[Dict]:
        """Return known sender domains ranked by sample count."""
        try:
            cursor = self.conn.cursor()
            if company_name:
                cursor.execute(
                    """
                    SELECT domain, COUNT(*) AS sample_count
                    FROM known_senders
                    WHERE domain IS NOT NULL
                      AND btrim(domain) <> ''
                      AND LOWER(COALESCE(company_name, '')) = LOWER(%s)
                    GROUP BY domain
                    ORDER BY sample_count DESC, domain ASC
                    LIMIT %s
                """,
                    (company_name, max(1, int(limit))),
                )
            else:
                cursor.execute(
                    """
                    SELECT domain, COUNT(*) AS sample_count
                    FROM known_senders
                    WHERE domain IS NOT NULL
                      AND btrim(domain) <> ''
                    GROUP BY domain
                    ORDER BY sample_count DESC, domain ASC
                    LIMIT %s
                """,
                    (max(1, int(limit)),),
                )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading known sender domains: {e}")
            return []

    def get_sender_locals_for_domain(self, domain: str, limit: int = 200) -> List[Dict]:
        """Return local-parts from known sender emails for one domain."""
        if not domain:
            return []
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT LOWER(split_part(email_address, '@', 1)) AS local_part
                FROM known_senders
                WHERE LOWER(domain) = LOWER(%s)
                  AND email_address LIKE %s
                LIMIT %s
            """,
                (domain, "%@%", max(1, int(limit))),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error reading sender locals for domain {domain}: {e}")
            return []

    def upsert_recruiter_contact(
        self,
        full_name: str = "",
        email: str = "",
        phone: str = "",
        linkedin_url: str = "",
        company_name: str = "",
        domain: str = "",
        source: str = "unknown",
        confidence: float = 0.0,
        notes: str = "",
    ) -> Optional[int]:
        """Upsert a recruiter contact and return recruiter id."""
        email_norm = str(email or "").strip().lower()
        linkedin_norm = str(linkedin_url or "").strip()
        domain_norm = str(domain or "").strip().lower()
        if not domain_norm and "@" in email_norm:
            domain_norm = email_norm.split("@", 1)[1]
        identity_key = self._build_recruiter_identity(
            full_name=full_name,
            email=email_norm,
            linkedin_url=linkedin_norm,
            company_name=company_name,
            domain=domain_norm,
        )
        if not identity_key:
            return None

        first_name, last_name = self._split_person_name(full_name)
        now = datetime.now().isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM recruiters WHERE identity_key = %s",
                (identity_key,),
            )
            existing = cursor.fetchone()
            if existing:
                row = dict(existing)
                merged_name = full_name or row.get("full_name") or ""
                merged_first, merged_last = self._split_person_name(merged_name)
                merged_email = email_norm or row.get("email") or ""
                merged_phone = phone or row.get("phone") or ""
                merged_linkedin = linkedin_norm or row.get("linkedin_url") or ""
                merged_company = company_name or row.get("company_name") or ""
                merged_domain = domain_norm or row.get("domain") or ""
                merged_conf = max(
                    float(row.get("confidence") or 0.0),
                    float(confidence or 0.0),
                )
                cursor.execute(
                    """
                    UPDATE recruiters
                    SET full_name = %s,
                        first_name = %s,
                        last_name = %s,
                        email = %s,
                        phone = %s,
                        linkedin_url = %s,
                        company_name = %s,
                        domain = %s,
                        source = COALESCE(NULLIF(%s, ''), source),
                        confidence = %s,
                        notes = COALESCE(NULLIF(%s, ''), notes),
                        updated_at = %s
                    WHERE id = %s
                """,
                    (
                        merged_name,
                        merged_first,
                        merged_last,
                        merged_email,
                        merged_phone,
                        merged_linkedin,
                        merged_company,
                        merged_domain,
                        source,
                        merged_conf,
                        notes,
                        now,
                        int(row.get("id")),
                    ),
                )
                self.conn.commit()
                return int(row.get("id"))

            cursor.execute(
                """
                INSERT INTO recruiters (
                    identity_key, full_name, first_name, last_name, email, phone,
                    linkedin_url, company_name, domain, source, confidence, notes,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    identity_key,
                    full_name or "",
                    first_name,
                    last_name,
                    email_norm,
                    phone or "",
                    linkedin_norm,
                    company_name or "",
                    domain_norm,
                    source or "unknown",
                    float(confidence or 0.0),
                    notes or "",
                    now,
                    now,
                ),
            )
            recruiter_id = int(cursor.fetchone()["id"])
            self.conn.commit()
            return recruiter_id
        except Exception as e:
            logger.error(f"Error upserting recruiter contact {identity_key}: {e}")
            self.conn.rollback()
            return None

    def link_job_to_recruiter(
        self,
        job_id: str,
        recruiter_id: int,
        relationship: str = "recruiter",
        confidence: float = 0.0,
        inferred_email: str = "",
        inference_rule: str = "",
    ) -> bool:
        """Link a job to recruiter contact with optional inferred email metadata."""
        if not job_id or not recruiter_id:
            return False
        now = datetime.now().isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO job_recruiter_links (
                    job_id, recruiter_id, relationship, confidence,
                    inferred_email, inference_rule, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(job_id, recruiter_id) DO UPDATE SET
                    relationship = excluded.relationship,
                    confidence = GREATEST(job_recruiter_links.confidence, excluded.confidence),
                    inferred_email = CASE
                        WHEN COALESCE(excluded.inferred_email, '') <> '' THEN excluded.inferred_email
                        ELSE job_recruiter_links.inferred_email
                    END,
                    inference_rule = CASE
                        WHEN COALESCE(excluded.inference_rule, '') <> '' THEN excluded.inference_rule
                        ELSE job_recruiter_links.inference_rule
                    END,
                    updated_at = excluded.updated_at
            """,
                (
                    job_id,
                    int(recruiter_id),
                    relationship or "recruiter",
                    float(confidence or 0.0),
                    inferred_email or "",
                    inference_rule or "",
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                UPDATE recruiters
                SET jobs_seen = (
                        SELECT COUNT(*) FROM job_recruiter_links WHERE recruiter_id = %s
                    ),
                    updated_at = %s
                WHERE id = %s
            """,
                (int(recruiter_id), now, int(recruiter_id)),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(
                f"Error linking job {job_id} to recruiter {recruiter_id}: {e}"
            )
            self.conn.rollback()
            return False

    def get_jobs_for_contact_intel(
        self, limit: int = 150, source: str = "", only_missing: bool = True
    ) -> List[Dict]:
        """Return recent jobs for contact extraction."""
        try:
            params: List = []
            query = (
                "SELECT j.job_id, j.title, j.description, j.source, j.url, "
                "j.created_at, j.score, c.name AS company_name "
                "FROM jobs j "
                "LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.description IS NOT NULL AND btrim(j.description) <> '' "
            )
            if source:
                query += "AND LOWER(COALESCE(j.source, '')) = %s "
                params.append(str(source).strip().lower())
            if only_missing:
                query += (
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM job_recruiter_links l WHERE l.job_id = j.job_id"
                    ") "
                )
            query += "ORDER BY j.created_at DESC "
            query += "LIMIT %s"
            params.append(max(1, int(limit)))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error loading jobs for contact intel: {e}")
            return []

    def find_recruiters_by_company(
        self, company_name: str, limit: int = 10
    ) -> List[Dict]:
        """Return known recruiters likely associated with a company/agency name."""
        needle = str(company_name or "").strip().lower()
        if not needle:
            return []
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM recruiters
                WHERE LOWER(COALESCE(company_name, '')) = LOWER(%s)
                   OR LOWER(COALESCE(company_name, '')) LIKE %s
                ORDER BY jobs_seen DESC, confidence DESC, updated_at DESC
                LIMIT %s
            """,
                (company_name, f"%{needle}%", max(1, int(limit))),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error finding recruiters by company {company_name}: {e}")
            return []

    def get_recruiter_outreach_candidates(
        self, limit: int = 50, source: str = ""
    ) -> List[Dict]:
        """Return ranked recruiter outreach candidates (email > inferred > LinkedIn)."""
        try:
            params: List = []
            query = """
                SELECT
                    j.job_id,
                    j.title,
                    j.source,
                    j.url,
                    j.score,
                    j.key_tools,
                    j.matching_keyword,
                    c.name AS company_name,
                    r.id AS recruiter_id,
                    r.full_name,
                    r.email,
                    r.phone,
                    r.linkedin_url,
                    r.domain,
                    r.company_name AS recruiter_company_name,
                    l.relationship,
                    l.confidence,
                    l.inferred_email,
                    l.inference_rule,
                    (
                        SELECT ol.status
                        FROM outreach_log ol
                        WHERE ol.job_id = j.job_id
                          AND ol.recruiter_id = r.id
                        ORDER BY ol.created_at DESC
                        LIMIT 1
                    ) AS last_outreach_status,
                    (
                        SELECT ol.created_at
                        FROM outreach_log ol
                        WHERE ol.job_id = j.job_id
                          AND ol.recruiter_id = r.id
                        ORDER BY ol.created_at DESC
                        LIMIT 1
                    ) AS last_outreach_at,
                    CASE
                        WHEN COALESCE(btrim(r.email), '') <> '' THEN 1
                        WHEN COALESCE(btrim(l.inferred_email), '') <> '' THEN 2
                        WHEN COALESCE(btrim(r.linkedin_url), '') <> '' THEN 3
                        WHEN COALESCE(btrim(r.full_name), '') <> '' THEN 4
                        ELSE 5
                    END AS contact_priority,
                    CASE
                        WHEN LOWER(COALESCE(c.name, '')) LIKE '%%recruit%%'
                          OR LOWER(COALESCE(c.name, '')) LIKE '%%staff%%'
                          OR LOWER(COALESCE(c.name, '')) LIKE '%%talent%%'
                          OR LOWER(COALESCE(c.name, '')) LIKE '%%agency%%'
                        THEN 1 ELSE 0
                    END AS job_company_is_agency
                FROM job_recruiter_links l
                JOIN recruiters r ON r.id = l.recruiter_id
                JOIN jobs j ON j.job_id = l.job_id
                LEFT JOIN companies c ON c.id = j.company_id
                WHERE 1 = 1
            """
            if source:
                query += " AND LOWER(COALESCE(j.source, '')) = %s "
                params.append(str(source).strip().lower())
            query += """
                ORDER BY
                    job_company_is_agency DESC,
                    contact_priority ASC,
                    COALESCE(j.score, 0) DESC,
                    COALESCE(l.confidence, 0) DESC,
                    COALESCE(j.created_at, '') DESC
                LIMIT %s
            """
            params.append(max(1, int(limit)))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error loading recruiter outreach candidates: {e}")
            return []

    def log_outreach_event(
        self,
        *,
        job_id: str,
        recruiter_id: int,
        channel: str,
        target: str,
        subject: str = "",
        body: str = "",
        status: str = "planned",
        error_message: str = "",
        sent_at: Optional[str] = None,
    ) -> Optional[int]:
        """Log a recruiter outreach attempt/event."""
        now = datetime.now().isoformat()
        sent_value = sent_at or (now if status == "sent" else None)
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO outreach_log (
                    job_id, recruiter_id, channel, target, subject, body,
                    status, error_message, created_at, sent_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    job_id or None,
                    int(recruiter_id) if recruiter_id else None,
                    channel,
                    target,
                    subject,
                    body,
                    status,
                    error_message,
                    now,
                    sent_value,
                ),
            )
            row = cursor.fetchone()
            if recruiter_id:
                cursor.execute(
                    """
                    UPDATE recruiters
                    SET outreach_state = %s,
                        last_outreach_at = %s,
                        updated_at = %s
                    WHERE id = %s
                """,
                    (
                        status if status else "planned",
                        sent_value or now,
                        now,
                        int(recruiter_id),
                    ),
                )
            self.conn.commit()
            return int(row["id"]) if row else None
        except Exception as e:
            logger.error(
                f"Error logging outreach event job={job_id} recruiter={recruiter_id}: {e}"
            )
            self.conn.rollback()
            return None

    def insert_parsed_email(self, parsed: Dict) -> Optional[int]:
        """Insert one parsed Gmail record into email_parsed."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO email_parsed (
                    gmail_message_id, date_received, sender_address, sender_domain,
                    subject, body_text, body_html, source_type,
                    outcome_classification, classification_confidence,
                    matched_application_id, match_method, requires_manual_review
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(gmail_message_id) DO NOTHING
                RETURNING id
            """,
                (
                    parsed.get("gmail_message_id"),
                    parsed.get("date_received"),
                    parsed.get("sender_address"),
                    parsed.get("sender_domain"),
                    parsed.get("subject"),
                    parsed.get("body_text"),
                    parsed.get("body_html"),
                    parsed.get("source_type", "unknown"),
                    parsed.get("outcome_classification"),
                    float(parsed.get("classification_confidence") or 0.0),
                    parsed.get("matched_application_id"),
                    parsed.get("match_method"),
                    int(bool(parsed.get("requires_manual_review"))),
                ),
            )
            row = cursor.fetchone()
            if not row:
                self.conn.rollback()
                return None
            self.conn.commit()
            return int(row["id"])
        except Exception as e:
            logger.error(
                f"Error inserting parsed email {parsed.get('gmail_message_id')}: {e}"
            )
            self.conn.rollback()
            return None

    def get_manual_review_emails(self, limit: int = 50) -> List[Dict]:
        """Return recent parsed emails requiring manual review."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM email_parsed
                WHERE requires_manual_review = 1
                ORDER BY date_received DESC
                LIMIT %s
            """,
                (max(1, int(limit)),),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching manual review emails: {e}")
            return []

    def resolve_manual_review_email_match(
        self,
        email_parsed_id: int,
        application_id: int,
        match_method: str = "manual",
    ) -> bool:
        """Confirm an email->application match and clear manual review flag."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM email_parsed WHERE id = %s", (email_parsed_id,)
            )
            email_row = cursor.fetchone()
            if not email_row:
                return False

            cursor.execute(
                "SELECT id, company_name FROM applications WHERE id = %s",
                (application_id,),
            )
            app_row = cursor.fetchone()
            if not app_row:
                return False

            cursor.execute(
                """
                UPDATE email_parsed
                SET matched_application_id = %s,
                    match_method = %s,
                    requires_manual_review = 0
                WHERE id = %s
            """,
                (application_id, match_method, email_parsed_id),
            )

            stage = (email_row.get("outcome_classification") or "other").strip()
            received = str(email_row.get("date_received") or "")
            outcome_date = received[:10] if received else None
            if stage and stage != "other":
                now = datetime.now().isoformat()
                stage_map = {
                    "applied": "PENDING",
                    "acknowledged": "CALLBACK",
                    "viewed": "CALLBACK",
                    "rejected": "REJECTION",
                    "interview_request": "INTERVIEW",
                    "offer": "OFFER",
                    "ghost": "PENDING",
                    "other": "PENDING",
                }
                cursor.execute(
                    """
                    UPDATE applications
                    SET outcome_stage = %s,
                        outcome_date = %s,
                        outcome_email_id = %s,
                        outcome = %s,
                        updated_at = %s,
                        last_modified = %s
                    WHERE id = %s
                """,
                    (
                        stage,
                        outcome_date,
                        str(email_parsed_id),
                        stage_map.get(stage, "PENDING"),
                        now,
                        now,
                        application_id,
                    ),
                )

            sender_address = (email_row.get("sender_address") or "").strip()
            sender_domain = (email_row.get("sender_domain") or "").strip()
            if sender_address:
                cursor.execute(
                    """
                    INSERT INTO known_senders (
                        email_address, domain, company_name, sender_type, first_seen_date
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(email_address) DO UPDATE SET
                        domain = excluded.domain,
                        company_name = COALESCE(excluded.company_name, known_senders.company_name),
                        sender_type = COALESCE(excluded.sender_type, known_senders.sender_type)
                """,
                    (
                        sender_address,
                        sender_domain,
                        app_row.get("company_name"),
                        "unknown",
                        date.today().isoformat(),
                    ),
                )

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error resolving manual review email match: {e}")
            self.conn.rollback()
            return False

    def update_application_outcome_stage(
        self,
        application_id: int,
        stage: str,
        outcome_date: Optional[str],
        outcome_email_id: Optional[str],
    ) -> bool:
        """Apply normalized outcome stage update on applications."""
        now = datetime.now().isoformat()
        stage_map = {
            "applied": "PENDING",
            "acknowledged": "CALLBACK",
            "viewed": "CALLBACK",
            "rejected": "REJECTION",
            "interview_request": "INTERVIEW",
            "offer": "OFFER",
            "ghost": "PENDING",
            "other": "PENDING",
        }
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE applications
                SET outcome_stage = %s,
                    outcome_date = %s,
                    outcome_email_id = %s,
                    outcome = %s,
                    updated_at = %s,
                    last_modified = %s
                WHERE id = %s
            """,
                (
                    stage,
                    outcome_date,
                    outcome_email_id,
                    stage_map.get(stage, "PENDING"),
                    now,
                    now,
                    int(application_id),
                ),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating application outcome stage: {e}")
            self.conn.rollback()
            return False

    def record_phone_call(
        self,
        phone_number: Optional[str],
        company_name: str,
        job_title: str,
        outcome: str,
        notes: str,
        call_date: str,
        matched_application_id: Optional[int] = None,
    ) -> Optional[int]:
        """Insert a phone call log and optionally update matched application."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO phone_call_log (
                    phone_number, company_name, job_title, outcome,
                    notes, call_date, matched_application_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    phone_number,
                    company_name,
                    job_title,
                    outcome,
                    notes,
                    call_date,
                    matched_application_id,
                ),
            )
            row = cursor.fetchone()
            call_id = int(row["id"]) if row else None

            if matched_application_id:
                mapped_stage = {
                    "screening_call": "interview_request",
                    "interview": "interview_request",
                    "rejection": "rejected",
                    "other": "other",
                }.get(outcome, "other")
                self.update_application_outcome_stage(
                    application_id=matched_application_id,
                    stage=mapped_stage,
                    outcome_date=call_date,
                    outcome_email_id=None,
                )

            self.conn.commit()
            return call_id
        except Exception as e:
            logger.error(f"Error recording phone call log: {e}")
            self.conn.rollback()
            return None

    def get_funnel_metrics(self) -> Dict:
        """Return funnel analytics used by feedback/status/apply dashboards."""
        ghost_cutoff = (date.today() - timedelta(days=30)).isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_applied,
                    SUM(CASE WHEN outcome_stage != 'applied' THEN 1 ELSE 0 END) AS any_response,
                    SUM(CASE WHEN outcome_stage = 'viewed' THEN 1 ELSE 0 END) AS viewed,
                    SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) AS interviews,
                    SUM(CASE WHEN outcome_stage = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                    SUM(
                        CASE
                            WHEN outcome_stage = 'applied'
                             AND date_applied < %s
                            THEN 1 ELSE 0
                        END
                    ) AS ghost
                FROM applications
                WHERE market_intelligence_only = 0
                  AND below_threshold = 0
            """,
                (ghost_cutoff,),
            )
            overview_row = cursor.fetchone()
            overview = dict(overview_row) if overview_row else {}

            cursor.execute(
                """
                SELECT
                    SUBSTRING(date_applied, 1, 7) AS month,
                    COUNT(*) AS applied,
                    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'viewed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS view_rate,
                    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) / COUNT(*), 1) AS interview_rate
                FROM applications
                WHERE market_intelligence_only = 0
                  AND below_threshold = 0
                  AND date_applied IS NOT NULL
                GROUP BY month
                ORDER BY month DESC
            """
            )
            by_month = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT
                    archetype_primary,
                    COUNT(*) AS applied,
                    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) / COUNT(*), 1) AS interview_rate
                FROM applications
                WHERE market_intelligence_only = 0
                  AND below_threshold = 0
                GROUP BY archetype_primary
            """
            )
            by_archetype = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT
                    resume_variant_sent AS archetype,
                    resume_commit_hash AS version,
                    COUNT(*) AS applications,
                    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'viewed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS view_rate,
                    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) / COUNT(*), 1) AS interview_rate,
                    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'rejected' THEN 1 ELSE 0 END) / COUNT(*), 1) AS rejection_rate
                FROM applications
                WHERE market_intelligence_only = 0
                  AND below_threshold = 0
                  AND date_applied IS NOT NULL
                GROUP BY resume_variant_sent, resume_commit_hash
                HAVING COUNT(*) >= 1
                ORDER BY archetype, version
            """
            )
            by_version = [dict(row) for row in cursor.fetchall()]

            return {
                "overview": overview,
                "by_month": by_month,
                "by_archetype": by_archetype,
                "by_version": by_version,
            }
        except Exception as e:
            logger.error(f"Error computing funnel metrics: {e}")
            return {
                "overview": {},
                "by_month": [],
                "by_archetype": [],
                "by_version": [],
            }

    def store_market_centroid(
        self,
        archetype: str,
        window_start: str,
        window_end: str,
        centroid_vector,
        jd_count: int,
        shift_from_previous: Optional[float],
        top_gained_terms: Optional[List[str]] = None,
        top_lost_terms: Optional[List[str]] = None,
    ) -> bool:
        """Upsert a weekly market centroid record for one archetype."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO market_centroids (
                    archetype, window_start, window_end, centroid_vector,
                    jd_count, shift_from_previous, top_gained_terms, top_lost_terms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(archetype, window_start) DO UPDATE SET
                    window_end = excluded.window_end,
                    centroid_vector = excluded.centroid_vector,
                    jd_count = excluded.jd_count,
                    shift_from_previous = excluded.shift_from_previous,
                    top_gained_terms = excluded.top_gained_terms,
                    top_lost_terms = excluded.top_lost_terms
            """,
                (
                    archetype,
                    window_start,
                    window_end,
                    self._serialize_vector(centroid_vector),
                    int(jd_count),
                    shift_from_previous,
                    json.dumps(top_gained_terms or []),
                    json.dumps(top_lost_terms or []),
                ),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error storing market centroid for {archetype}: {e}")
            self.conn.rollback()
            return False

    def get_most_recent_centroid(self, archetype: str) -> Optional[Dict]:
        """Return most recent centroid row for an archetype."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM market_centroids
                WHERE archetype = %s
                ORDER BY window_start DESC
                LIMIT 1
            """,
                (archetype,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["centroid_vector"] = self._deserialize_vector(
                data.get("centroid_vector")
            )
            data["top_gained_terms"] = self._safe_json_load(
                data.get("top_gained_terms"), []
            )
            data["top_lost_terms"] = self._safe_json_load(
                data.get("top_lost_terms"), []
            )
            return data
        except Exception as e:
            logger.error(f"Error fetching most recent centroid for {archetype}: {e}")
            return None

    def get_previous_centroid(self, archetype: str) -> Optional[Dict]:
        """Return second most recent centroid row for an archetype."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM market_centroids
                WHERE archetype = %s
                ORDER BY window_start DESC
                LIMIT 1 OFFSET 1
            """,
                (archetype,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["centroid_vector"] = self._deserialize_vector(
                data.get("centroid_vector")
            )
            return data
        except Exception as e:
            logger.error(f"Error fetching previous centroid for {archetype}: {e}")
            return None

    def get_embeddings_for_archetype_window(
        self, archetype: str, window_start: str, window_end: str
    ) -> List[List[float]]:
        """Load JD embeddings for archetype within a date window."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT embedding_vector
                FROM jobs
                WHERE archetype_primary = %s
                  AND SUBSTRING(created_at, 1, 10) BETWEEN %s AND %s
                  AND embedding_vector IS NOT NULL
            """,
                (archetype, window_start, window_end),
            )
            vectors: List[List[float]] = []
            for row in cursor.fetchall():
                decoded = self._deserialize_vector(row.get("embedding_vector"))
                if decoded:
                    vectors.append(decoded)
            return vectors
        except Exception as e:
            logger.error(f"Error fetching embeddings for {archetype}: {e}")
            return []

    def create_drift_alert(
        self,
        archetype: str,
        alert_type: str,
        metric_value: float,
        threshold_value: float,
        details: Dict,
    ) -> Optional[int]:
        """Create a drift alert record and return its id."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO drift_alerts (
                    archetype, alert_type, metric_value,
                    threshold_value, details, acknowledged
                ) VALUES (%s, %s, %s, %s, %s, 0)
                RETURNING id
            """,
                (
                    archetype,
                    alert_type,
                    float(metric_value),
                    float(threshold_value),
                    json.dumps(details or {}),
                ),
            )
            row = cursor.fetchone()
            self.conn.commit()
            return int(row["id"]) if row else None
        except Exception as e:
            logger.error(f"Error creating drift alert: {e}")
            self.conn.rollback()
            return None

    def get_recent_unacknowledged_alert(
        self,
        archetype: str,
        alert_type: str,
        within_days: int = 30,
    ) -> Optional[Dict]:
        """Return most recent unacknowledged alert matching filters."""
        cutoff = (datetime.now() - timedelta(days=max(1, within_days))).isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM drift_alerts
                WHERE archetype = %s
                  AND alert_type = %s
                  AND acknowledged = 0
                  AND created_at >= %s
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (archetype, alert_type, cutoff),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["details"] = self._safe_json_load(data.get("details"), {})
            return data
        except Exception as e:
            logger.error(f"Error reading unacknowledged alert: {e}")
            return None

    def get_unacknowledged_alerts(self) -> List[Dict]:
        """List unacknowledged drift alerts newest first."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM drift_alerts
                WHERE acknowledged = 0
                ORDER BY created_at DESC
            """
            )
            rows: List[Dict] = []
            for row in cursor.fetchall():
                data = dict(row)
                data["details"] = self._safe_json_load(data.get("details"), {})
                rows.append(data)
            return rows
        except Exception as e:
            logger.error(f"Error reading drift alerts: {e}")
            return []

    def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark a drift alert as acknowledged."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE drift_alerts SET acknowledged = 1 WHERE id = %s",
                (int(alert_id),),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error acknowledging alert {alert_id}: {e}")
            self.conn.rollback()
            return False

    def close(self) -> None:
        """Close database connection."""
        try:
            if self.conn:
                self.conn.close()
        finally:
            logger.debug("Postgres connection closed")

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
