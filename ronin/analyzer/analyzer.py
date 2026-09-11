"""Service for analyzing job postings using Anthropic Claude."""

import threading
from typing import Dict, Optional

import anthropic
from loguru import logger

from ronin.ai import _parse_json_response
from ronin.analyzer.archetype_classifier import ArchetypeClassifier
from ronin.feedback.analysis import OutcomeAnalytics
from ronin.profile import Profile, load_profile
from ronin.prompts import JOB_ANALYSIS_PROMPT
from ronin.prompts.generator import generate_job_analysis_prompt

ARCHETYPE_PROFILES = {"builder", "fixer", "operator", "translator"}


class JobAnalyzerService:
    """Service for analyzing job postings using Anthropic Claude."""

    def __init__(self, config: Dict, client=None):
        self.config = config
        self.client = client or anthropic.Anthropic()
        self.model = "claude-sonnet-4-6"
        self.profile: Optional[Profile] = None
        self._feedback_context = ""
        # analyze_job runs concurrently across threads; the embedding model is a
        # single shared torch module, so serialize the encode step.
        self._classifier_lock = threading.Lock()
        self.archetype_classifier = ArchetypeClassifier(
            enable_embeddings=bool(
                self.config.get("analysis", {}).get("enable_embeddings", True)
            ),
            embedding_model_name=self.config.get("analysis", {}).get(
                "embedding_model", "all-MiniLM-L6-v2"
            ),
        )

        try:
            self.profile = load_profile()
            self._system_prompt = generate_job_analysis_prompt(self.profile)
            # Use model from profile if configured
            if self.profile.ai.analysis_model:
                self.model = self.profile.ai.analysis_model
            logger.debug(f"Using dynamic prompt from profile (model: {self.model})")
        except FileNotFoundError:
            self._system_prompt = JOB_ANALYSIS_PROMPT
            logger.debug("No profile found, falling back to static prompt")
        except Exception as e:
            self._system_prompt = JOB_ANALYSIS_PROMPT
            logger.warning(f"Error loading profile, falling back to static prompt: {e}")

        self._feedback_context = self._load_feedback_context()
        if self._feedback_context:
            self._system_prompt = (
                f"{self._system_prompt}\n\n"
                "MARKET FEEDBACK SIGNALS (from historical outcomes):\n"
                f"{self._feedback_context}"
            )

    def _load_feedback_context(self) -> str:
        """Load compact outcome analytics context for prompt conditioning."""
        try:
            analytics = OutcomeAnalytics()
            context = analytics.build_prompt_context(
                max_lines=8,
                min_samples=self.config.get("analysis", {}).get(
                    "feedback_min_samples", 2
                ),
            )
            analytics.close()
            return context
        except Exception as e:
            logger.debug(f"Outcome feedback context unavailable: {e}")
            return ""

    def _rule_based_resume_hint(self, job_data: Dict) -> Optional[str]:
        if not self.profile:
            return None
        try:
            recommended = self.profile.recommend_resume_for_listing(
                job_title=job_data.get("title", ""),
                job_description=job_data.get("description", ""),
                work_type=job_data.get("work_type", ""),
            )
            return recommended.name
        except Exception as e:
            logger.debug(f"Rule-based resume hint unavailable: {e}")
            return None

    def _role_specific_resume_override(self, job_data: Dict) -> Optional[str]:
        """Return a custom (non-archetype) resume that matches this listing.

        Custom resumes take precedence over the four embedding archetypes, which
        only describe data-engineering JD *shapes* and would otherwise mis-route
        a "Sales Engineer" listing to builder/operator, or send the plain
        archetype copy to a contract that wants the cashflow/FinOps framing.

        Matching is delegated to the profile rule scorer, so title patterns,
        keyword bias and work type all count — see
        :meth:`Profile.select_custom_resume`.
        """
        if not self.profile or not self.profile.resumes:
            return None
        return self.profile.select_custom_resume(
            job_title=str(job_data.get("title", "")),
            job_description=str(job_data.get("description", "")),
            work_type=str(job_data.get("work_type", "")),
        )

    def _resolve_resume_profile(self, job_data: Dict, analysis: Dict) -> str:
        """Resolve resume fields to one canonical archetype profile."""
        candidate = (
            str(
                analysis.get("archetype_primary")
                or analysis.get("resume_archetype")
                or analysis.get("resume_profile")
                or ""
            )
            .strip()
            .lower()
        )

        if candidate not in ARCHETYPE_PROFILES:
            suggested = (
                str(self._rule_based_resume_hint(job_data) or "").strip().lower()
            )
            if suggested in ARCHETYPE_PROFILES:
                candidate = suggested
            else:
                if analysis.get("resume_profile"):
                    logger.debug(
                        "AI selected non-canonical resume_profile "
                        f"'{analysis.get('resume_profile')}', falling back to 'builder'"
                    )
                candidate = "builder"

        analysis["resume_profile"] = candidate
        analysis["resume_archetype"] = candidate
        return candidate

    def _enrich_with_archetype_signals(self, job_data: Dict, analysis: Dict) -> None:
        """Attach deterministic archetype+metadata signals to the AI analysis blob."""
        jd_text = job_data.get("description", "")
        job_title = job_data.get("title", "")
        if not jd_text:
            return

        try:
            with self._classifier_lock:
                classification = self.archetype_classifier.classify(
                    jd_text=jd_text,
                    job_title=job_title,
                )
            analysis["archetype_scores"] = classification.get("archetype_scores", {})
            analysis["archetype_primary"] = classification.get("archetype_primary")
            analysis["embedding_vector"] = classification.get("embedding_vector")
            analysis["job_type"] = classification.get("job_type", "unknown")
            analysis["tech_stack_tags"] = classification.get("tech_stack_tags", [])
            analysis["seniority_level"] = classification.get(
                "seniority_level", "unknown"
            )
            analysis["archetype_prior"] = classification.get("archetype_prior", {})
            analysis["day_rate_or_salary"] = job_data.get("pay_rate", "")
        except Exception as exc:
            logger.warning(f"Archetype enrichment failed for {job_title}: {exc}")

    def analyze_job(self, job_data: Dict) -> Optional[Dict]:
        """
        Analyze a job posting using Anthropic Claude.

        Args:
            job_data: Dictionary containing job information with a description field

        Returns:
            Dictionary containing the enriched job data with analysis,
            or None if analysis fails
        """
        job_id = job_data.get("job_id", "unknown")
        job_title = job_data.get("title", "unknown")

        logger.info(f"Starting job analysis for '{job_title}' (ID: {job_id})")

        if not job_data.get("description"):
            logger.error(
                f"Job {job_id} ({job_title}) has no description. Skipping analysis."
            )
            return None

        try:
            logger.debug(
                f"Making Anthropic API call for job {job_id} ({job_title}) using model: {self.model}"
            )

            rule_based_resume = self._rule_based_resume_hint(job_data)
            user_prompt = [
                f"Job title: {job_title}",
                f"Work type: {job_data.get('work_type', '')}",
                "Analyze this job description:",
                job_data["description"],
            ]
            if rule_based_resume:
                user_prompt.append(
                    f"Rule-based resume recommendation (heuristic): {rule_based_resume}"
                )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self._system_prompt
                + "\n\nIMPORTANT: Your response MUST be a valid JSON object only, no other text.",
                messages=[
                    {
                        "role": "user",
                        "content": "\n\n".join(user_prompt),
                    },
                ],
            )

            if not response:
                logger.error(
                    f"Failed to get analysis from Anthropic for job {job_id} ({job_title})"
                )
                return None

            content = response.content[0].text
            logger.debug(f"Received response from Anthropic for job {job_id}")

            try:
                analysis = _parse_json_response(content)
            except Exception as e:
                logger.error(f"Failed to parse JSON for job {job_id}: {e}")
                return None
            if analysis is None:
                return None

            resolved_resume_profile = self._resolve_resume_profile(job_data, analysis)
            self._enrich_with_archetype_signals(job_data, analysis)

            canonical_archetype = (
                str(
                    analysis.get("archetype_primary")
                    or analysis.get("resume_archetype")
                    or resolved_resume_profile
                    or ""
                )
                .strip()
                .lower()
            )
            if canonical_archetype not in ARCHETYPE_PROFILES:
                canonical_archetype = "builder"

            analysis["archetype_primary"] = canonical_archetype
            analysis["resume_archetype"] = canonical_archetype
            analysis["resume_profile"] = canonical_archetype
            resolved_resume_profile = canonical_archetype

            # A custom resume (matched on title patterns, keyword bias or work
            # type) overrides the embedding archetype for resume selection while
            # leaving the archetype fields intact for analytics/feedback.
            role_override = self._role_specific_resume_override(job_data)
            if role_override:
                logger.info(
                    f"Job {job_id}: custom resume '{role_override}' "
                    f"overrides archetype '{canonical_archetype}'"
                )
                analysis["resume_profile"] = role_override
                resolved_resume_profile = role_override

            enriched_job = job_data.copy()
            enriched_job["analysis"] = analysis

            # Seek "Strong applicant" recommendations: trust Seek's profile-match
            # signal over our AI scorer and force a passing score of 80, but only
            # for quick-apply roles (non-quick-apply stays market-intel only and
            # is never auto-applied). Done before the min-score gate so a strong
            # applicant is never dropped for a low AI score.
            STRONG_APPLICANT_SCORE = 80
            if job_data.get("strong_applicant") and job_data.get("quick_apply"):
                logger.info(
                    f"Job {job_id} ({job_title}): Seek 'Strong applicant' badge — "
                    f"overriding score {analysis.get('score')} -> "
                    f"{STRONG_APPLICANT_SCORE} (quick-apply)"
                )
                analysis["score"] = STRONG_APPLICANT_SCORE

            enriched_job["resume_profile"] = resolved_resume_profile

            min_score = self.config.get("analysis", {}).get("min_score", 0)
            job_score = analysis.get("score", 0)

            if job_score < min_score:
                logger.info(
                    f"Job {job_id} ({job_title}) score {job_score} below minimum {min_score}"
                )
                return None

            return enriched_job

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error for job {job_id}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Error analyzing job {job_id} ({job_title}): {str(e)}")
            return None
