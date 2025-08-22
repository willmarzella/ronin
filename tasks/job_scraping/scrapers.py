"""Job board scrapers for various platforms."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple, Union
from datetime import datetime, timedelta
import re
import time
import functools
import json
import logging
import random

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
        self.search_config = config.get("search", {})
        self._parse_search_keywords()
        # Track which keyword group we're currently searching
        self.current_keyword_group_index = 0

    def _parse_search_keywords(self):
        """Parse search keywords from the config which is now a list of OR-separated queries."""
        keywords_list = self.search_config.get("keywords", [])

        # Handle both string and list configurations for backward compatibility
        if isinstance(keywords_list, str):
            keywords_list = [keywords_list]

        # Store both the raw keyword groups and the parsed individual keywords
        self.keyword_groups = keywords_list
        self.target_keywords = []

        # Extract all individual keywords from all groups
        for keyword_group in keywords_list:
            # Use regex to find all quoted strings in this group
            matches = re.findall(r'"([^"]*)"', keyword_group)
            parsed_keywords = [keyword.lower() for keyword in matches if keyword]

            if not parsed_keywords:
                # Fallback if no quoted terms found - split by OR and strip
                parsed_keywords = [
                    k.strip().lower() for k in keyword_group.split("OR") if k.strip()
                ]

            # Add these keywords to our master list
            self.target_keywords.extend(parsed_keywords)

        print(f"Parsed target keywords: {self.target_keywords}")
        print(f"Using {len(self.keyword_groups)} keyword groups for searches")

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

    def build_search_url(self, page: int, keyword_index: Optional[int] = None) -> str:
        """Build the Seek search URL with parameters for a specific keyword group."""
        # Determine which keyword group to use
        if keyword_index is not None:
            idx = keyword_index
        else:
            idx = self.current_keyword_group_index

        # Make sure the index is valid
        if idx < 0 or idx >= len(self.keyword_groups):
            raise ValueError(f"Invalid keyword group index: {idx}")

        # Get the keyword group for this search
        keyword_group = self.keyword_groups[idx]

        # For URL construction, we strip quotes and replace spaces with hyphens
        keywords = keyword_group.replace('"', "").replace(" OR ", "-OR-")
        keywords = keywords.replace(" ", "-")

        print(f"Using keyword group {idx}: {keyword_group} -> URL format: {keywords}")

        location = self.search_config.get("location", "All Australia").replace(" ", "-")
        salary_config = self.search_config.get("salary", {})
        salary_min = salary_config.get("min", 0)
        salary_max = salary_config.get("max", 999999)
        date_range = self.search_config.get("date_range", 30)

        print(
            f"Building URL with: {keywords}, {location}, {salary_min}-{salary_max}, {date_range}"
        )

        params = {
            "daterange": date_range,
            "salaryrange": f"{salary_min}-{salary_max}",
            "salarytype": "annual",
            "sortmode": "ListedDate",
            "page": str(page),
        }

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        return (
            f"{self.base_url}/{keywords}-jobs/in-{location}/contract-temp?{param_str}"
        )

    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Extract job preview information from a job card."""

        job_id = job_element.get("data-job-id")
        if not job_id:
            return None

        title_element = job_element.find("a", attrs={"data-automation": "jobTitle"})
        company_element = job_element.find("a", attrs={"data-automation": "jobCompany"})

        if not title_element:
            return None

        job_title = title_element.text.strip()

        # Validate that the job title contains at least one of the target keywords
        matching_keyword = self._get_matching_keyword(job_title)
        if not matching_keyword:
            logger.debug(f"Skipping job: '{job_title}' - doesn't match target keywords")
            return None

        logger.info(f"Found job '{job_title}' matching keyword '{matching_keyword}'")

        return {
            "job_id": job_id,
            "title": job_title,
            "company": company_element.text.strip() if company_element else "Unknown",
            "url": f"{self.base_url}/job/{job_id}",
            "source": "seek",
            "matching_keyword": matching_keyword,
        }

    def _get_matching_keyword(self, title: str) -> Optional[str]:
        """Check if job title contains any of the target keywords and return the matching keyword."""
        if not self.target_keywords:
            return "No keywords defined"

        title_lower = title.lower()

        # Check if any of the target keywords are in the title
        for keyword in self.target_keywords:
            # For multi-word keywords, we want to match the exact phrase
            if " " in keyword:
                if keyword in title_lower:
                    return keyword
            else:
                # For single-word keywords, check for word boundaries
                # This prevents matching 'data' in 'database administrator'
                word_pattern = r"\b{}\b".format(re.escape(keyword))
                if re.search(word_pattern, title_lower):
                    return keyword

        return None

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
        """Get job previews with minimal information by iterating through all keyword groups."""
        all_jobs_data = []
        seen_job_ids = (
            set()
        )  # To avoid duplicate jobs across different keyword searches

        # Iterate through each keyword group
        for keyword_index in range(len(self.keyword_groups)):
            self.current_keyword_group_index = keyword_index
            print(
                f"\n--- Searching with keyword group {keyword_index + 1}/{len(self.keyword_groups)}: {self.keyword_groups[keyword_index]} ---\n"
            )

            # Search for this keyword group
            jobs_data = self._get_jobs_for_current_keyword()

            # Add new jobs to our combined results
            for job in jobs_data:
                job_id = job.get("job_id")
                if job_id and job_id not in seen_job_ids:
                    seen_job_ids.add(job_id)
                    all_jobs_data.append(job)

            print(
                f"Found {len(jobs_data)} jobs for keyword group {keyword_index + 1}, "
                f"total unique jobs so far: {len(all_jobs_data)}"
            )

            # Check if we've reached the max jobs limit
            if self.max_jobs and len(all_jobs_data) >= self.max_jobs:
                print(f"Reached maximum jobs limit ({self.max_jobs})")
                break

        print(
            f"Total unique jobs found across all keyword groups: {len(all_jobs_data)}"
        )
        return all_jobs_data

    def _get_jobs_for_current_keyword(self) -> List[Dict[str, Any]]:
        """Get job previews for the current keyword group."""
        assert hasattr(self, "max_jobs"), "max_jobs must be set"
        assert isinstance(
            self.max_jobs, (int, type(None))
        ), "max_jobs must be integer or None"

        jobs_data = []
        page = 1
        jobs_per_page = 22  # Seek typically shows 22 jobs per page
        max_pages = 50  # Fixed upper bound for pages to prevent infinite loops

        while page <= max_pages:  # Fixed upper bound
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

            if len(job_elements) < jobs_per_page:
                logger.info("No more pages available")
                break

            page += 1

        return jobs_data

    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed job information for a specific job."""
        url = f"{self.base_url}/job/{job_id}"
        logger.info(f"Fetching job details from: {url}")

        try:
            soup = self.make_request(url)
            if not soup:
                logger.error(f"Failed to get HTML content for job {job_id}")
                return None

            # Check if job has quick apply first to avoid unnecessary processing
            apply_button = soup.find("a", attrs={"data-automation": "job-detail-apply"})
            quick_apply = apply_button and "Quick apply" in apply_button.get_text()

            # If quick_apply_only is enabled and this job doesn't have quick apply, return None
            if self.quick_apply_only and not quick_apply:
                logger.info(f"Skipping job {job_id} - Quick apply not available")
                return None

            # Extract job description
            description_element = soup.find(
                "div", attrs={"data-automation": "jobAdDetails"}
            )
            if not description_element:
                logger.error(f"Could not find job description element for job {job_id}")
                return None

            # Clean up description text
            description_text = description_element.get_text(separator="\n").strip()
            description_text = description_text.encode("ascii", "ignore").decode(
                "ascii"
            )
            logger.debug(
                f"Extracted description of length {len(description_text)} for job {job_id}"
            )

            # Extract location and work type
            location_element = soup.find(
                "span", attrs={"data-automation": "job-detail-location"}
            )
            location = (
                self.clean_location(location_element.text.strip())
                if location_element
                else "Unknown"
            )

            work_type_element = soup.find(
                "span", attrs={"data-automation": "job-detail-work-type"}
            )
            work_type = (
                work_type_element.text.strip() if work_type_element else "Unknown"
            )

            # Posted time information
            posted_time = None
            for span in soup.find_all("span"):
                if span.text and span.text.strip().startswith("Posted "):
                    posted_time = span.text.strip()
                    break

            # Parse the posted time to a datetime
            created_at = self._parse_relative_time(posted_time) or datetime.now()
            created_at_iso = created_at.isoformat()

            # Build the job details dictionary
            job_details = {
                "description": description_text,
                "quick_apply": quick_apply,
                "created_at": created_at_iso,
                "location": location,
                "work_type": work_type,
            }

            logger.info(
                f"Successfully extracted details for job {job_id} (Location: {location}, Work Type: {work_type})"
            )
            return job_details

        except Exception as e:
            logger.exception(f"Error extracting job details for {job_id}: {str(e)}")
            return None


def create_scraper(platform: str, config: Dict) -> BaseScraper:
    """Factory function to create appropriate scraper instance."""
    scrapers = {"seek": SeekScraper}

    scraper_class = scrapers.get(platform.lower())
    if not scraper_class:
        raise ValueError(f"Unsupported platform: {platform}")

    return scraper_class(config)
