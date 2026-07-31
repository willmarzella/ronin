"""SQLite integration for job management."""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger


_CAPTURE_EXTERNAL_CACHE: Optional[bool] = None


def _capture_external_enabled() -> bool:
    """Whether external (non-quick-apply) jobs should be kept addressable.

    Reads ``scraping.capture_external`` once and caches it. When True, external
    jobs are stored as ordinary rows (not buried as market-intelligence-only)
    so the agent applier can pick them up. Defaults to False, preserving the
    legacy behaviour of treating non-quick-apply jobs as market intel.
    """
    global _CAPTURE_EXTERNAL_CACHE
    if _CAPTURE_EXTERNAL_CACHE is None:
        try:
            from ronin.config import load_config

            cfg = load_config()
            _CAPTURE_EXTERNAL_CACHE = bool(
                cfg.get("scraping", {}).get("capture_external", False)
            )
        except Exception:
            _CAPTURE_EXTERNAL_CACHE = False
    return _CAPTURE_EXTERNAL_CACHE


class SQLiteManager:
    """Manager for SQLite job database."""

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
        resume_profile_arch = cls._normalize_archetype_name(
            payload.get("resume_profile")
        )
        canonical = primary or resume_arch or resume_profile_arch or "builder"
        # archetype fields stay one of the four embedding archetypes for
        # analytics/feedback, but resume_profile may carry a role-specific
        # resume (e.g. solutions_engineer) that is intentionally not an
        # archetype; preserve it when explicitly provided.
        raw_profile = str(payload.get("resume_profile") or "").strip().lower()
        if raw_profile and raw_profile not in cls.ARCHETYPE_PROFILES:
            resume_profile = raw_profile
        else:
            resume_profile = canonical
        return {
            "archetype_primary": canonical,
            "resume_archetype": canonical,
            "resume_profile": resume_profile,
        }

    def __init__(self, db_path: Optional[str] = None):
        """Initialize SQLite database connection."""
        if db_path is None:
            # Check RONIN_HOME first, then fallback to project root
            from ronin.config import get_ronin_home

            ronin_home = str(get_ronin_home())
            user_db = os.path.join(ronin_home, "data", "ronin.db")
            project_db = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data",
                "ronin.db",
            )
            # Prefer user dir if it exists, otherwise use project root
            if os.path.exists(os.path.dirname(user_db)):
                db_path = user_db
            elif os.path.exists(os.path.dirname(project_db)):
                db_path = project_db
            else:
                db_path = user_db  # Will be created

        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

        logger.info(f"Connected to SQLite database: {db_path}")

        self._init_schema()
        self.existing_companies = {}

    def _init_schema(self):
        """Initialize database schema."""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                apply_type TEXT DEFAULT 'quick',
                apply_url TEXT,
                created_at TEXT,
                pay TEXT,
                type TEXT,
                location TEXT,
                status TEXT DEFAULT 'DISCOVERED',
                keywords TEXT,
                company_id INTEGER,
                recruiter_id INTEGER,
                open_job INTEGER DEFAULT 0,
                last_modified TEXT,
                job_classification TEXT DEFAULT 'SHORT_TERM',
                resume_profile TEXT DEFAULT 'builder',
                matching_keyword TEXT,
                resume_archetype TEXT DEFAULT 'builder',
                archetype_scores TEXT,
                archetype_primary TEXT,
                embedding_vector BLOB,
                job_type TEXT DEFAULT 'unknown',
                day_rate_or_salary TEXT,
                seniority_level TEXT DEFAULT 'unknown',
                tech_stack_tags TEXT,
                market_intelligence_only INTEGER DEFAULT 0,
                below_threshold INTEGER DEFAULT 0,
                selection_needs_review INTEGER DEFAULT 0,
                application_batch_id INTEGER,
                resume_commit_hash TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                seek_job_id TEXT,
                title TEXT NOT NULL,
                job_title TEXT,
                description TEXT,
                job_description_text TEXT,
                company_name TEXT,
                source TEXT,
                url TEXT,
                date_scraped DATE,
                date_applied DATE,
                job_type TEXT,
                day_rate_or_salary TEXT,
                seniority_level TEXT,
                tech_stack_tags TEXT,
                search_keyword_origin TEXT,
                archetype_scores TEXT,
                archetype_primary TEXT,
                embedding_vector BLOB,
                resume_profile TEXT DEFAULT 'builder',
                resume_archetype TEXT DEFAULT 'builder',
                resume_variant_sent TEXT,
                resume_commit_hash TEXT,
                profile_state_at_application TEXT,
                application_batch_id INTEGER,
                key_tools TEXT,
                matching_keyword TEXT,
                job_classification TEXT,
                applied_at TEXT,
                outcome TEXT DEFAULT 'PENDING',
                outcome_confidence REAL DEFAULT 0,
                outcome_email_message_id TEXT,
                outcome_email_subject TEXT,
                outcome_email_from TEXT,
                outcome_email_received_at TEXT,
                outcome_updated_at TEXT,
                outcome_stage TEXT DEFAULT 'applied',
                outcome_date DATE,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                sender TEXT,
                subject TEXT,
                received_at TEXT,
                outcome TEXT,
                confidence REAL DEFAULT 0,
                match_strategy TEXT,
                matched_application_id INTEGER,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_message_id TEXT UNIQUE NOT NULL,
                date_received TIMESTAMP NOT NULL,
                sender_address TEXT NOT NULL,
                sender_domain TEXT NOT NULL,
                subject TEXT,
                body_text TEXT,
                body_html TEXT,
                source_type TEXT NOT NULL,
                outcome_classification TEXT,
                classification_confidence REAL,
                matched_application_id INTEGER REFERENCES applications(id),
                match_method TEXT,
                requires_manual_review INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS known_senders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_address TEXT NOT NULL,
                domain TEXT NOT NULL,
                company_name TEXT,
                sender_type TEXT DEFAULT 'unknown',
                first_seen_date DATE NOT NULL,
                UNIQUE(email_address)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recruiters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                confidence REAL DEFAULT 0,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                recruiter_id INTEGER NOT NULL,
                relationship TEXT DEFAULT 'recruiter',
                confidence REAL DEFAULT 0,
                inferred_email TEXT,
                inference_rule TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, recruiter_id),
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (recruiter_id) REFERENCES recruiters(id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outreach_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                recruiter_id INTEGER,
                channel TEXT NOT NULL,
                target TEXT,
                subject TEXT,
                body TEXT,
                status TEXT DEFAULT 'planned',
                error_message TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (recruiter_id) REFERENCES recruiters(id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resume_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archetype TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                current_commit_hash TEXT NOT NULL,
                embedding_vector BLOB,
                alignment_score REAL,
                last_rewritten DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS market_centroids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archetype TEXT NOT NULL,
                window_start DATE NOT NULL,
                window_end DATE NOT NULL,
                centroid_vector BLOB NOT NULL,
                jd_count INTEGER NOT NULL,
                shift_from_previous REAL,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archetype TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                metric_value REAL NOT NULL,
                threshold_value REAL NOT NULL,
                details TEXT,
                acknowledged INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS application_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archetype TEXT NOT NULL,
                profile_state TEXT NOT NULL,
                batch_start_date TIMESTAMP NOT NULL,
                batch_end_date TIMESTAMP,
                application_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS phone_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT,
                company_name TEXT,
                job_title TEXT,
                outcome TEXT,
                notes TEXT,
                call_date DATE NOT NULL,
                matched_application_id INTEGER REFERENCES applications(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_job_id ON jobs(job_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name)"
        )
        # Compound index for pending jobs query (status + quick_apply + score)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_pending ON jobs(status, quick_apply, score DESC)"
        )
        # Index for job classification
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_classification ON jobs(job_classification)"
        )
        # Migrations: add columns if they don't exist on older databases
        for col, col_type, default in [
            ("job_classification", "TEXT", "'SHORT_TERM'"),
            ("resume_profile", "TEXT", "'builder'"),
            ("key_tools", "TEXT", "''"),
            ("matching_keyword", "TEXT", "''"),
            ("resume_archetype", "TEXT", "'builder'"),
            ("archetype_scores", "TEXT", "NULL"),
            ("archetype_primary", "TEXT", "NULL"),
            ("embedding_vector", "BLOB", "NULL"),
            ("job_type", "TEXT", "'unknown'"),
            ("day_rate_or_salary", "TEXT", "NULL"),
            ("seniority_level", "TEXT", "'unknown'"),
            ("tech_stack_tags", "TEXT", "NULL"),
            ("market_intelligence_only", "INTEGER", "0"),
            ("below_threshold", "INTEGER", "0"),
            ("selection_needs_review", "INTEGER", "0"),
            ("application_batch_id", "INTEGER", "NULL"),
            ("resume_commit_hash", "TEXT", "NULL"),
            # Phase 1 (external apply): distinguish Seek-native "Quick apply"
            # from link-out "external" applications (Workday/PageUp/Greenhouse/
            # etc.) so the agent applier can pick them up. apply_url holds the
            # external destination once resolved (may be NULL until apply time).
            ("apply_type", "TEXT", "'quick'"),
            ("apply_url", "TEXT", "NULL"),
            # Outcome-weighted apply ordering. Recomputed by recompute_queue on
            # every apply run; NULL until then, which sorts last.
            ("priority_score", "REAL", "NULL"),
        ]:
            try:
                cursor.execute(f"SELECT {col} FROM jobs LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute(
                    f"ALTER TABLE jobs ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                logger.info(f"Migrated database: added jobs.{col} column")
                # Backfill: split overloaded market_intelligence_only column.
                # Rows with quick_apply=1 AND market_intelligence_only=1 were
                # demoted by queue threshold (not structurally non-quick-apply),
                # so move that signal to the new below_threshold column.
                if col == "below_threshold":
                    cursor.execute(
                        "UPDATE jobs SET below_threshold = 1, "
                        "market_intelligence_only = 0 "
                        "WHERE market_intelligence_only = 1 AND quick_apply = 1"
                    )
                    logger.info(
                        "Backfilled below_threshold from overloaded "
                        "market_intelligence_only column"
                    )
                # Backfill apply_type from the existing quick_apply flag so
                # legacy rows classify correctly the moment the column exists.
                if col == "apply_type":
                    cursor.execute(
                        "UPDATE jobs SET apply_type = "
                        "CASE WHEN quick_apply = 1 THEN 'quick' ELSE 'external' END"
                    )
                    logger.info("Backfilled jobs.apply_type from quick_apply flag")

        # Migrate data from old tech_stack column to key_tools
        try:
            cursor.execute("SELECT tech_stack FROM jobs LIMIT 1")
            # Old column exists — copy data to new column if key_tools is empty
            cursor.execute(
                "UPDATE jobs SET key_tools = tech_stack "
                "WHERE key_tools IS NULL OR key_tools = ''"
            )
            logger.info("Migrated tech_stack data to key_tools column")
        except sqlite3.OperationalError:
            pass  # tech_stack column doesn't exist (fresh DB)

        # Migrations: add columns for older applications tables
        for col, col_type, default in [
            ("seek_job_id", "TEXT", "NULL"),
            ("job_title", "TEXT", "NULL"),
            ("job_description_text", "TEXT", "NULL"),
            ("date_scraped", "DATE", "NULL"),
            ("date_applied", "DATE", "NULL"),
            ("job_type", "TEXT", "NULL"),
            ("day_rate_or_salary", "TEXT", "NULL"),
            ("seniority_level", "TEXT", "NULL"),
            ("tech_stack_tags", "TEXT", "NULL"),
            ("search_keyword_origin", "TEXT", "NULL"),
            ("archetype_scores", "TEXT", "NULL"),
            ("archetype_primary", "TEXT", "NULL"),
            ("embedding_vector", "BLOB", "NULL"),
            ("resume_variant_sent", "TEXT", "NULL"),
            ("resume_commit_hash", "TEXT", "NULL"),
            ("profile_state_at_application", "TEXT", "NULL"),
            ("application_batch_id", "INTEGER", "NULL"),
            ("resume_archetype", "TEXT", "'builder'"),
            ("matching_keyword", "TEXT", "''"),
            ("outcome", "TEXT", "'PENDING'"),
            ("outcome_confidence", "REAL", "0"),
            ("outcome_stage", "TEXT", "'applied'"),
            ("outcome_date", "DATE", "NULL"),
            ("outcome_email_id", "TEXT", "NULL"),
            ("market_intelligence_only", "INTEGER", "0"),
            ("below_threshold", "INTEGER", "0"),
            ("updated_at", "TEXT", "NULL"),
        ]:
            try:
                cursor.execute(f"SELECT {col} FROM applications LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute(
                    f"ALTER TABLE applications ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                logger.info(f"Migrated applications table: added applications.{col}")

        # Backfill denormalized fields used by feedback and drift tooling.
        cursor.execute(
            """
            UPDATE applications
            SET seek_job_id = COALESCE(seek_job_id, job_id),
                job_title = COALESCE(job_title, title),
                job_description_text = COALESCE(job_description_text, description),
                date_applied = COALESCE(date_applied, substr(applied_at, 1, 10)),
                outcome_stage = COALESCE(
                    outcome_stage,
                    CASE
                        WHEN outcome = 'PENDING' THEN 'applied'
                        WHEN outcome = 'REJECTION' THEN 'rejected'
                        WHEN outcome IN ('CALLBACK', 'INTERVIEW') THEN 'interview_request'
                        WHEN outcome = 'OFFER' THEN 'offer'
                        ELSE 'applied'
                    END
                ),
                updated_at = COALESCE(updated_at, last_modified)
            WHERE seek_job_id IS NULL
               OR job_title IS NULL
               OR job_description_text IS NULL
               OR date_applied IS NULL
               OR outcome_stage IS NULL
               OR updated_at IS NULL
        """
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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_below_threshold ON jobs(below_threshold)"
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
        logger.debug("Database schema initialized")

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
        """Serialize an embedding vector to bytes for SQLite BLOB storage."""
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
            if isinstance(vector_blob, bytes):
                payload = vector_blob.decode("utf-8")
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
        """Check if a job ID already exists in the database using EXISTS query."""
        job_id = str(job_id or "").strip()
        if not job_id:
            return False
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM jobs WHERE job_id = ? LIMIT 1", (job_id,))
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
                "SELECT id FROM companies WHERE LOWER(name) = LOWER(?)", (company_name,)
            )
            row = cursor.fetchone()

            if row:
                company_id = row[0]
                self.existing_companies[company_lower] = company_id
                return company_id

            cursor.execute(
                "INSERT INTO companies (name, created_at) VALUES (?, ?)",
                (company_name, datetime.now().isoformat()),
            )
            self.conn.commit()

            company_id = cursor.lastrowid
            self.existing_companies[company_lower] = company_id
            logger.debug(f"Created company: {company_name} (ID: {company_id})")

            return company_id

        except sqlite3.Error as e:
            logger.error(f"Error getting/creating company '{company_name}': {e}")
            return None

    def insert_job(self, job_data: Dict) -> bool:
        """Insert a job into database if it doesn't exist."""
        job_id = str(job_data.get("job_id") or "").strip()

        if not job_id:
            logger.error("Missing job_id in job_data")
            return False

        # Use EXISTS query instead of in-memory set
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
            # Resolve the application type. Prefer an explicit value from the
            # scraper; otherwise derive from the quick_apply flag.
            apply_type = job_data.get("apply_type") or (
                "quick" if job_data.get("quick_apply", False) else "external"
            )
            apply_url = job_data.get("apply_url")
            # created_at is the POSTING date when the board exposes one. Scrapers
            # leave it empty rather than fabricating, so the fallback to scrape
            # time lives here — one place, and never a blank NOT NULL column.
            created_at = str(job_data.get("created_at") or "").strip()
            if not created_at:
                created_at = datetime.now().isoformat()
            # An external job is only "market intelligence only" (excluded from
            # every apply queue) if the analyzer said so — NOT merely because it
            # lacks Seek Quick Apply. When external capture is enabled the agent
            # applier handles these jobs, so keep them addressable. Legacy
            # behaviour (bury all non-quick jobs) is preserved when disabled.
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
                """INSERT INTO jobs (
                    job_id, title, description, score, key_tools, recommendation,
                    overview, url, source, quick_apply, apply_type, apply_url,
                    created_at, pay, type,
                    location, status, keywords, company_id, job_classification,
                    resume_profile, matching_keyword, resume_archetype,
                    archetype_scores, archetype_primary, embedding_vector, job_type,
                    day_rate_or_salary, seniority_level, tech_stack_tags,
                    market_intelligence_only, selection_needs_review,
                    application_batch_id, resume_commit_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    created_at,
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

            logger.info(f"Added job {job_id}: {job_data.get('title', '')[:50]}")
            return True

        except sqlite3.IntegrityError:
            # Race condition: job was inserted between check and insert
            logger.debug(f"Job {job_id} already exists (race condition)")
            return False
        except sqlite3.Error as e:
            logger.error(f"Error adding job {job_id} to database: {e}")
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
                ORDER BY j.priority_score DESC, j.score DESC, j.created_at DESC
                LIMIT ?
            """,
                (limit,),
            )

            jobs = []
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

        except sqlite3.Error as e:
            logger.error(f"Error getting pending jobs: {e}")
            return []

    def get_pending_external_jobs(
        self, limit: int = 10, min_score: int = 0
    ) -> List[Dict]:
        """Get external (link-out) jobs ready for the agent applier.

        Mirrors :meth:`get_pending_jobs` but selects ``apply_type = 'external'``
        instead of Seek Quick Apply rows. These are the Workday / PageUp /
        Greenhouse-style postings that the deterministic Seek applier cannot
        submit. ``min_score`` gates on the analyzer score so the agent only
        spends effort on jobs worth applying to.
        """
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
                AND COALESCE(j.score, 0) >= ?
                ORDER BY j.priority_score DESC, j.score DESC, j.created_at DESC
                LIMIT ?
            """,
                (min_score, limit),
            )

            jobs = []
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

        except sqlite3.Error as e:
            logger.error(f"Error getting pending external jobs: {e}")
            return []

    def get_external_jobs_report(self) -> List[Dict]:
        """Summarise captured external jobs grouped by company.

        Used by ``ronin status`` / ``ronin apply external --report`` to size how
        much of the pipeline is currently link-out (and therefore invisible to
        the Seek Quick Apply path). Ordered by count so the biggest gaps — the
        operator targets that mostly run PageUp/Workday — surface first.
        """
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
        except sqlite3.Error as e:
            logger.error(f"Error building external jobs report: {e}")
            return []

    def update_job_status(self, job_id: str, status: str) -> bool:
        """Update the status of a job by job_id."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = ?, last_modified = ?
                WHERE job_id = ?
            """,
                (status, datetime.now().isoformat(), job_id),
            )

            self.conn.commit()

            if cursor.rowcount > 0:
                logger.debug(f"Updated job {job_id} status to {status}")
                return True
            else:
                logger.warning(f"Job {job_id} not found for status update")
                return False

        except sqlite3.Error as e:
            logger.error(f"Error updating job status: {e}")
            self.conn.rollback()
            return False

    def expire_old_jobs(self, days: int = 30) -> int:
        """Mark still-pending jobs older than ``days`` as EXPIRED.

        Ads are taken down long before the queue drains, so a job that has sat
        unapplied for a month is almost certainly gone. Rows are kept — only the
        status changes — so the history stays available for outcome analytics.

        Only DISCOVERED and APP_ERROR are touched: APPLIED is history, and
        STALE/NEEDS_HUMAN/BLOCKED already record a more specific outcome.

        Args:
            days: Age in days, measured from the job's posting date
                (``created_at``), after which a pending job expires.

        Returns:
            The number of jobs newly marked EXPIRED.
        """
        if days <= 0:
            return 0
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'EXPIRED', last_modified = ?
                WHERE status IN ('DISCOVERED', 'APP_ERROR')
                  AND created_at IS NOT NULL
                  AND created_at < ?
                """,
                (datetime.now().isoformat(), cutoff),
            )
            self.conn.commit()
            count = cursor.rowcount or 0
            if count:
                logger.info(f"Expired {count} job(s) posted before {cutoff[:10]}")
            return count
        except sqlite3.Error as e:
            logger.error(f"Error expiring old jobs: {e}")
            self.conn.rollback()
            return 0

    def update_record(self, record_id: int, fields: dict) -> bool:
        """Update an existing job record by database ID."""
        if not fields:
            return False

        # Whitelist allowed field names to prevent SQL injection
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
            set_clause = ", ".join([f"{key} = ?" for key in safe_fields.keys()])
            values = list(safe_fields.values()) + [record_id]

            cursor = self.conn.cursor()
            cursor.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
            self.conn.commit()

            logger.debug(f"Updated record {record_id}")
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error updating record {record_id}: {e}")
            self.conn.rollback()
            return False

    def get_jobs_stats(self) -> Dict:
        """Get statistics about jobs in the database."""
        try:
            cursor = self.conn.cursor()
            stats = {}

            cursor.execute("SELECT COUNT(*) FROM jobs")
            stats["total_jobs"] = cursor.fetchone()[0]

            cursor.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
            stats["by_status"] = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT source, COUNT(*) FROM jobs GROUP BY source ORDER BY COUNT(*) DESC"
            )
            stats["by_source"] = {row[0]: row[1] for row in cursor.fetchall()}

            return stats

        except sqlite3.Error as e:
            logger.error(f"Error getting job stats: {e}")
            return {}

    def get_jobs_corpus(self, limit: int = 0) -> List[Dict]:
        """Return job rows for corpus analysis (broad, unfiltered).

        This intentionally does NOT filter on quick-apply or status; the corpus
        is meant to reflect what has been scraped/stored, not only what is
        currently queue-eligible.
        """
        try:
            query = (
                "SELECT id, job_id, title, created_at, status, quick_apply, source "
                "FROM jobs ORDER BY created_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT ?"
                params.append(int(limit))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                "WHERE j.description IS NOT NULL AND TRIM(j.description) <> '' "
                "ORDER BY j.created_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT ?"
                params.append(int(limit))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error reading jobs for labeling: {e}")
            return []

    def get_job_by_job_id(self, job_id: str) -> Optional[Dict]:
        """Return a single job row by job_id."""
        if not job_id:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT j.*, c.name AS company_name "
                "FROM jobs j LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.job_id = ?",
                (str(job_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Error reading job by job_id {job_id}: {e}")
            return None

    def get_existing_job_ids(self) -> set:
        """Get all existing job IDs. Use sparingly - prefer job_exists() for single checks."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT job_id FROM jobs")
        return {row[0] for row in cursor.fetchall()}

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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        except sqlite3.Error as e:
            logger.error(f"Error recording application submission for {job_id}: {e}")
            self.conn.rollback()
            return False

    def backfill_applications_from_applied_jobs(
        self,
        limit: int = 0,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Insert missing application rows for jobs already marked APPLIED.

        This is intended for existing users upgrading to the outcome-tracking
        system: older runs may have `jobs.status = APPLIED` but no corresponding
        rows in `applications`, which prevents Gmail matching.

        The operation is idempotent: it only inserts missing records and will
        not overwrite existing application rows.
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
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'APPLIED'")
            stats["applied_jobs"] = int(cursor.fetchone()[0])

            cursor.execute("SELECT COUNT(*) FROM applications")
            stats["applications_total"] = int(cursor.fetchone()[0])

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM jobs j
                WHERE j.status = 'APPLIED'
                  AND NOT EXISTS (
                    SELECT 1 FROM applications a WHERE a.job_id = j.job_id
                  )
            """
            )
            stats["missing"] = int(cursor.fetchone()[0])

            if dry_run or stats["missing"] == 0:
                return stats

            query = (
                "SELECT j.*, c.name AS company_name "
                "FROM jobs j LEFT JOIN companies c ON j.company_id = c.id "
                "WHERE j.status = 'APPLIED' "
                "AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.job_id = j.job_id) "
                "ORDER BY j.created_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT ?"
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
            insert_sql = (
                f"INSERT OR IGNORE INTO applications ({', '.join(columns)}) "
                f"VALUES ({', '.join(['?'] * len(columns))})"
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

        except sqlite3.Error as e:
            logger.error(f"Error backfilling applications: {e}")
            self.conn.rollback()
            return stats

    def get_applications_missing_archetype(self, limit: int = 0) -> List[Dict]:
        """Return application rows missing archetype_primary."""
        try:
            cursor = self.conn.cursor()
            query = (
                "SELECT * FROM applications "
                "WHERE (archetype_primary IS NULL OR TRIM(archetype_primary) = '') "
                "  AND ((job_description_text IS NOT NULL AND TRIM(job_description_text) <> '') "
                "       OR (description IS NOT NULL AND TRIM(description) <> '')) "
                "ORDER BY applied_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT ?"
                params.append(int(limit))

            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                SET archetype_primary = ?,
                    archetype_scores = ?,
                    updated_at = ?,
                    last_modified = ?
                WHERE id = ?
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
        except sqlite3.Error as e:
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
                placeholders = ", ".join("?" for _ in outcomes)
                query += f" WHERE outcome IN ({placeholders})"
                params.extend(outcomes)

            query += " ORDER BY applied_at DESC"
            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

        except sqlite3.IntegrityError:
            logger.debug(
                f"Outcome event {event.get('message_id')} already recorded, skipping"
            )
            return False
        except sqlite3.Error as e:
            logger.error(
                f"Error recording outcome event {event.get('message_id')}: {e}"
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
            WHERE id = ?
        """,
            (application_id,),
        )
        row = cursor.fetchone()
        if not row:
            logger.debug(f"Matched application {application_id} no longer exists")
            return

        current_outcome = row[0] or "PENDING"
        current_received_at = row[1]

        if not self._should_update_outcome(
            current_outcome=current_outcome,
            current_received_at=current_received_at,
            new_outcome=outcome,
            new_received_at=received_at,
        ):
            return

        cursor.execute(
            """
            UPDATE applications
            SET outcome = ?,
                outcome_confidence = ?,
                outcome_email_message_id = ?,
                outcome_email_subject = ?,
                outcome_email_from = ?,
                outcome_email_received_at = ?,
                outcome_updated_at = ?,
                outcome_stage = ?,
                outcome_date = ?,
                outcome_email_id = ?,
                updated_at = ?,
                last_modified = ?
            WHERE id = ?
        """,
            (
                outcome,
                confidence,
                message_id,
                subject,
                sender,
                received_at,
                datetime.now().isoformat(),
                self._map_outcome_to_stage(outcome),
                (received_at or datetime.now().isoformat())[:10],
                message_id,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                application_id,
            ),
        )

    @staticmethod
    def _map_outcome_to_stage(outcome: str) -> str:
        """Map legacy outcomes to normalized outcome stages."""
        normalized = (outcome or "").strip().upper()
        mapping = {
            "PENDING": "applied",
            "REJECTION": "rejected",
            "CALLBACK": "interview_request",
            "INTERVIEW": "interview_request",
            "OFFER": "offer",
            "ACKNOWLEDGED": "acknowledged",
            "VIEWED": "viewed",
        }
        return mapping.get(normalized, "other")

    def _should_update_outcome(
        self,
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
            current_dt = datetime.fromisoformat(current_received_at)
            new_dt = datetime.fromisoformat(new_received_at)
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

            cursor.execute("SELECT COUNT(*) FROM applications")
            total = int(cursor.fetchone()[0])

            cursor.execute(
                "SELECT outcome_stage, COUNT(*) FROM applications GROUP BY outcome_stage"
            )
            by_stage = {
                str(row[0] or "applied"): int(row[1]) for row in cursor.fetchall()
            }

            resolved = total - by_stage.get("applied", 0)
            positive = (
                by_stage.get("viewed", 0)
                + by_stage.get("interview_request", 0)
                + by_stage.get("offer", 0)
            )

            conversion_rate = (positive / resolved) if resolved else 0.0

            # Backward-compatible labels used by older status/report code paths.
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
        except sqlite3.Error as e:
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
                  AND date(date_applied) < date('now', '-30 days')
                ORDER BY date_applied ASC
                LIMIT ?
            """,
                (max(1, int(limit)),),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error reading ghosted applications: {e}")
            return []

    def get_sync_state(self, key: str) -> Optional[str]:
        """Get a sync cursor/state value by key."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value FROM sync_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error(f"Error reading sync state '{key}': {e}")
            return None

    def set_sync_state(self, key: str, value: str) -> bool:
        """Upsert a sync cursor/state value by key."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO sync_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """,
                (key, value, datetime.now().isoformat()),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
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
                WHERE j.id = ?
            """,
                (record_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
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
                WHERE seek_job_id = ? OR job_id = ?
                ORDER BY applied_at DESC
                LIMIT 1
            """,
                (seek_job_id, seek_job_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
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
                WHERE date_applied >= ?
                   OR applied_at >= ?
                ORDER BY applied_at DESC
            """,
                (window_start, f"{window_start}T00:00:00"),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                archetype = (row[0] or "unknown").strip().lower()
                scores = self._safe_json_load(row[1], {})
                # Aggregate both "can't apply" buckets into market_intel for
                # the dashboard. Splitting them adds noise without changing
                # the user's action (neither is applyable via auto-apply).
                excluded = bool(row[3]) or bool(row[4])
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
                        primary_score = float(row[2] or 0) / 100.0
                    except Exception:
                        primary_score = 0.0

                summary[bucket]["count"] += 1
                summary[bucket]["score_sum"] += primary_score

            for bucket, values in summary.items():
                count = values["count"]
                avg = values["score_sum"] / count if count else 0.0
                values["avg_score"] = round(avg, 3)

            return summary
        except sqlite3.Error as e:
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
                "ORDER BY j.priority_score DESC, j.score DESC, j.created_at DESC"
            )
            params: List = []
            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                query += " AND LOWER(COALESCE(j.archetype_primary, '')) = ?"
                params.append(archetype.strip().lower())
            query += " ORDER BY j.priority_score DESC, j.score DESC, j.created_at DESC"
            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                ORDER BY j.priority_score DESC, j.score DESC, j.created_at DESC
                LIMIT ?
            """,
                (max(1, int(limit)),),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                INSERT INTO application_batches (
                    archetype, profile_state, batch_start_date
                ) VALUES (?, ?, ?)
            """,
                (archetype, profile_state, started_at),
            )
            self.conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.Error as e:
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
                SET batch_end_date = ?, application_count = ?
                WHERE id = ?
            """,
                (ended_at, int(application_count), batch_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
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
                    last_modified = ?,
                    application_batch_id = ?,
                    resume_profile = COALESCE(resume_profile, ?),
                    resume_archetype = COALESCE(resume_archetype, ?),
                    resume_commit_hash = COALESCE(?, resume_commit_hash)
                WHERE id = ?
            """,
                (
                    now,
                    batch_id,
                    resume_variant_sent,
                    profile_state,
                    resume_commit_hash,
                    record_id,
                ),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error marking job {record_id} applied: {e}")
            self.conn.rollback()
            return False

    def get_resume_variant(self, archetype: str) -> Optional[Dict]:
        """Fetch resume variant metadata for one archetype."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM resume_variants WHERE archetype = ?",
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
        except sqlite3.Error as e:
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
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        except sqlite3.Error as e:
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
                WHERE LOWER(COALESCE(sender_address, '')) = LOWER(?)
                   OR LOWER(COALESCE(sender_domain, '')) = LOWER(?)
                LIMIT 1
            """,
                (sender_address or "", sender_domain or ""),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
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
                    VALUES (?, ?, ?)
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
                    VALUES (?, ?, ?)
                    ON CONFLICT(sender_domain) DO UPDATE SET
                        sender_address = excluded.sender_address,
                        reason = excluded.reason
                """,
                    (None, domain, reason or ""),
                )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
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
                LIMIT ?
            """,
                (max(1, int(limit)),),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email_address) DO UPDATE SET
                    domain = excluded.domain,
                    company_name = COALESCE(excluded.company_name, known_senders.company_name),
                    sender_type = COALESCE(excluded.sender_type, known_senders.sender_type)
            """,
                (email_address, domain, company_name, sender_type, first_seen),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
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
                "SELECT * FROM known_senders WHERE LOWER(email_address) = LOWER(?)",
                (email_address,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
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
                      AND TRIM(domain) <> ''
                      AND LOWER(COALESCE(company_name, '')) = LOWER(?)
                    GROUP BY domain
                    ORDER BY sample_count DESC, domain ASC
                    LIMIT ?
                """,
                    (company_name, max(1, int(limit))),
                )
            else:
                cursor.execute(
                    """
                    SELECT domain, COUNT(*) AS sample_count
                    FROM known_senders
                    WHERE domain IS NOT NULL
                      AND TRIM(domain) <> ''
                    GROUP BY domain
                    ORDER BY sample_count DESC, domain ASC
                    LIMIT ?
                """,
                    (max(1, int(limit)),),
                )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                SELECT DISTINCT LOWER(SUBSTR(email_address, 1, INSTR(email_address, '@') - 1)) AS local_part
                FROM known_senders
                WHERE LOWER(domain) = LOWER(?)
                  AND email_address LIKE '%@%'
                LIMIT ?
            """,
                (domain, max(1, int(limit))),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                "SELECT * FROM recruiters WHERE identity_key = ?",
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
                    SET full_name = ?,
                        first_name = ?,
                        last_name = ?,
                        email = ?,
                        phone = ?,
                        linkedin_url = ?,
                        company_name = ?,
                        domain = ?,
                        source = COALESCE(NULLIF(?, ''), source),
                        confidence = ?,
                        notes = COALESCE(NULLIF(?, ''), notes),
                        updated_at = ?
                    WHERE id = ?
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            recruiter_id = int(cursor.lastrowid)
            self.conn.commit()
            return recruiter_id
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, recruiter_id) DO UPDATE SET
                    relationship = excluded.relationship,
                    confidence = MAX(job_recruiter_links.confidence, excluded.confidence),
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
                        SELECT COUNT(*) FROM job_recruiter_links WHERE recruiter_id = ?
                    ),
                    updated_at = ?
                WHERE id = ?
            """,
                (int(recruiter_id), now, int(recruiter_id)),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
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
                "WHERE j.description IS NOT NULL AND TRIM(j.description) <> '' "
            )
            if source:
                query += "AND LOWER(COALESCE(j.source, '')) = ? "
                params.append(str(source).strip().lower())
            if only_missing:
                query += (
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM job_recruiter_links l WHERE l.job_id = j.job_id"
                    ") "
                )
            query += "ORDER BY j.created_at DESC "
            query += "LIMIT ?"
            params.append(max(1, int(limit)))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                WHERE LOWER(COALESCE(company_name, '')) = LOWER(?)
                   OR LOWER(COALESCE(company_name, '')) LIKE ?
                ORDER BY jobs_seen DESC, confidence DESC, updated_at DESC
                LIMIT ?
            """,
                (company_name, f"%{needle}%", max(1, int(limit))),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                        WHEN COALESCE(TRIM(r.email), '') <> '' THEN 1
                        WHEN COALESCE(TRIM(l.inferred_email), '') <> '' THEN 2
                        WHEN COALESCE(TRIM(r.linkedin_url), '') <> '' THEN 3
                        WHEN COALESCE(TRIM(r.full_name), '') <> '' THEN 4
                        ELSE 5
                    END AS contact_priority,
                    CASE
                        WHEN LOWER(COALESCE(c.name, '')) GLOB '*recruit*'
                          OR LOWER(COALESCE(c.name, '')) GLOB '*staff*'
                          OR LOWER(COALESCE(c.name, '')) GLOB '*talent*'
                          OR LOWER(COALESCE(c.name, '')) GLOB '*agency*'
                        THEN 1 ELSE 0
                    END AS job_company_is_agency
                FROM job_recruiter_links l
                JOIN recruiters r ON r.id = l.recruiter_id
                JOIN jobs j ON j.job_id = l.job_id
                LEFT JOIN companies c ON c.id = j.company_id
                WHERE 1 = 1
            """
            if source:
                query += " AND LOWER(COALESCE(j.source, '')) = ? "
                params.append(str(source).strip().lower())
            query += """
                ORDER BY
                    job_company_is_agency DESC,
                    contact_priority ASC,
                    COALESCE(j.score, 0) DESC,
                    COALESCE(l.confidence, 0) DESC,
                    COALESCE(j.created_at, '') DESC
                LIMIT ?
            """
            params.append(max(1, int(limit)))

            cursor = self.conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            if recruiter_id:
                cursor.execute(
                    """
                    UPDATE recruiters
                    SET outreach_state = ?,
                        last_outreach_at = ?,
                        updated_at = ?
                    WHERE id = ?
                """,
                    (
                        status if status else "planned",
                        sent_value or now,
                        now,
                        int(recruiter_id),
                    ),
                )
            self.conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            self.conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None
        except sqlite3.Error as e:
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
                LIMIT ?
            """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching manual review emails: {e}")
            return []

    def resolve_manual_review_email_match(
        self,
        email_parsed_id: int,
        application_id: int,
        match_method: str = "manual",
    ) -> bool:
        """Confirm an email->application match and clear manual review flag.

        This updates both:
        - ``email_parsed``: attaches matched_application_id and clears requires_manual_review
        - ``applications``: updates outcome_stage/outcome_date/outcome_email_id when applicable

        Args:
            email_parsed_id: Primary key from email_parsed.
            application_id: Primary key from applications.
            match_method: Stored into email_parsed.match_method (default: "manual").

        Returns:
            True if updated, False otherwise.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM email_parsed WHERE id = ?", (email_parsed_id,)
            )
            email_row = cursor.fetchone()
            if not email_row:
                return False

            cursor.execute(
                "SELECT id, company_name FROM applications WHERE id = ?",
                (application_id,),
            )
            app_row = cursor.fetchone()
            if not app_row:
                return False

            cursor.execute(
                """
                UPDATE email_parsed
                SET matched_application_id = ?,
                    match_method = ?,
                    requires_manual_review = 0
                WHERE id = ?
            """,
                (application_id, match_method, email_parsed_id),
            )

            # Apply outcome signal to the matched application (if this email is a signal).
            stage = (email_row["outcome_classification"] or "other").strip()
            received = str(email_row["date_received"] or "")
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
                    SET outcome_stage = ?,
                        outcome_date = ?,
                        outcome_email_id = ?,
                        outcome = ?,
                        updated_at = ?,
                        last_modified = ?
                    WHERE id = ?
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

            # Add sender to known_senders after confirmation.
            sender_address = (email_row["sender_address"] or "").strip()
            sender_domain = (email_row["sender_domain"] or "").strip()
            if sender_address:
                cursor.execute(
                    """
                    INSERT INTO known_senders (
                        email_address, domain, company_name, sender_type, first_seen_date
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(email_address) DO UPDATE SET
                        domain = excluded.domain,
                        company_name = COALESCE(excluded.company_name, known_senders.company_name),
                        sender_type = COALESCE(excluded.sender_type, known_senders.sender_type)
                """,
                    (
                        sender_address,
                        sender_domain,
                        app_row["company_name"],
                        "unknown",
                        date.today().isoformat(),
                    ),
                )

            self.conn.commit()
            return True
        except sqlite3.Error as e:
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
                SET outcome_stage = ?,
                    outcome_date = ?,
                    outcome_email_id = ?,
                    outcome = ?,
                    updated_at = ?,
                    last_modified = ?
                WHERE id = ?
            """,
                (
                    stage,
                    outcome_date,
                    outcome_email_id,
                    stage_map.get(stage, "PENDING"),
                    now,
                    now,
                    application_id,
                ),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
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
            call_id = int(cursor.lastrowid)

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
        except sqlite3.Error as e:
            logger.error(f"Error recording phone call log: {e}")
            self.conn.rollback()
            return None

    def get_funnel_metrics(self) -> Dict:
        """Return funnel analytics used by feedback/status/apply dashboards."""
        try:
            cursor = self.conn.cursor()
            overview_query = """
                SELECT
                    COUNT(*) AS total_applied,
                    SUM(CASE WHEN outcome_stage != 'applied' THEN 1 ELSE 0 END) AS any_response,
                    SUM(CASE WHEN outcome_stage = 'viewed' THEN 1 ELSE 0 END) AS viewed,
                    SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) AS interviews,
                    SUM(CASE WHEN outcome_stage = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                    SUM(
                        CASE
                            WHEN outcome_stage = 'applied'
                             AND date_applied < date('now', '-30 days')
                            THEN 1 ELSE 0
                        END
                    ) AS ghost
                FROM applications
                WHERE market_intelligence_only = 0
                  AND below_threshold = 0
            """
            cursor.execute(overview_query)
            overview_row = cursor.fetchone()
            overview = dict(overview_row) if overview_row else {}

            monthly_query = """
                SELECT
                    strftime('%Y-%m', date_applied) AS month,
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
            cursor.execute(monthly_query)
            by_month = [dict(row) for row in cursor.fetchall()]

            archetype_query = """
                SELECT
                    archetype_primary,
                    COUNT(*) AS applied,
                    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) / COUNT(*), 1) AS interview_rate
                FROM applications
                WHERE market_intelligence_only = 0
                  AND below_threshold = 0
                GROUP BY archetype_primary
            """
            cursor.execute(archetype_query)
            by_archetype = [dict(row) for row in cursor.fetchall()]

            version_query = """
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
                HAVING applications >= 1
                ORDER BY archetype, version
            """
            cursor.execute(version_query)
            by_version = [dict(row) for row in cursor.fetchall()]

            return {
                "overview": overview,
                "by_month": by_month,
                "by_archetype": by_archetype,
                "by_version": by_version,
            }
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        except sqlite3.Error as e:
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
                WHERE archetype = ?
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
        except sqlite3.Error as e:
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
                WHERE archetype = ?
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
        except sqlite3.Error as e:
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
                WHERE archetype_primary = ?
                  AND date(created_at) BETWEEN date(?) AND date(?)
                  AND embedding_vector IS NOT NULL
            """,
                (archetype, window_start, window_end),
            )
            vectors = []
            for row in cursor.fetchall():
                decoded = self._deserialize_vector(row[0])
                if decoded:
                    vectors.append(decoded)
            return vectors
        except sqlite3.Error as e:
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
                ) VALUES (?, ?, ?, ?, ?, 0)
            """,
                (
                    archetype,
                    alert_type,
                    float(metric_value),
                    float(threshold_value),
                    json.dumps(details or {}),
                ),
            )
            self.conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.Error as e:
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
                WHERE archetype = ?
                  AND alert_type = ?
                  AND acknowledged = 0
                  AND created_at >= ?
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
        except sqlite3.Error as e:
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
            rows = []
            for row in cursor.fetchall():
                data = dict(row)
                data["details"] = self._safe_json_load(data.get("details"), {})
                rows.append(data)
            return rows
        except sqlite3.Error as e:
            logger.error(f"Error reading drift alerts: {e}")
            return []

    def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark a drift alert as acknowledged."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE drift_alerts SET acknowledged = 1 WHERE id = ?",
                (alert_id,),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error acknowledging alert {alert_id}: {e}")
            self.conn.rollback()
            return False

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            pass


def get_db_manager(config: Optional[Dict] = None, allow_spool_fallback: bool = True):
    """Return a database manager for the configured backend.

    Backends:
    - sqlite (default): ~/.ronin/data/ronin.db
    - postgres: uses RONIN_DATABASE_DSN (or DATABASE_URL) or config.database.postgres.dsn
    """
    backend_env = (
        os.environ.get("RONIN_DB_BACKEND")
        or os.environ.get("RONIN_DATABASE_BACKEND")
        or ""
    )
    cfg = config
    if cfg is None:
        try:
            from ronin.config import load_config

            cfg = load_config()
        except Exception:
            cfg = {}

    backend = (
        backend_env
        or (cfg.get("database", {}) if isinstance(cfg, dict) else {}).get("backend")
        or "sqlite"
    )
    backend = str(backend).strip().lower()

    if backend in {"postgres", "postgresql", "pg"}:
        db_cfg = cfg.get("database", {}) if isinstance(cfg, dict) else {}
        postgres_cfg = db_cfg.get("postgres", {}) if isinstance(db_cfg, dict) else {}

        def _dsn_from_secret_json(secret_json: str) -> Optional[str]:
            try:
                payload = json.loads(secret_json or "")
            except Exception:
                return None
            if not isinstance(payload, dict):
                return None

            env_username = (
                os.environ.get("RONIN_DATABASE_USERNAME")
                or os.environ.get("RONIN_DATABASE_USER")
                or os.environ.get("RONIN_DB_USER")
                or os.environ.get("PGUSER")
            )
            env_password = (
                os.environ.get("RONIN_DATABASE_PASSWORD")
                or os.environ.get("RONIN_DB_PASSWORD")
                or os.environ.get("PGPASSWORD")
            )
            env_host = (
                os.environ.get("RONIN_DATABASE_HOST")
                or os.environ.get("RONIN_DB_HOST")
                or os.environ.get("PGHOST")
            )
            env_port = (
                os.environ.get("RONIN_DATABASE_PORT")
                or os.environ.get("RONIN_DB_PORT")
                or os.environ.get("PGPORT")
            )
            env_dbname = (
                os.environ.get("RONIN_DATABASE_NAME")
                or os.environ.get("RONIN_DB_NAME")
                or os.environ.get("PGDATABASE")
            )

            username = (
                payload.get("username")
                or payload.get("user")
                or payload.get("db_user")
                or payload.get("dbUsername")
                or env_username
            )
            password = payload.get("password") or payload.get("pass") or env_password
            host = (
                payload.get("host")
                or payload.get("hostname")
                or payload.get("address")
                or env_host
            )
            port_raw = payload.get("port") or env_port or 5432
            try:
                port = int(port_raw)
            except Exception:
                port = 5432
            dbname = (
                payload.get("dbname")
                or payload.get("db_name")
                or payload.get("database")
                or payload.get("dbName")
                or env_dbname
            )
            if not (username and password and host and dbname):
                return None

            try:
                from urllib.parse import quote

                user_q = quote(str(username), safe="")
                pass_q = quote(str(password), safe="")
            except Exception:
                user_q = str(username)
                pass_q = str(password)

            sslmode = (
                os.environ.get("RONIN_DATABASE_SSLMODE")
                or os.environ.get("PGSSLMODE")
                or "require"
            )
            sslmode = str(sslmode).strip() or "require"

            return f"postgresql://{user_q}:{pass_q}@{str(host)}:{port}/{str(dbname)}?sslmode={sslmode}"

        dsn = (
            os.environ.get("RONIN_DATABASE_DSN")
            or os.environ.get("DATABASE_URL")
            or (postgres_cfg.get("dsn") if isinstance(postgres_cfg, dict) else None)
            or (db_cfg.get("dsn") if isinstance(db_cfg, dict) else None)
        )

        if not dsn:
            secret_json = (
                os.environ.get("RONIN_RDS_SECRET_JSON")
                or os.environ.get("RONIN_DATABASE_SECRET_JSON")
                or os.environ.get("RONIN_RDS_SECRET")
                or ""
            )
            if secret_json:
                dsn = _dsn_from_secret_json(secret_json)

        if dsn and str(dsn).lstrip().startswith("{"):
            converted = _dsn_from_secret_json(str(dsn))
            if converted:
                dsn = converted
        if not dsn:
            raise ValueError(
                "Postgres backend selected but DSN is missing. "
                "Set RONIN_DATABASE_DSN (or DATABASE_URL), or configure database.postgres.dsn."
            )

        fallback_enabled = bool(
            allow_spool_fallback
            and (
                postgres_cfg.get("fallback_to_spool", True)
                if isinstance(postgres_cfg, dict)
                else True
            )
        )

        from ronin.db_postgres import PostgresManager

        try:
            return PostgresManager(dsn=str(dsn))
        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            if not fallback_enabled:
                raise

            from pathlib import Path

            from ronin.config import get_ronin_home

            spool_raw = (
                db_cfg.get("spool_path") if isinstance(db_cfg, dict) else None
            ) or "data/spool.db"
            spool_path = Path(str(spool_raw)).expanduser()
            if not spool_path.is_absolute():
                spool_path = (get_ronin_home() / spool_path).resolve()
            logger.warning(
                "Postgres unavailable; falling back to local spool DB. "
                f"spool={spool_path} error={exc}"
            )
            return SQLiteManager(db_path=str(spool_path))

    return SQLiteManager()
