"""Factory for creating job scrapers."""

from typing import Dict, Optional, Type
from app.scrapers.base import BaseScraper
from app.scrapers.seek import SeekScraper
from app.scrapers.indeed import IndeedScraper
from app.utils.config import load_config


class JobScraperFactory:
    """Factory class for creating job scrapers based on job board type."""

    _scrapers: Dict[str, Type[BaseScraper]] = {
        "seek": SeekScraper,
        # "indeed": IndeedScraper,
        # "linkedin": LinkedInScraper,
    }

    @classmethod
    def create_scraper(
        cls, job_board: str, config: Optional[Dict] = None
    ) -> Optional[BaseScraper]:
        """
        Create a scraper instance for the specified job board.

        Args:
            job_board: The name of the job board (e.g., 'seek', 'indeed', 'linkedin')
            config: Optional configuration dictionary. If not provided, will load from config file.

        Returns:
            An instance of the appropriate scraper, or None if not supported
        """
        scraper_class = cls._scrapers.get(job_board.lower())
        if scraper_class:
            if config is None:
                config = load_config()
            return scraper_class(config)
        return None

    @classmethod
    def register_scraper(cls, job_board: str, scraper_class: Type[BaseScraper]):
        """
        Register a new scraper class for a job board.

        Args:
            job_board: The name of the job board
            scraper_class: The scraper class to register
        """
        cls._scrapers[job_board.lower()] = scraper_class

    @classmethod
    def supported_job_boards(cls) -> list[str]:
        """Get a list of supported job boards."""
        return list(cls._scrapers.keys())
