"""
Job board scrapers for various platforms.

This module provides a collection of scrapers for different job boards,
along with a factory function to create the appropriate scraper instance.

Available scrapers:
- SeekJobScraper: Scraper for Seek.com.au
"""

from typing import Dict, Optional, Type
from .base import BaseScraper
from .seek import SeekJobScraper

# Registry of available scrapers
SCRAPER_REGISTRY: Dict[str, Type[BaseScraper]] = {
    "seek": SeekJobScraper,
}


def create_scraper(
    platform: str, config: Dict, scraper_class: Optional[Type[BaseScraper]] = None
) -> BaseScraper:
    """
    Factory function to create a scraper instance.

    Args:
        platform: The job platform to scrape ("seek", "linkedin", etc.)
        config: Configuration dictionary
        scraper_class: Optional custom scraper class (for testing/extension)

    Returns:
        An instance of the appropriate scraper

    Raises:
        ValueError: If the platform is not supported

    Example:
        >>> config = load_config()
        >>> scraper = create_scraper("seek", config)
        >>> raw_jobs = scraper.scrape_jobs()
    """
    if scraper_class:
        return scraper_class(config)

    scraper_class = SCRAPER_REGISTRY.get(platform.lower())
    if not scraper_class:
        supported = ", ".join(SCRAPER_REGISTRY.keys())
        raise ValueError(
            f"Unsupported platform: {platform}. Supported platforms are: {supported}"
        )

    return scraper_class(config)


# For convenience, export the scraper classes directly
__all__ = ["BaseScraper", "SeekJobScraper", "create_scraper", "SCRAPER_REGISTRY"]
