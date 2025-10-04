"""
Configuration management for the job automation system.

This package contains configuration files and utilities for managing
job search parameters, scraping settings, and analysis preferences.
"""

from pathlib import Path

# Export the config directory path for convenience
CONFIG_DIR = Path(__file__).parent

# Default config file path
DEFAULT_CONFIG_FILE = CONFIG_DIR / "config.yaml"

__all__ = ["CONFIG_DIR", "DEFAULT_CONFIG_FILE"]
