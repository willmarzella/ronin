"""
formatters.py
Utility functions for formatting data throughout the ronin system.
"""

import re
import json
from datetime import datetime
from typing import Dict, Any, List, Union


def format_currency(amount: float, currency: str = "USD") -> str:
    """Convert float to formatted currency string."""
    if currency == "USD":
        return f"${amount:,.2f}"
    elif currency == "EUR":
        return f"€{amount:,.2f}"
    elif currency == "GBP":
        return f"£{amount:,.2f}"
    else:
        return f"{amount:,.2f} {currency}"


def format_date(date_obj: Union[datetime, str], output_format: str = "%Y-%m-%d") -> str:
    """
    Format date objects consistently throughout the system.

    Args:
        date_obj: Either a datetime object or a string in ISO format
        output_format: strftime format string
    """
    if isinstance(date_obj, str):
        # Try to parse ISO format first
        try:
            date_obj = datetime.fromisoformat(date_obj.replace("Z", "+00:00"))
        except ValueError:
            # Try common formats
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
                try:
                    date_obj = datetime.strptime(date_obj, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Could not parse date: {date_obj}")

    return date_obj.strftime(output_format)


def format_job_title(title: str) -> str:
    """
    Standardize job titles for consistency.

    Args:
        title: Raw job title from scraped data
    """
    # Lowercase and strip extra whitespace
    title = title.lower().strip()

    # Common abbreviations to standardize
    replacements = {
        "sr.": "senior",
        "jr.": "junior",
        "engg": "engineering",
        "eng": "engineer",
        "dev": "developer",
        "mgr": "manager",
        "prog": "programmer",
    }

    for old, new in replacements.items():
        title = re.sub(r"\b" + re.escape(old) + r"\b", new, title)

    # Capitalize words
    return " ".join(word.capitalize() for word in title.split())


def format_response_for_storage(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format API response data for consistent storage.
    Adds metadata and ensures consistent structure.
    """
    return {
        "data": response,
        "meta": {"timestamp": datetime.now().isoformat(), "version": "1.0"},
    }


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to specified length with suffix if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def format_prompt_variables(template: str, variables: Dict[str, Any]) -> str:
    """
    Format a prompt template with variables.

    Args:
        template: String template with {variable} placeholders
        variables: Dictionary of variable values
    """
    # Before formatting, escape any braces that aren't variable placeholders
    for key in variables:
        if not isinstance(variables[key], (str, int, float, bool)):
            variables[key] = json.dumps(variables[key])

    try:
        return template.format(**variables)
    except KeyError as e:
        missing_key = str(e).strip("'")
        raise ValueError(f"Missing required variable in prompt template: {missing_key}")


def format_keywords_for_search(keywords: List[str]) -> str:
    """
    Format a list of keywords into a search query string.
    E.g., ["python", "machine learning"] -> "python \"machine learning\""
    """
    formatted = []
    for keyword in keywords:
        if " " in keyword:
            formatted.append(f'"{keyword}"')
        else:
            formatted.append(keyword)
    return " ".join(formatted)


def format_filename_safe(text: str) -> str:
    """Convert text to a filename-safe string."""
    # Replace spaces with underscores
    text = text.replace(" ", "_")
    # Remove any non-alphanumeric characters except underscores, hyphens and periods
    return re.sub(r"[^\w\-\.]", "", text)
