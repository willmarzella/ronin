"""Job board scrapers for various platforms."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import time
from loguru import logger


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
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

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

    @abstractmethod
    def scrape_jobs(self) -> List[Dict]:
        """Main scraping method to get jobs from the board."""
        pass


class SeekScraper(BaseScraper):
    """Scraper for Seek job board."""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = "https://www.seek.com.au"

    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """Parse relative time string into datetime object."""
        try:
            match = re.search(r"Posted (\d+)([dhm]) ago", time_str)
            if not match:
                return None

            number = int(match.group(1))
            unit = match.group(2)
            now = datetime.now()

            if unit == "d":
                return now - timedelta(days=number)
            elif unit == "h":
                return now - timedelta(hours=number)
            elif unit == "m":
                return now - timedelta(minutes=number)
            return None
        except Exception as e:
            logger.error(f"Error parsing relative time '{time_str}': {str(e)}")
            return None

    def build_search_url(self, page: int) -> str:
        """Build the search URL for the given page."""
        keywords = self.config["search"]["keywords"].replace(" ", "-").lower()
        location = self.config["search"]["location"].replace(" ", "-")
        salary_min = self.config["search"]["salary"]["min"]
        salary_max = self.config["search"]["salary"]["max"]

        url = f"{self.base_url}/{keywords}-jobs/in-{location}"
        params = {
            "daterange": "7",
            "salaryrange": f"{salary_min}-{salary_max}",
            "salarytype": "annual",
            "sortmode": "ListedDate",
            "page": str(page),
        }
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{url}?{param_str}"

    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict]:
        """Extract job information from a job card."""
        try:
            job_id = job_element.get("data-job-id")
            if not job_id:
                return None

            title_element = job_element.find("a", attrs={"data-automation": "jobTitle"})
            company_element = job_element.find(
                "a", attrs={"data-automation": "jobCompany"}
            )

            return {
                "job_id": job_id,
                "title": title_element.text.strip() if title_element else "Unknown",
                "company": (
                    company_element.text.strip() if company_element else "Unknown"
                ),
                "url": f"https://www.seek.com.au/job/{job_id}",
                "source": "seek",
            }
        except Exception as e:
            logger.error(f"Error extracting job info: {str(e)}")
            return None

    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get detailed job information."""
        try:
            url = f"https://www.seek.com.au/job/{job_id}"
            soup = self.make_request(url)
            if not soup:
                return None

            description_element = soup.find(
                "div", attrs={"data-automation": "jobAdDetails"}
            )
            if not description_element:
                return None

            description_text = description_element.get_text(separator="\n").strip()
            description_text = description_text.encode("ascii", "ignore").decode(
                "ascii"
            )

            apply_button = soup.find("a", attrs={"data-automation": "job-detail-apply"})
            quick_apply = apply_button and "Quick apply" in apply_button.get_text()

            return {
                "description": description_text,
                "quick_apply": quick_apply,
                "created_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {str(e)}")
            return None

    def get_job_previews(self) -> List[Dict]:
        """Get job previews with minimal information to check against Airtable."""
        jobs_data = []
        page = 1

        while True:
            if self.max_jobs and len(jobs_data) >= self.max_jobs:
                break

            url = self.build_search_url(page)
            soup = self.make_request(url)
            if not soup:
                break

            job_elements = soup.find_all("article", attrs={"data-card-type": "JobCard"})
            if not job_elements:
                logger.info(f"No jobs found on page {page}")
                break

            logger.info(f"Found {len(job_elements)} job previews on page {page}")

            for job_element in job_elements:
                if self.max_jobs and len(jobs_data) >= self.max_jobs:
                    break

                job_info = self.extract_job_info(job_element)
                if job_info:
                    jobs_data.append(job_info)
                    logger.info(
                        f"Added job preview: {job_info['title']} (ID: {job_info['job_id']})"
                    )

            if len(job_elements) < 22:  # Seek typically shows 22 jobs per page
                break
                page += 1

        return jobs_data

    def scrape_jobs(self) -> List[Dict]:
        """
        Scrape jobs from Seek.
        This is now an optimized version that only fetches full details for new jobs.
        """
        jobs_data = []
        job_previews = self.get_job_previews()

        if not job_previews:
            return []

        for preview in job_previews:
            job_details = self.get_job_details(preview["job_id"])
            if job_details:
                full_job = {**preview, **job_details}
                jobs_data.append(full_job)
                logger.info(
                    f"Scraped full details for job: {preview['title']} (ID: {preview['job_id']})"
                )

        return jobs_data


def create_scraper(platform: str, config: Dict) -> BaseScraper:
    """Factory function to create a scraper instance."""
    scrapers = {"seek": SeekScraper}

    scraper_class = scrapers.get(platform.lower())
    if not scraper_class:
        raise ValueError(f"Unsupported platform: {platform}")

    return scraper_class(config)
