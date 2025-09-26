"""
Services package containing external service integrations.
"""

from .ai_service import AIService
from .airtable_service import AirtableManager

__all__ = ["AirtableManager", "AIService"]
