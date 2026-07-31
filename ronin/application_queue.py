"""Queue gating and resume variant alignment services."""

from __future__ import annotations

import json
from typing import Dict, Optional, Tuple

from loguru import logger

from ronin.analyzer.archetype_classifier import ArchetypeClassifier, is_excluded_title
from ronin.db import get_db_manager
from ronin.profile import load_profile
from ronin.ranking import RankingPolicy
from ronin.resume_variants import ARCHETYPES, ResumeVariantManager


class ApplicationQueueService:
    """Recompute queue gating and keep resume variant metadata in sync."""

    def __init__(self, config: Dict, db_manager: Optional[object] = None):
        self.config = config or {}
        self.db = db_manager or get_db_manager(config=self.config)
        self._owns_db = db_manager is None

        self.classifier = ArchetypeClassifier(
            enable_embeddings=bool(
                self.config.get("analysis", {}).get("enable_embeddings", True)
            ),
            embedding_model_name=self.config.get("analysis", {}).get(
                "embedding_model", "all-MiniLM-L6-v2"
            ),
        )
        self.resume_manager = ResumeVariantManager(self.config)

        try:
            self.profile = load_profile()
        except Exception as exc:
            logger.debug(f"Profile unavailable for queue role overrides: {exc}")
            self.profile = None

    def _role_specific_resume(self, job: Dict) -> Optional[str]:
        """Return a custom (non-archetype) resume that matches this job.

        Must stay in step with ``JobAnalyzer._role_specific_resume_override``:
        ``recompute_queue`` re-derives ``resume_profile`` on every apply run, so
        a rule the analyzer honours and this does not would be silently undone.
        Both delegate to :meth:`Profile.select_custom_resume`.
        """
        if not self.profile or not getattr(self.profile, "resumes", None):
            return None
        return self.profile.select_custom_resume(
            job_title=str(job.get("title", "")),
            job_description=str(job.get("description", "")),
            work_type=str(job.get("work_type") or job.get("job_type") or ""),
        )

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def refresh_resume_variants(self) -> Dict[str, Dict]:
        """Recompute alignment for all archetypes and persist in DB."""
        variants = self.resume_manager.refresh_variants(self.classifier)
        persisted: Dict[str, Dict] = {}
        for archetype, payload in variants.items():
            ok = self.db.upsert_resume_variant(
                archetype=archetype,
                file_path=payload["file_path"],
                commit_hash=payload["current_commit_hash"],
                alignment_score=payload["alignment_score"],
                embedding_vector=payload["embedding_vector"],
                last_rewritten=payload.get("last_rewritten"),
            )
            if ok:
                persisted[archetype] = payload
        return persisted

    def select_variant(self, jd_archetype_scores: Dict[str, float]) -> Tuple[str, bool]:
        """Return selected archetype and whether review is needed."""
        sorted_scores = sorted(
            jd_archetype_scores.items(),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        if not sorted_scores:
            return "builder", True

        top = sorted_scores[0]
        second = sorted_scores[1] if len(sorted_scores) > 1 else (top[0], 0.0)
        needs_review = (float(top[1]) - float(second[1])) < 0.10
        return top[0], needs_review

    def recompute_queue(self, limit: int = 0) -> Dict[str, int]:
        """Apply queue gating thresholds to discovered jobs."""
        self.refresh_resume_variants()
        app_cfg = self.config.get("application", {}) or {}
        threshold = float(app_cfg.get("queue_threshold", 0.15))
        policy = RankingPolicy(self.config)

        # Retire ads too old to still be live before scoring the rest, so the
        # queue never spends browser time on a month-old posting.
        expired = self.db.expire_old_jobs(int(app_cfg.get("expire_after_days", 30)))

        candidates = self.db.get_queue_candidates(limit=limit)
        updated = 0
        market_intel = 0
        manual_review = 0
        excluded = 0

        for job in candidates:
            scores = self._get_job_scores(job)
            primary, needs_review = self.select_variant(scores)

            if policy.enabled:
                # Gate on the analyst score alone. Alignment is still refreshed
                # and recorded above, but it is a resume-quality measure and
                # multiplying it into the gate made throughput a function of how
                # the resumes embed rather than of job quality.
                intel_only = 1 if policy.is_below_bar(job) else 0
            else:
                primary_score = float(scores.get(primary, 0.0))
                variant = self.db.get_resume_variant(primary)
                alignment = (
                    float(variant.get("alignment_score") or 0.5) if variant else 0.5
                )
                intel_only = 1 if primary_score * alignment < threshold else 0

            # Roles we no longer target never queue, whatever they scored. The
            # four archetypes score these as noise, so a high score is an
            # artefact rather than a fit.
            if is_excluded_title(job.get("title", "")):
                intel_only = 1
                excluded += 1

            # A custom resume (title patterns, keyword bias or work type)
            # overrides the embedding archetype for resume selection; archetype
            # fields stay as the classifier output for analytics/feedback.
            resume_profile = self._role_specific_resume(job) or primary

            # Priority reads archetype_primary/seniority as just recomputed, not
            # the stale values on the row.
            priority = policy.priority(
                {
                    "score": job.get("score"),
                    "archetype_primary": primary,
                    "seniority_level": job.get("seniority_level"),
                }
            )

            fields = {
                "archetype_scores": json.dumps(scores),
                "archetype_primary": primary,
                "selection_needs_review": 1 if needs_review else 0,
                # below_threshold: this job is not worth applying to. Distinct
                # from market_intelligence_only, which means "structurally not
                # quick-apply on Seek" (set by cli/search.py).
                "below_threshold": intel_only,
                "resume_archetype": primary,
                "resume_profile": resume_profile,
                "priority_score": priority,
            }
            if self.db.update_record(job["id"], fields):
                updated += 1
                market_intel += intel_only
                manual_review += 1 if needs_review else 0

        return {
            "evaluated": len(candidates),
            "updated": updated,
            "market_intelligence": market_intel,
            "manual_review": manual_review,
            "expired": expired,
            "excluded_role": excluded,
        }

    def _get_job_scores(self, job: Dict) -> Dict[str, float]:
        raw_scores = self.db._safe_json_load(job.get("archetype_scores"), {})
        if isinstance(raw_scores, dict) and raw_scores:
            return {
                archetype: float(raw_scores.get(archetype, 0.0))
                for archetype in ARCHETYPES
            }

        try:
            classification = self.classifier.classify(
                jd_text=job.get("description", "") or "",
                job_title=job.get("title", "") or "",
            )
            update_fields = {
                "archetype_scores": json.dumps(classification["archetype_scores"]),
                "archetype_primary": classification["archetype_primary"],
                "embedding_vector": classification["embedding_vector"],
                "job_type": classification.get("job_type", "unknown"),
                "tech_stack_tags": json.dumps(
                    classification.get("tech_stack_tags", [])
                ),
                "seniority_level": classification.get("seniority_level", "unknown"),
            }
            self.db.update_record(job["id"], update_fields)
            return {
                archetype: float(classification["archetype_scores"].get(archetype, 0.0))
                for archetype in ARCHETYPES
            }
        except Exception as exc:
            logger.warning(f"Failed to classify job {job.get('job_id')}: {exc}")
            return {archetype: 0.25 for archetype in ARCHETYPES}
