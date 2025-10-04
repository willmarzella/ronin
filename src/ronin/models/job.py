"""Core job scraping functionality."""

from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger


class JobScraper:
    """Base class for job scraping functionality."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.114 Safari/537.36"
                )
            }
        )

    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get detailed information for a specific job."""
        try:
            url = f"https://www.seek.com.au/job/{job_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Find the job description
            description = soup.find("div", attrs={"data-automation": "jobDescription"})
            if not description:
                return None

            # Check if quick apply is available
            quick_apply = bool(
                soup.find("button", attrs={"data-automation": "job-detail-apply"})
            )

            return {
                "description": description.get_text(separator="\n").strip(),
                "quick_apply": quick_apply,
            }

        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {str(e)}")
            return None

    def extract_job_id(self, job_card):
        """Extract job ID from the job card"""
        try:
            title_element = job_card.find("a", attrs={"data-automation": "jobTitle"})
            if not title_element or not title_element.get("href"):
                return None

            href = title_element["href"]
            job_id = href.split("/")[-1]
            return job_id.split("?")[0]
        except Exception as e:
            logger.error(f"Error extracting job ID: {str(e)}")
            return None

    def extract_job_info(self, job_card):
        """Extract basic job information from a job card"""
        try:
            title_element = job_card.find("a", attrs={"data-automation": "jobTitle"})
            if not title_element:
                return None

            company_element = job_card.find(
                "a", attrs={"data-automation": "jobCompany"}
            )

            # Add quick apply check to the job info
            is_quick = self.is_quick_apply(job_card)

            return {
                "title": title_element.text.strip(),
                "company": (
                    company_element.text.strip()
                    if company_element
                    else "Company not listed"
                ),
                "job_id": self.extract_job_id(job_card),
                "quick_apply": is_quick,
            }
        except Exception as e:
            logger.error(f"Error extracting job info: {str(e)}")
            return None

    def is_quick_apply(self, job_card):
        """Check if the job is quick apply"""
        try:
            # Find the apply button using the consistent data-automation attribute
            apply_button = job_card.find(
                "a", attrs={"data-automation": "job-detail-apply"}
            )
            if apply_button:
                logger.info("Quick apply button found")
                return any(
                    "Quick apply" in elem.text for elem in apply_button.find_all()
                )
            return False
        except Exception as e:
            logger.error(f"Error checking if job is quick apply: {str(e)}")
            return False
