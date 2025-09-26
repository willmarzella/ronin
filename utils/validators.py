"""
validators.py
Utility functions for validating data throughout the ronin system.
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def is_valid_email(email: str) -> bool:
    """
    Validate email format.
    This is intentionally simple rather than RFC-compliant.
    The only real email validation is sending an actual email.
    """
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def is_valid_url(url: str) -> bool:
    """Validate URL format."""
    pattern = (
        r"^(http|https)://[a-zA-Z0-9]+([\-\.]{1}[a-zA-Z0-9]+)*\."
        r"[a-zA-Z]{2,}(:[0-9]{1,5})?(\/.*)?$"
    )
    return bool(re.match(pattern, url))


def validate_required_fields(
    data: Dict[str, Any], required_fields: List[str]
) -> List[str]:
    """
    Validate that a dictionary contains all required fields.
    Returns list of missing fields (empty if all present).
    """
    return [
        field for field in required_fields if field not in data or data[field] is None
    ]


def validate_job_listing(job: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Validate a job listing has all required fields and correct format.
    Returns dict with 'errors' and 'warnings' lists.
    """
    errors = []
    warnings = []

    # Check required fields
    required = ["title", "company", "url"]
    missing = validate_required_fields(job, required)
    if missing:
        errors.append(f"Missing required fields: {', '.join(missing)}")

    # Check field formats
    if "url" in job and job["url"] and not is_valid_url(job["url"]):
        errors.append("Invalid URL format")

    if "email" in job and job["email"] and not is_valid_email(job["email"]):
        errors.append("Invalid email format")

    # Check for suspicious patterns in job listing
    if "description" in job and job["description"]:
        desc = job["description"].lower()

        suspicious_patterns = [
            "bank account",
            "wire transfer",
            "paypal",
            "western union",
            "pay to apply",
            "certification fee",
            "training fee",
        ]

        for pattern in suspicious_patterns:
            if pattern in desc:
                warnings.append(f"Suspicious content detected: '{pattern}'")

    return {"errors": errors, "warnings": warnings}


def validate_date_string(
    date_str: str, formats: List[str] = None
) -> Optional[datetime]:
    """
    Validate a date string against a list of formats.
    Returns datetime object if valid, None if invalid.
    """
    if formats is None:
        formats = ["%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


def validate_json_structure(
    json_str: str, schema: Dict[str, Any]
) -> Dict[str, List[str]]:
    """
    Validate JSON string against a schema.
    Simple schema validator - not full JSON Schema implementation.

    Args:
        json_str: JSON string to validate
        schema: Dict with keys as field names and values as types or nested schemas

    Returns:
        Dict with 'errors' list
    """
    errors = []

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {str(e)}")
        return {"errors": errors}

    def validate_against_schema(data, schema, path=""):
        nonlocal errors

        for key, expected_type in schema.items():
            current_path = f"{path}.{key}" if path else key

            # Check if required field exists
            if key not in data:
                errors.append(f"Missing required field: {current_path}")
                continue

            value = data[key]

            # Handle nested objects
            if isinstance(expected_type, dict):
                if not isinstance(value, dict):
                    errors.append(f"Field {current_path} should be an object")
                else:
                    validate_against_schema(value, expected_type, current_path)
                continue

            # Handle arrays
            if isinstance(expected_type, list):
                if not isinstance(value, list):
                    errors.append(f"Field {current_path} should be an array")
                elif (
                    expected_type and value
                ):  # If we have array type info and array has values
                    item_type = expected_type[0]
                    for i, item in enumerate(value):
                        if isinstance(item_type, dict):
                            if not isinstance(item, dict):
                                errors.append(
                                    f"Item {i} in {current_path} should be an object"
                                )
                            else:
                                validate_against_schema(
                                    item, item_type, f"{current_path}[{i}]"
                                )
                        elif not isinstance(item, item_type):
                            errors.append(
                                f"Item {i} in {current_path} should be "
                                f"{item_type.__name__}"
                            )
                continue

            # Handle primitive types
            if not isinstance(value, expected_type):
                errors.append(
                    f"Field {current_path} should be {expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )

    validate_against_schema(data, schema)
    return {"errors": errors}


def is_valid_phone(phone: str) -> bool:
    """
    Validate phone number format.
    Allows for various formats with or without country codes.
    """
    # Remove all non-digit characters for normalization
    digits_only = re.sub(r"\D", "", phone)

    # Check if the resulting string is a valid length for a phone number
    return 7 <= len(digits_only) <= 15


def is_safe_filename(filename: str) -> bool:
    """
    Validate that a filename doesn't contain unsafe characters
    or attempt directory traversal.
    """
    # Check for directory traversal attempts
    if ".." in filename or "/" in filename or "\\" in filename:
        return False

    # Check for valid characters (alphanumeric, underscore, hyphen, period)
    return bool(re.match(r"^[\w\-\.]+$", filename))
