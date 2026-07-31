"""Profile loader and validator for Ronin.

Loads user profile from ~/.ronin/profile.yaml (or the directory specified by
the RONIN_HOME environment variable) and validates it against the expected
schema using Pydantic v2 models.
"""

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from loguru import logger
from pydantic import BaseModel, Field, model_validator

from ronin.config import get_ronin_home


# The four embedding archetypes. A resume named anything else is a "custom"
# resume, selected by the profile.yaml rule signals rather than by JD shape.
ARCHETYPE_RESUME_NAMES = frozenset({"builder", "fixer", "operator", "translator"})

# Minimum rule score for a register-cut resume to override the archetype.
# A work-type match alone scores 2.0, which is deliberately NOT enough: every
# contract ad would take the contract resume and the archetypes would go unused.
# 3.0 means work type plus at least one keyword-bias hit.
_CUSTOM_RESUME_MIN_SCORE = 3.0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PersonalInfo(BaseModel):
    """Personal contact information."""

    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""


class WorkRights(BaseModel):
    """Work rights and legal status."""

    citizenship: str = ""
    visa_status: str = ""
    has_drivers_license: bool = False
    security_clearances: List[str] = Field(default_factory=list)
    willing_to_obtain_clearance: bool = False
    willing_to_relocate: bool = False
    willing_to_travel: bool = False
    police_check: str = ""
    notice_period: str = ""


class Preferences(BaseModel):
    """Job search preferences used for scoring and ranking."""

    high_value_signals: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    preferred_work_types: List[str] = Field(default_factory=list)
    preferred_arrangements: List[str] = Field(default_factory=list)


class ProfessionalInfo(BaseModel):
    """Professional profile: title, experience, skills, preferences."""

    title: str = ""
    years_experience: int = Field(default=0, ge=0)
    salary_min: int = Field(default=0, ge=0)
    salary_max: int = Field(default=0, ge=0)
    salary_currency: str = "AUD"
    skills: Dict[str, List[str]] = Field(default_factory=dict)
    preferences: Preferences = Field(default_factory=Preferences)

    @model_validator(mode="after")
    def _validate_salary_range(self) -> "ProfessionalInfo":
        if self.salary_min and self.salary_max and self.salary_min > self.salary_max:
            raise ValueError(
                f"salary_min ({self.salary_min}) must be <= salary_max ({self.salary_max})"
            )
        return self


class ResumeUseWhen(BaseModel):
    """Rules for when a resume profile should be selected."""

    job_types: List[str] = Field(default_factory=list)
    description: str = ""


class ResumeArchetype(str, Enum):
    """Resume framing archetypes for software engineering roles."""

    EXPANSION = "expansion"
    CONSOLIDATION = "consolidation"
    ADAPTATION = "adaptation"
    ASPIRATION = "aspiration"


class ResumeProfile(BaseModel):
    """A single resume profile entry."""

    name: str = "default"
    file: str = ""
    highlights_file: str = ""
    seek_resume_id: str = ""
    archetype: ResumeArchetype = ResumeArchetype.ADAPTATION
    hiring_signal: str = ""
    role_title_patterns: List[str] = Field(default_factory=list)
    keyword_bias: List[str] = Field(default_factory=list)
    use_when: ResumeUseWhen = Field(default_factory=ResumeUseWhen)


class CoverLetterConfig(BaseModel):
    """Cover letter generation settings."""

    tone: str = "casual professional"
    max_words: int = Field(default=150, gt=0)
    spelling: str = "Australian English"
    example_file: str = ""
    highlights_file: str = ""
    anti_slop_rules: List[str] = Field(default_factory=list)
    contract_framing: str = ""
    fulltime_framing: str = ""


class AIConfig(BaseModel):
    """AI provider and model configuration."""

    analysis_provider: str = "anthropic"
    analysis_model: str = "claude-sonnet-4-6"
    cover_letter_provider: str = "anthropic"
    cover_letter_model: str = "claude-opus-4-8"
    form_filling_provider: str = "openai"
    form_filling_model: str = "gpt-4o"


class Profile(BaseModel):
    """Root profile model containing all configuration sections."""

    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    work_rights: WorkRights = Field(default_factory=WorkRights)
    professional: ProfessionalInfo = Field(default_factory=ProfessionalInfo)
    resumes: List[ResumeProfile] = Field(default_factory=list)
    cover_letter: CoverLetterConfig = Field(default_factory=CoverLetterConfig)
    ai: AIConfig = Field(default_factory=AIConfig)

    # -- Resume helpers -----------------------------------------------------

    def get_resume(self, name: str) -> ResumeProfile:
        """Return a resume profile by name.

        Args:
            name: The unique name identifier of the resume profile.

        Returns:
            The matching ``ResumeProfile``.

        Raises:
            KeyError: If no resume with *name* exists.
        """
        for r in self.resumes:
            if r.name == name:
                return r
        available = [r.name for r in self.resumes]
        raise KeyError(f"Resume '{name}' not found. Available resumes: {available}")

    def get_resume_for_job_type(self, job_type: str) -> ResumeProfile:
        """Find the best resume for a given job type.

        Checks each resume's ``use_when.job_types`` list for a
        case-insensitive match.  Falls back to a resume named ``"default"``
        if one exists, then to the first resume in the list.

        Args:
            job_type: Job type string to match (e.g. ``"contract"``,
                ``"full-time"``).

        Returns:
            The best-matching ``ResumeProfile``.

        Raises:
            ValueError: If the profile has no resumes configured.
        """
        if not self.resumes:
            raise ValueError(
                "No resumes configured in profile. Run `ronin setup` to add one."
            )

        job_type_lower = job_type.lower()
        for r in self.resumes:
            if any(jt.lower() == job_type_lower for jt in r.use_when.job_types):
                return r

        # Fallback: try 'default' resume, then first entry.
        for r in self.resumes:
            if r.name == "default":
                return r
        return self.resumes[0]

    def recommend_resume_for_listing(
        self,
        job_title: str,
        job_description: str = "",
        work_type: str = "",
    ) -> ResumeProfile:
        """Recommend the best resume profile for a listing via rule scoring.

        This provides deterministic fallback matching when AI resume selection
        is unavailable or low-confidence. Always returns a resume — see
        :meth:`score_resumes_for_listing` when you need to know whether the
        winner actually matched anything.

        Args:
            job_title: Listing title.
            job_description: Full listing description.
            work_type: Listing work type (e.g. contract/full-time).

        Returns:
            Best-scoring ``ResumeProfile`` based on role/title/keyword signals.

        Raises:
            ValueError: If no resumes are configured.
        """
        ranked = self.score_resumes_for_listing(
            job_title=job_title, job_description=job_description, work_type=work_type
        )
        return ranked[0][0]

    def score_resumes_for_listing(
        self,
        job_title: str,
        job_description: str = "",
        work_type: str = "",
    ) -> List[Tuple[ResumeProfile, float]]:
        """Score every resume against a listing, best first.

        Signal weights: work-type match +2.0, title pattern +3.0 (or +1.5 when
        the pattern appears in the body only), keyword bias +1.0, archetype
        keyword +0.5, and +0.1 for a resume literally named ``default``.

        A score of 0.0 means nothing matched — the resume is not a positive
        recommendation, just the head of an unsorted list. Callers deciding
        whether to *act* on the winner must check the score.

        Raises:
            ValueError: If no resumes are configured.
        """
        if not self.resumes:
            raise ValueError(
                "No resumes configured in profile. Run `ronin setup` to add one."
            )

        title_text = (job_title or "").lower()
        combined_text = f"{job_title or ''} {job_description or ''}".lower()
        work_type_text = (work_type or "").lower()

        archetype_keywords: Dict[ResumeArchetype, List[str]] = {
            ResumeArchetype.EXPANSION: [
                "growth",
                "scale",
                "greenfield",
                "launch",
                "hypergrowth",
            ],
            ResumeArchetype.CONSOLIDATION: [
                "stability",
                "reliability",
                "optimization",
                "maintain",
                "refactor",
                "platform",
            ],
            ResumeArchetype.ADAPTATION: [
                "migration",
                "modernisation",
                "modernization",
                "transformation",
                "integration",
                "change",
            ],
            ResumeArchetype.ASPIRATION: [
                "staff",
                "principal",
                "lead",
                "architecture",
                "strategy",
                "mentoring",
            ],
        }

        ranked: List[Tuple[ResumeProfile, float]] = []

        for resume in self.resumes:
            score = 0.0

            if resume.name == "default":
                score += 0.1

            for job_type in resume.use_when.job_types:
                jt = job_type.lower().strip()
                if jt and jt in work_type_text:
                    score += 2.0

            for pattern in resume.role_title_patterns:
                normalized = pattern.lower().strip()
                if not normalized:
                    continue
                if normalized in title_text:
                    score += 3.0
                elif normalized in combined_text:
                    score += 1.5

            for keyword in resume.keyword_bias:
                normalized = keyword.lower().strip()
                if normalized and normalized in combined_text:
                    score += 1.0

            for keyword in archetype_keywords.get(resume.archetype, []):
                if keyword in combined_text:
                    score += 0.5

            ranked.append((resume, score))

        # Stable sort: ties keep profile.yaml order, so ordering the file is a
        # usable tie-break lever.
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return ranked

    def select_custom_resume(
        self,
        job_title: str,
        job_description: str = "",
        work_type: str = "",
        min_score: float = _CUSTOM_RESUME_MIN_SCORE,
    ) -> Optional[str]:
        """Return a non-archetype resume name that positively matches a listing.

        The four embedding archetypes describe data-engineering JD *shapes*.
        Custom resumes take precedence over them, but the two kinds of custom
        resume are matched differently and must not be merged:

        * **Role cuts** (``solutions_engineer``) declare ``role_title_patterns``
          and are matched on the listing TITLE only. A "Sales Engineer" ad needs
          that resume; an ordinary data-engineering ad that merely mentions
          "stakeholder" or "proof of concept" in the body does not. Scoring
          these against the description makes them swallow the queue.
        * **Register cuts** (``contract_aggressive`` — the cashflow/FinOps copy)
          declare ``keyword_bias`` and no title patterns, because they are not
          about the job's role. They are chosen on context: work type plus
          keyword bias, via the rule scorer, and must clear ``min_score``.

        Declaring ``keyword_bias`` is what opts a resume into the scored path.
        A resume with neither signal (only ``use_when.job_types``) is never
        auto-selected here — work type alone is too coarse to abandon the
        archetype, and the scorer's fuzzy archetype-keyword bonus could
        otherwise push it over the line by accident.

        Returns ``None`` when nothing matched — the caller keeps its archetype.
        The threshold matters: the scorer always names a winner, so without it
        a listing matching nothing would adopt whichever resume sits first in
        profile.yaml.
        """
        if not self.resumes:
            return None

        custom = [
            r
            for r in self.resumes
            if str(r.name or "").strip().lower() not in ARCHETYPE_RESUME_NAMES
            and str(r.name or "").strip()
        ]
        if not custom:
            return None

        title_text = (job_title or "").strip().lower()
        if title_text:
            for resume in custom:
                for pattern in resume.role_title_patterns or []:
                    normalized = str(pattern or "").strip().lower()
                    if normalized and normalized in title_text:
                        return resume.name

        # Register cuts only — a role cut that did not win on title must not get
        # a second chance on body keywords.
        scored = {
            str(r.name): r
            for r in custom
            if not (r.role_title_patterns or []) and (r.keyword_bias or [])
        }
        if not scored:
            return None
        try:
            ranked = self.score_resumes_for_listing(
                job_title=job_title,
                job_description=job_description,
                work_type=work_type,
            )
        except ValueError:
            return None

        for resume, score in ranked:
            if str(resume.name) not in scored:
                continue
            return resume.name if score >= min_score else None
        return None

    def get_resume_text(self, resume_name: str) -> str:
        """Read the plain-text content of a resume file.

        Looks for the file at ``<RONIN_HOME>/resumes/<filename>``.

        Args:
            resume_name: The name identifier of the resume profile.

        Returns:
            The text content of the resume file.

        Raises:
            KeyError: If no resume with *resume_name* exists.
            FileNotFoundError: If the resume file is missing on disk.
        """
        resume = self.get_resume(resume_name)
        resumes_dir = get_ronin_home() / "resumes"
        resume_path = resumes_dir / resume.file
        if not resume_path.exists():
            raise FileNotFoundError(
                f"Resume file not found: {resume_path}\n"
                f"Place your plain-text resume at that path, or run `ronin setup`."
            )
        return resume_path.read_text(encoding="utf-8")

    # -- Skill helpers ------------------------------------------------------

    def get_all_skills_flat(self) -> List[str]:
        """Return all skills from every category as a flat, deduplicated list.

        The order follows category insertion order, then item order within
        each category.  Duplicates across categories are removed (first
        occurrence wins).

        Returns:
            Flat list of skill strings.
        """
        seen: set[str] = set()
        flat: list[str] = []
        for skills in self.professional.skills.values():
            for skill in skills:
                if skill not in seen:
                    seen.add(skill)
                    flat.append(skill)
        return flat

    # -- Cover-letter asset helpers -----------------------------------------

    def get_highlights_text(self) -> str:
        """Read the highlights file referenced by the cover-letter config.

        Looks for the file at ``<RONIN_HOME>/assets/<highlights_file>``.

        Returns:
            The text content of the highlights file, or an empty string if
            no highlights file is configured.

        Raises:
            FileNotFoundError: If the configured file does not exist on disk.
        """
        filename = self.cover_letter.highlights_file
        if not filename:
            return ""
        path = get_ronin_home() / "assets" / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Highlights file not found: {path}\n"
                f"Create it or update cover_letter.highlights_file in your profile."
            )
        return path.read_text(encoding="utf-8")

    def get_resume_highlights_text(self, resume_name: str) -> str:
        """Read the highlights file for a specific resume profile.

        Each resume can define its own concise ``highlights_file`` so cover
        letters are guided by a short summary instead of the full resume
        text (keeping token usage down). Falls back to the global
        ``cover_letter.highlights_file`` when the resume defines none.

        Looks for the file at ``<RONIN_HOME>/assets/<highlights_file>``.

        Args:
            resume_name: The name identifier of the resume profile.

        Returns:
            The text content of the highlights file, or an empty string if
            neither a per-resume nor a global highlights file is configured.

        Raises:
            FileNotFoundError: If the configured file does not exist on disk.
        """
        try:
            filename = self.get_resume(resume_name).highlights_file
        except KeyError:
            filename = ""
        if not filename:
            return self.get_highlights_text()
        path = get_ronin_home() / "assets" / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Highlights file not found: {path}\n"
                f"Create it or update highlights_file for resume "
                f"'{resume_name}' in your profile."
            )
        return path.read_text(encoding="utf-8")

    def get_cover_letter_example(self) -> str:
        """Read the example cover letter referenced by the config.

        Looks for the file at ``<RONIN_HOME>/assets/<example_file>``.

        Returns:
            The text content of the example file, or an empty string if no
            example file is configured.

        Raises:
            FileNotFoundError: If the configured file does not exist on disk.
        """
        filename = self.cover_letter.example_file
        if not filename:
            return ""
        path = get_ronin_home() / "assets" / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Cover letter example not found: {path}\n"
                f"Create it or update cover_letter.example_file in your profile."
            )
        return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def load_profile(path: Optional[Path] = None) -> Profile:
    """Load and validate the user profile from YAML.

    Args:
        path: Explicit path to a ``profile.yaml`` file.  When *None*, the
            file is loaded from ``<RONIN_HOME>/profile.yaml``.

    Returns:
        A validated ``Profile`` instance.

    Raises:
        FileNotFoundError: If the profile file does not exist.
        ValueError: If the YAML is not a valid mapping.
        yaml.YAMLError: If the file contains invalid YAML syntax.
    """
    if path is None:
        user_path = get_ronin_home() / "profile.yaml"
        project_path = Path(__file__).parent.parent / "profile.yaml"
        if user_path.exists():
            path = user_path
        elif project_path.exists():
            path = project_path
        else:
            raise FileNotFoundError(
                f"Profile not found. Run `ronin setup` to create your profile.\n"
                f"Checked:\n  - {user_path}\n  - {project_path}"
            )

    if not path.exists():
        raise FileNotFoundError(
            f"Profile not found: {path}\nRun `ronin setup` to create your profile."
        )

    logger.debug("Loading profile from {}", path)

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if raw is None:
        # Empty YAML file — return a profile with all defaults.
        logger.warning("Profile file is empty, using defaults: {}", path)
        return Profile()

    if not isinstance(raw, dict):
        raise ValueError(
            f"Invalid profile format: expected a YAML mapping, got {type(raw).__name__}"
        )

    return Profile.model_validate(raw)
