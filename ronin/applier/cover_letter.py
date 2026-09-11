"""Cover letter generation functionality for job applications."""

from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from ronin.ai import AnthropicService
from ronin.prompts import (
    COVER_LETTER_CONTRACT_CONTEXT,
    COVER_LETTER_FULLTIME_CONTEXT,
    COVER_LETTER_SYSTEM_PROMPT,
)

try:
    from ronin.profile import load_profile
    from ronin.prompts.generator import generate_cover_letter_prompt
except ImportError:
    load_profile = None  # type: ignore[assignment,misc]
    generate_cover_letter_prompt = None  # type: ignore[assignment,misc]


class CoverLetterGenerator:
    """Handles the generation of cover letters for job applications."""

    def __init__(self, ai_service: Optional[AnthropicService] = None):
        """
        Initialize the cover letter generator.

        Args:
            ai_service: An instance of AnthropicService. If None, a new instance will be created.
        """
        self.ai_service = ai_service or AnthropicService()

        self.profile = None
        self.model: Optional[str] = None
        if load_profile is not None:
            try:
                self.profile = load_profile()
                logger.debug("Loaded user profile for cover letter generation")
            except Exception as e:
                logger.debug(f"Profile not available, using legacy prompts: {e}")

        # Without this the request falls through to AnthropicService's own
        # default, which is not the model the user configured.
        try:
            self.model = self.profile.ai.cover_letter_model or None
        except Exception:
            self.model = None

    def generate_cover_letter(
        self,
        job_description: str,
        title: str,
        company_name: str,
        key_tools: str,
        resume_text: str = None,
        work_type: str = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a cover letter for a job application.

        Args:
            job_description: The full job description text
            title: The job title
            company_name: The company name
            key_tools: The key tools or domain for the job
            resume_text: Optional resume text to include. If None, will be loaded from appropriate files.
            work_type: The work type (e.g., "Contract/Temp", "Full time")

        Returns:
            Dictionary containing the generated cover letter or None if generation failed.
        """
        try:
            is_contract = work_type and "contract" in work_type.lower()
            engagement_type = "CONTRACT/TEMP" if is_contract else "FULL-TIME/PERMANENT"

            if self.profile is not None and generate_cover_letter_prompt is not None:
                # --- Profile-based path ---
                highlights = self.profile.get_highlights_text()
                if highlights:
                    resume_text = highlights
                else:
                    resume_text = (
                        self._get_resume_text(key_tools)
                        if resume_text is None
                        else resume_text
                    )

                example = self.profile.get_cover_letter_example()

                engagement_context = (
                    self.profile.cover_letter.contract_framing
                    if is_contract
                    else self.profile.cover_letter.fulltime_framing
                )

                system_prompt = generate_cover_letter_prompt(
                    profile=self.profile,
                    engagement_type=engagement_type,
                    engagement_context=engagement_context,
                    example=example,
                    resume_text=resume_text,
                )
            else:
                # --- Legacy hardcoded path ---
                example_path = (
                    Path(__file__).parent.parent.parent
                    / "assets"
                    / "cover_letter_example.txt"
                )
                example = example_path.read_text() if example_path.exists() else ""

                highlights_path = (
                    Path(__file__).parent.parent.parent / "assets" / "highlights.txt"
                )
                if highlights_path.exists():
                    resume_text = highlights_path.read_text()
                else:
                    resume_text = (
                        self._get_resume_text(key_tools)
                        if resume_text is None
                        else resume_text
                    )

                engagement_context = (
                    COVER_LETTER_CONTRACT_CONTEXT
                    if is_contract
                    else COVER_LETTER_FULLTIME_CONTEXT
                )

                system_prompt = COVER_LETTER_SYSTEM_PROMPT.format(
                    engagement_type=engagement_type,
                    engagement_context=engagement_context,
                    example=example,
                    resume_text=resume_text,
                )

            user_message = f"Write a cover letter for the {'contract' if is_contract else 'full-time'} role of {title} at {company_name}: {job_description}"

            return self.ai_service.chat_completion(
                system_prompt=system_prompt,
                user_message=user_message,
                model=self.model,
                temperature=0.7,
                max_tokens=8192,
            )

        except Exception as e:
            logger.error(f"Failed to generate cover letter: {e}")
            return None

    def _get_resume_text(self, key_tools: str) -> str:
        """Get the resume text based on tech stack or job classification."""
        if self.profile is not None:
            try:
                return self.profile.get_resume_text(key_tools)
            except (KeyError, FileNotFoundError) as e:
                logger.debug(f"Profile resume lookup failed, using legacy path: {e}")

        # Legacy hardcoded path
        key_tools = key_tools.lower() if key_tools else "default"
        base_path = Path(__file__).parent.parent.parent / "assets" / "cv"

        # Try exact match first
        cv_path = base_path / f"{key_tools}.txt"
        if cv_path.exists():
            logger.debug(f"Using resume: {cv_path.name}")
            return cv_path.read_text()

        # Default resume
        default_path = base_path / "default.txt"
        if default_path.exists():
            logger.debug("Using default resume")
            return default_path.read_text()

        logger.error("No resume file found!")
        return "Resume information not available."
