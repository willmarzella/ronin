"""Job board scrapers for various platforms."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import re
import time
import functools

import requests
from bs4 import BeautifulSoup
from loguru import logger


def rate_limited(func):
    """Decorator to implement rate limiting and error handling for requests."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            time.sleep(self.delay)  # Rate limiting
            return func(self, *args, **kwargs)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error in {func.__name__}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            return None

    return wrapper


class BaseScraper(ABC):
    """Base class for all job board scrapers."""

    def __init__(self, config: Dict, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()
        self.delay = config.get("scraping", {}).get("delay_seconds", 2)
        self.max_jobs = config.get("scraping", {}).get("max_jobs", None)
        self.timeout = config.get("scraping", {}).get("timeout_seconds", 10)
        self.quick_apply_only = config.get("scraping", {}).get("quick_apply_only", True)

        # Set up common headers
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    @rate_limited
    def make_request(self, url: str) -> Optional[BeautifulSoup]:
        """Make an HTTP request and return BeautifulSoup object."""
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    @abstractmethod
    def get_job_previews(self) -> List[Dict[str, Any]]:
        """Get job previews with minimal information."""
        pass

    @abstractmethod
    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed job information."""
        pass

    def scrape_jobs(self) -> List[Dict[str, Any]]:
        """
        Scrape all jobs with full details.
        Default implementation for most job boards.
        """
        job_previews = self.get_job_previews()
        if not job_previews:
            return []

        jobs_data = []
        for preview in job_previews:
            job_details = self.get_job_details(preview["job_id"])
            if job_details:
                # Skip jobs without quick apply if the option is enabled
                if self.quick_apply_only and not job_details.get("quick_apply", False):
                    logger.info(
                        f"Skipping job without quick apply: {preview['title']} (ID: {preview['job_id']})"
                    )
                    continue

                full_job = {**preview, **job_details}
                jobs_data.append(full_job)
                logger.info(
                    f"Scraped details for: {preview['title']} (ID: {preview['job_id']})"
                )

        if self.quick_apply_only:
            logger.info(f"Found {len(jobs_data)} jobs with quick apply option")
        return jobs_data


class SeekScraper(BaseScraper):
    """Scraper for Seek job board."""

    # Mapping of Australian state abbreviations to city names
    LOCATION_MAPPING = {
        "NSW": "Sydney, NSW",
        "VIC": "Melbourne, VIC",
        "QLD": "Brisbane, QLD",
        "SA": "Adelaide, SA",
        "WA": "Perth, WA",
        "TAS": "Hobart, TAS",
        "ACT": "Canberra, ACT",
        "NT": "Darwin, NT",
    }

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = "https://www.seek.com.au"

    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """Parse relative time string (e.g., 'Posted 3d ago') into datetime."""
        if not time_str:
            return None

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

    def build_search_url(self, page: int) -> str:
        """Build the search URL for the given page."""
        search_config = self.config["search"]
        keywords = search_config["keywords"].replace(" ", "-").lower()
        location = search_config["location"].replace(" ", "-")
        salary_min = search_config["salary"]["min"]
        salary_max = search_config["salary"]["max"]
        date_range = search_config["date_range"]

        params = {
            "daterange": date_range,
            "salaryrange": f"{salary_min}-{salary_max}",
            "salarytype": "annual",
            "sortmode": "ListedDate",
            "page": str(page),
        }
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.base_url}/{keywords}-jobs/in-{location}?{param_str}"

    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Extract job preview information from a job card."""
        job_id = job_element.get("data-job-id")
        if not job_id:
            return None

        title_element = job_element.find("a", attrs={"data-automation": "jobTitle"})
        company_element = job_element.find("a", attrs={"data-automation": "jobCompany"})

        return {
            "job_id": job_id,
            "title": title_element.text.strip() if title_element else "Unknown",
            "company": company_element.text.strip() if company_element else "Unknown",
            "url": f"{self.base_url}/job/{job_id}",
            "source": "seek",
        }

    def clean_location(self, location: str) -> str:
        """Map location to standard city name based on state abbreviations."""
        if not location:
            return "Unknown"

        # Check each state abbreviation in the location string
        for state, city in self.LOCATION_MAPPING.items():
            if state in location:
                return city

        return location.strip()

    def get_job_previews(self) -> List[Dict[str, Any]]:
        """Get job previews with minimal information."""
        jobs_data = []
        page = 1
        jobs_per_page = 22  # Seek typically shows 22 jobs per page

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

            # Process job elements on this page
            for job_element in job_elements:
                if self.max_jobs and len(jobs_data) >= self.max_jobs:
                    break

                job_info = self.extract_job_info(job_element)
                if job_info:
                    jobs_data.append(job_info)
                    logger.debug(f"Added job preview: {job_info['title']}")

            # Stop if we didn't get a full page of results
            if len(job_elements) < jobs_per_page:
                break

            page += 1  # Move to next page

        logger.info(f"Found {len(jobs_data)} total job previews")
        return jobs_data

    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed job information for a specific job."""
        url = f"{self.base_url}/job/{job_id}"
        soup = self.make_request(url)
        if not soup:
            return None

        # Check if job has quick apply first to avoid unnecessary processing
        apply_button = soup.find("a", attrs={"data-automation": "job-detail-apply"})
        quick_apply = apply_button and "Quick apply" in apply_button.get_text()

        # If quick_apply_only is enabled and this job doesn't have quick apply, return None
        if self.quick_apply_only and not quick_apply:
            return None

        # Extract job description
        description_element = soup.find(
            "div", attrs={"data-automation": "jobAdDetails"}
        )
        if not description_element:
            return None

        # Clean up description text
        description_text = description_element.get_text(separator="\n").strip()
        description_text = description_text.encode("ascii", "ignore").decode("ascii")

        # Extract location and work type
        location_element = soup.find(
            "span", attrs={"data-automation": "job-detail-location"}
        )
        work_type_element = soup.find(
            "span", attrs={"data-automation": "job-detail-work-type"}
        )

        location = self.clean_location(
            location_element.text.strip() if location_element else ""
        )
        work_type = (
            work_type_element.text.strip() if work_type_element else "Not specified"
        )

        # Find posted time
        posted_time = None
        for span in soup.find_all("span"):
            if span.text and span.text.strip().startswith("Posted "):
                posted_time = span.text.strip()
                break

        # Parse the posted time to a datetime
        created_at = self._parse_relative_time(posted_time) or datetime.now()
        created_at_iso = created_at.isoformat()

        return {
            "description": description_text,
            "quick_apply": quick_apply,
            "created_at": created_at_iso,
            "location": location,
            "work_type": work_type,
        }


def create_scraper(platform: str, config: Dict) -> BaseScraper:
    """Factory function to create appropriate scraper instance."""
    scrapers = {"seek": SeekScraper}

    scraper_class = scrapers.get(platform.lower())
    if not scraper_class:
        raise ValueError(f"Unsupported platform: {platform}")

    return scraper_class(config)
