"""Indeed job board scraper."""

import time
import json
import logging
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import requests
from urllib.parse import urlencode

from app.scrapers.base import BaseScraper


class IndeedScraper(BaseScraper):
    """Scraper for Indeed jobs."""

    def __init__(self, config: Dict):
        """Initialize the Indeed scraper."""
        super().__init__(config)
        self.base_url = "https://au.indeed.com/jobs"
        self.location = config.get("search", {}).get("location", "Australia")
        self.keywords = config.get("search", {}).get("keywords", [])

        # Add Indeed-specific headers
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )

    def build_search_url(self, page: int) -> str:
        """Build the search URL for the given page number."""
        params = {
            "q": " ".join(self.keywords.replace(" ", "+").lower()),
            "l": self.location,
            "sort": "date",  # Sort by date
            "fromage": "1",  # Last 24 hours
            "start": (page - 1) * 15,  # Indeed uses 15 jobs per page
        }
        return f"{self.base_url}?{urlencode(params)}"

    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict]:
        """Extract job information from a job card."""
        try:
            # Extract job ID from the parent container
            job_id = job_element.get("data-jk")
            if not job_id:
                return None

            # Extract basic job information
            title_elem = job_element.find("h2", class_="jobTitle")
            company_elem = job_element.find("span", {"data-testid": "company-name"})
            location_elem = job_element.find("div", {"data-testid": "text-location"})

            # Check for quick apply
            quick_apply = False
            apply_elem = job_element.find("span", {"data-testid": "indeedApply"})
            if apply_elem and "Easily apply" in apply_elem.text:
                quick_apply = True

            job_info = {
                "id": job_id,
                "title": title_elem.text.strip() if title_elem else "",
                "company": company_elem.text.strip() if company_elem else "",
                "location": location_elem.text.strip() if location_elem else "",
                "url": f"https://au.indeed.com/viewjob?jk={job_id}",
                "source": "indeed",
                "tech_stack": [],  # Will be populated from job details
                "salary_range": "",
                "job_type": "Full-time",
                "remote": True,
                "quick_apply": quick_apply,  # Add quick apply status
            }

            # Try to extract salary information
            salary_elem = job_element.find("div", class_="salary-snippet")
            if salary_elem:
                job_info["salary_range"] = salary_elem.text.strip()
            else:
                # Try metadata salary
                meta_salary = job_element.find(
                    "div", class_="metadata salary-snippet-container"
                )
                if meta_salary:
                    job_info["salary_range"] = meta_salary.text.strip()

            return job_info

        except Exception as e:
            logging.error(f"Error extracting job info: {str(e)}")
            return None

    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get detailed information for a specific job."""
        try:
            url = f"https://au.indeed.com/viewjob?jk={job_id}"
            soup = self.make_request(url)
            if not soup:
                return None

            # Extract job description
            description_elem = soup.find("div", id="jobDescriptionText")
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

            # Try to extract requirements (Indeed often has them in lists)
            requirements_lists = description_elem.find_all("ul")
            for ul in requirements_lists:
                # Check if this list is likely requirements
                list_text = ul.get_text().lower()
                if any(
                    keyword in list_text
                    for keyword in ["require", "qualification", "skill"]
                ):
                    details["requirements"].extend(
                        [li.text.strip() for li in ul.find_all("li")]
                    )

            # Try to extract benefits
            benefits_section = soup.find("div", id="benefits")
            if benefits_section:
                benefits_list = benefits_section.find_all("li")
                details["benefits"] = [
                    benefit.text.strip() for benefit in benefits_list
                ]

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
        return soup.find_all("div", class_="job_seen_beacon")

    def scrape_jobs(self) -> List[Dict]:
        """
        Scrape jobs from Indeed.

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
            next_button = soup.find("a", {"aria-label": "Next"})
            if not next_button:
                break

            page += 1

        return jobs
