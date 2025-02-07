"""Seek.com job board scraper."""

from loguru import logger
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import re
from app.scrapers.base import BaseScraper


class SeekJobScraper(BaseScraper):
    """Scraper for Seek job board."""

    def __init__(self, config: Dict):
        """Initialize the scraper with config."""
        super().__init__(config)
        self.base_url = "https://www.seek.com.au"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """
        Parse relative time string into datetime object.
        Examples: "Posted 1d ago", "Posted 30m ago", "Posted 2h ago"
        """
        try:
            # Extract the number and unit from the string
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
        """Build the search URL for the given page.

        Example URL:
        https://www.seek.com.au/data-engineer-jobs/in-All-Australia?daterange=7&salaryrange=120000-200000&salarytype=annual&sortmode=ListedDate&page=1
        """

        keywords = self.config["search"]["keywords"].replace(" ", "-").lower()
        location = self.config["search"]["location"].replace(" ", "-")
        date_range = self.config["search"].get("date_range", 7)
        salary_min = self.config["search"]["salary"]["min"]
        salary_max = self.config["search"]["salary"]["max"]
        salary_type = self.config["search"]["salary"]["type"]
        sort_mode = self.config["search"].get("sort_mode", "ListedDate")

        # Build URL with parameters
        url = f"{self.base_url}/{keywords}-jobs/in-{location}"
        params = {
            "daterange": str(date_range),
            "salaryrange": f"{salary_min}-{salary_max}",
            "salarytype": salary_type,
            "sortmode": sort_mode,
            "page": str(page),
        }

        # Add parameters to URL
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{url}?{param_str}"

    def find_job_elements(self, soup: BeautifulSoup) -> List:
        """Find all job elements on the page."""
        return soup.find_all("article", attrs={"data-card-type": "JobCard"})

    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict]:
        """Extract basic job information from a job card."""
        try:
            # Extract job ID
            job_id = job_element.get("data-job-id")
            if not job_id:
                return None

            # Extract job title
            title_element = job_element.find("a", attrs={"data-automation": "jobTitle"})
            if not title_element:
                return None

            # Extract company name
            company_element = job_element.find(
                "a", attrs={"data-automation": "jobCompany"}
            )

            # Extract location
            location_element = job_element.find(
                "a", attrs={"data-automation": "jobLocation"}
            )

            # Extract salary
            salary_element = job_element.find(
                "span", attrs={"data-automation": "jobSalary"}
            )

            return {
                "job_id": job_id,
                "title": title_element.text.strip(),
                "company": (
                    company_element.text.strip() if company_element else "Unknown"
                ),
                "location": (
                    location_element.text.strip() if location_element else "Unknown"
                ),
                "salary": (
                    salary_element.text.strip() if salary_element else "Not specified"
                ),
                "url": f"https://www.seek.com.au/job/{job_id}",
                "source": "seek",
            }

        except Exception as e:
            logger.error(f"Error extracting job info: {str(e)}")
            return None

    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get detailed job information from the job page."""
        try:
            url = f"https://www.seek.com.au/job/{job_id}"
            soup = self.make_request(url)
            if not soup:
                return None

            # Find the type of work
            work_type_elem = soup.find(
                "span", {"data-automation": "job-detail-work-type"}
            )
            if work_type_elem:
                work_type = work_type_elem.text.strip()
            else:
                work_type = "Unknown"

            # Find the pay rate
            pay_rate_elem = soup.find("span", {"data-automation": "job-detail-salary"})
            if pay_rate_elem:
                pay_rate = pay_rate_elem.text.strip()
            else:
                pay_rate = "Unknown"

            # Find the location
            location_elem = soup.find(
                "span", {"data-automation": "job-detail-location"}
            )
            if location_elem:
                location = location_elem.text.strip()
            else:
                location = "Unknown"

            # Find the job description
            description_element = soup.find(
                "div", attrs={"data-automation": "jobAdDetails"}
            )
            if not description_element:
                return None

            # Check if quick apply is available by finding the apply button and checking its text
            apply_button = soup.find("a", attrs={"data-automation": "job-detail-apply"})
            quick_apply = apply_button and "Quick apply" in apply_button.get_text()

            # Get posted time - find all elements with the class and filter for the one starting with "Posted"
            posted_elements = soup.find_all(
                "span",
                class_="snwpn00 l1r1184z _1l99f880 _1l99f881 _1l99f8822 v7shb4 _1l99f887",
            )
            posted_time = None
            for element in posted_elements:
                text = element.text.strip()
                if text.startswith("Posted"):
                    posted_time = self._parse_relative_time(text)
                    break

            # Get additional metadata
            metadata = self._extract_metadata(soup)

            # Ensure we have a created_at date
            created_at = None
            if posted_time:
                created_at = posted_time.isoformat()
            elif metadata.get("listed_date"):
                # Try to parse from metadata if available
                try:
                    listed_date = self._parse_relative_time(metadata["listed_date"])
                    if listed_date:
                        created_at = listed_date.isoformat()
                except Exception as e:
                    # Handle exception
                    print(f"An error occurred: {e}")

            if not created_at:
                created_at = datetime.now().isoformat()  # Fallback to current time

            return {
                "description": description_element.get_text(separator="\n").strip(),
                "quick_apply": quick_apply,
                "created_at": created_at,
                "work_type": work_type,
                "pay_rate": pay_rate,
                "location": location,
                **metadata,
            }

        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {str(e)}")
            return None

    # def _extract_metadata(self, job_card: BeautifulSoup) -> Dict:
    #     """Extract additional metadata from the job card."""
    #     metadata = {}

    #     # Extract work type (e.g., "Full time", "Part time", etc.)
    #     work_type_elem = job_card.find("span", {"data-automation": "jobWorkType"})
    #     if work_type_elem:
    #         metadata["work_type"] = work_type_elem.text.strip()

    #     # Extract job classification
    #     classification_elem = job_card.find(
    #         "a", {"data-automation": "jobClassification"}
    #     )
    #     if classification_elem:
    #         metadata["classification"] = classification_elem.text.strip()

    #     # Extract listed date
    #     listed_date_elem = job_card.find("span", {"data-automation": "jobListingDate"})
    #     if listed_date_elem:
    #         metadata["listed_date"] = listed_date_elem.text.strip()

    #     # Extract salary if available
    #     salary_elem = job_card.find("span", {"data-automation": "jobSalary"})
    #     if salary_elem:
    #         metadata["salary"] = salary_elem.text.strip()

    #     return metadata


    def scrape_jobs(self) -> List[Dict]:
        """
        Scrape jobs from Seek.

        Returns:
            List of raw job data (without analysis)
        """
        jobs_data = []
        page = 1
        jobs_processed = 0

        while True:
            if self.max_jobs and jobs_processed >= self.max_jobs:
                break

            url = self.build_search_url(page)
            logger.info(f"Scraping page {page}")

            soup = self.make_request(url)
            if not soup:
                break

            job_elements = self.find_job_elements(soup)
            if not job_elements:
                logger.info(f"No more jobs found on page {page}")
                break

            logger.info(f"Found {len(job_elements)} jobs on page {page}")

            for job_element in job_elements:
                if self.max_jobs and jobs_processed >= self.max_jobs:
                    break

                job_info = self.extract_job_info(job_element)
                if not job_info:
                    continue

                job_details = self.get_job_details(job_info["job_id"])
                if job_details:
                    jobs_data.append({**job_info, **job_details})
                    jobs_processed += 1
                    logger.info(
                        f"Scraped job {jobs_processed}/{self.max_jobs if self.max_jobs else 'unlimited'}: {job_info['title']}"
                    )

            page += 1

        logger.info(
            f"Completed scraping. Found {len(jobs_data)} jobs across {page-1} pages"
        )
        return jobs_data
