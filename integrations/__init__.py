"""
Third-party service integrations for the job automation system.
"""

from .airtable import AirtableManager
from .openai import OpenAIClient

__all__ = ["AirtableManager", "OpenAIClient"]
