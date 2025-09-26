"""
LinkedIn Outreach Module

This package provides functionality for automating LinkedIn outreach:
- Searching for companies and people on LinkedIn
- Sending connection requests and direct messages
- Generating personalized messages using OpenAI
"""

import tasks.job_outreach.prompts as prompts
from tasks.job_outreach.company import LinkedInCompanyHandler
from tasks.job_outreach.login import LinkedInLoginHandler
from tasks.job_outreach.message import LinkedInMessageGenerator, OutreachTracker
from tasks.job_outreach.people import LinkedInPeopleHandler
from tasks.job_outreach.search import LinkedInSearcher

__all__ = [
    "LinkedInLoginHandler",
    "LinkedInSearcher",
    "LinkedInCompanyHandler",
    "LinkedInPeopleHandler",
    "LinkedInMessageGenerator",
    "OutreachTracker",
    "prompts",
]
