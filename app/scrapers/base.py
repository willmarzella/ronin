"""Base scraper functionality."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import requests
from loguru import logger
from bs4 import BeautifulSoup
import time


class BaseScraper(ABC):
    """Base class for all job board scrapers."""

    def __init__(self, config: Dict, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()
        self.delay = config.get("scraping", {}).get("delay_seconds", 2)
        self.max_jobs = config.get("scraping", {}).get("max_jobs", None)
        self.timeout = config.get("scraping", {}).get("timeout_seconds", 10)

        # Set up common headers
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"[
                    :150
                ]
            }
        )

    @abstractmethod
    def build_search_url(self, page: int) -> str:
        """Build the search URL for the given page number."""
        pass

    @abstractmethod
    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict]:
        """Extract job information from a job card/element."""
        pass

    @abstractmethod
    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get detailed information for a specific job."""
        pass

    @abstractmethod
    def find_job_elements(self, soup: BeautifulSoup) -> List:
        """Find all job elements on the page."""
        pass

    @abstractmethod
    def scrape_jobs(self) -> List[Dict]:
        """
        Main scraping method to get jobs from the board.
        This should be implemented by each specific scraper.

        Returns:
            List of raw job data (without analysis)
        """
        pass

    def make_request(self, url: str) -> Optional[BeautifulSoup]:
        """Make an HTTP request with error handling and rate limiting."""
        try:
            time.sleep(self.delay)  # Rate limiting
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {url}: {str(e)}")
            return None
