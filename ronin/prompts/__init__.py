"""Prompt templates and generators for AI interactions.

This module provides both:
- Legacy static prompt constants (for backwards compatibility)
- Dynamic prompt generators that build prompts from user profile
"""

# Legacy static prompts (kept for reference / fallback)
from ronin.prompts.cover_letter import (
    COVER_LETTER_CONTRACT_CONTEXT,
    COVER_LETTER_FULLTIME_CONTEXT,
    COVER_LETTER_SYSTEM_PROMPT,
)
from ronin.prompts.form_fields import FORM_FIELD_SYSTEM_PROMPT

# Dynamic prompt generators (preferred)
from ronin.prompts.generator import (
    generate_cover_letter_prompt,
    generate_form_field_prompt,
    generate_job_analysis_prompt,
)
from ronin.prompts.job_analysis import JOB_ANALYSIS_PROMPT

__all__ = [
    # Static (legacy)
    "JOB_ANALYSIS_PROMPT",
    "FORM_FIELD_SYSTEM_PROMPT",
    "COVER_LETTER_SYSTEM_PROMPT",
    "COVER_LETTER_CONTRACT_CONTEXT",
    "COVER_LETTER_FULLTIME_CONTEXT",
    # Dynamic (preferred)
    "generate_job_analysis_prompt",
    "generate_form_field_prompt",
    "generate_cover_letter_prompt",
]
