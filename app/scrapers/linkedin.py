"""LinkedIn job board scraper."""

import time
import json
import logging
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import requests
from urllib.parse import urlencode

from app.scrapers.base import BaseScraper


class LinkedInScraper(BaseScraper):
    """Scraper for LinkedIn jobs."""

    def __init__(self, config: Dict):
        """Initialize the LinkedIn scraper."""
        super().__init__(config)
        self.base_url = "https://www.linkedin.com/jobs/search"
        self.location = config.get("search", {}).get("location", "Australia")
        self.keywords = config.get("search", {}).get("keywords", [])

        # Add LinkedIn-specific headers
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Referer": "https://www.linkedin.com/jobs",
            }
        )

    def build_search_url(self, page: int) -> str:
        """Build the search URL for the given page number."""
        params = {
            "keywords": " ".join(self.keywords),
            "location": self.location,
            "position": 1
            + ((page - 1) * 25),  # LinkedIn uses position-based pagination
            "pageNum": page,
            "f_TPR": "r86400",  # Last 24 hours
            "f_WT": "2",  # Remote jobs
            "f_JT": "F",  # Full-time
            "sortBy": "DD",  # Most recent
        }
        return f"{self.base_url}?{urlencode(params)}"

    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict]:
        """Extract job information from a job card."""
        try:
            # Extract basic job info
            job_id = job_element.get("data-job-id")
            if not job_id:
                return None

            title_elem = job_element.find("h3", class_="base-search-card__title")
            company_elem = job_element.find("h4", class_="base-search-card__subtitle")
            location_elem = job_element.find("span", class_="job-search-card__location")

            job_info = {
                "id": job_id,
                "title": title_elem.text.strip() if title_elem else "",
                "company": company_elem.text.strip() if company_elem else "",
                "location": location_elem.text.strip() if location_elem else "",
                "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                "source": "linkedin",
                "tech_stack": [],  # Will be populated from job details
                "salary_range": "",
                "job_type": "Full-time",
                "remote": True,
            }

            # Try to extract salary if available
            salary_elem = job_element.find(
                "span", class_="job-search-card__salary-info"
            )
            if salary_elem:
                job_info["salary_range"] = salary_elem.text.strip()

            return job_info

        except Exception as e:
            logging.error(f"Error extracting job info: {str(e)}")
            return None

    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get detailed information for a specific job."""
        try:
            url = f"https://www.linkedin.com/jobs/view/{job_id}/"
            soup = self.make_request(url)
            if not soup:
                return None

            # Extract job description
            description_elem = soup.find("div", class_="show-more-less-html__markup")
            if not description_elem:
                return None

            description = description_elem.get_text(separator="\n").strip()

            # Extract additional details
            details = {
                "description": description,
                "requirements": [],
                "benefits": [],
                "tech_stack": [],
            }

            # Try to extract requirements
            requirements_section = soup.find(
                "div", string=lambda x: x and "Requirements" in x
            )
            if requirements_section:
                ul = requirements_section.find_next("ul")
                if ul:
                    details["requirements"] = [
                        li.text.strip() for li in ul.find_all("li")
                    ]

            # Try to extract benefits
            benefits_section = soup.find("div", string=lambda x: x and "Benefits" in x)
            if benefits_section:
                ul = benefits_section.find_next("ul")
                if ul:
                    details["benefits"] = [li.text.strip() for li in ul.find_all("li")]

            # Extract tech stack from description
            tech_keywords = self.config.get("tech_keywords", [])
            for tech in tech_keywords:
                if tech.lower() in description.lower():
                    details["tech_stack"].append(tech)

            return details

        except Exception as e:
            logging.error(f"Error getting job details: {str(e)}")
            return None

    def find_job_elements(self, soup: BeautifulSoup) -> List:
        """Find all job elements on the page."""
        return soup.find_all(
            "div",
            class_="base-card relative w-full hover:no-underline focus:no-underline base-card--link base-search-card base-search-card--link job-search-card",
        )

    def scrape_jobs(self) -> List[Dict]:
        """
        Scrape jobs from LinkedIn.

        Returns:
            List of job data dictionaries
        """
        jobs = []
        page = 1
        total_jobs = 0

        while True:
            url = self.build_search_url(page)
            soup = self.make_request(url)
            if not soup:
                break

            job_elements = self.find_job_elements(soup)
            if not job_elements:
                break

            for job_element in job_elements:
                if self.max_jobs and total_jobs >= self.max_jobs:
                    return jobs

                job_info = self.extract_job_info(job_element)
                if not job_info:
                    continue

                # Get detailed job information
                details = self.get_job_details(job_info["id"])
                if details:
                    job_info.update(details)

                jobs.append(job_info)
                total_jobs += 1

                # Respect rate limiting
                time.sleep(self.delay)

            # Check if there are more pages
            next_button = soup.find("button", {"aria-label": "Next"})
            if not next_button or "disabled" in next_button.get("class", []):
                break

            page += 1

        return jobs
