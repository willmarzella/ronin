"""
Services package containing external service integrations.
"""

from .airtable_service import AirtableManager
from .ai_service import AIService

__all__ = ["AirtableManager", "AIService"]
