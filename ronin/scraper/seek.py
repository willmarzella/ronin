"""Seek.com.au job board scraper."""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from loguru import logger

from ronin.scraper.base import BaseScraper


class SeekScraper(BaseScraper):
    """Scraper for Seek job board."""

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
        self.current_keyword_group_index = 0

    def _parse_search_keywords(self):
        """Parse search keywords from config."""
        keywords_list = self.search_config.get("keywords", [])

        if isinstance(keywords_list, str):
            keywords_list = [keywords_list]

        self.keyword_groups = keywords_list
        self.target_keywords = []

        for keyword_group in keywords_list:
            matches = re.findall(r'"([^"]*)"', keyword_group)
            parsed_keywords = [keyword.lower() for keyword in matches if keyword]

            if not parsed_keywords:
                parsed_keywords = [
                    k.strip().lower() for k in keyword_group.split("OR") if k.strip()
                ]

            self.target_keywords.extend(parsed_keywords)

        logger.debug(f"Parsed target keywords: {self.target_keywords}")
        logger.debug(f"Using {len(self.keyword_groups)} keyword groups for searches")

    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """Parse relative time string into datetime."""
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
        """Build the Seek search URL with parameters."""
        idx = (
            keyword_index
            if keyword_index is not None
            else self.current_keyword_group_index
        )

        if idx < 0 or idx >= len(self.keyword_groups):
            raise ValueError(f"Invalid keyword group index: {idx}")

        keyword_group = self.keyword_groups[idx]
        keywords = keyword_group.replace('"', "%22")

        location = self.search_config.get("location", "All Australia").replace(" ", "-")
        # Strip leading "in-" if the user already included it in config,
        # since we always prepend "in-" in the URL path.
        if location.lower().startswith("in-"):
            location = location[3:]

        salary_config = self.search_config.get("salary", {})
        salary_min = salary_config.get("min", 0)
        salary_max = salary_config.get("max", 999999)
        date_range = self.search_config.get("date_range", 30)

        params = {
            "daterange": date_range,
            "salaryrange": f"{salary_min}-{salary_max}",
            "salarytype": "annual",
            "sortmode": "ListedDate",
            "worktype": "242,244",
            "workarrangement": "2,3",
            "page": str(page),
        }

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.base_url}/{keywords}-jobs/in-{location}?{param_str}"
        logger.debug(f"Built search URL: {url}")
        return url

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

        matching_keyword = self._get_matching_keyword(job_title)
        if not matching_keyword:
            logger.debug(f"Skipping job: '{job_title}' - doesn't match target keywords")
            return None

        logger.debug(f"Found job '{job_title}' matching keyword '{matching_keyword}'")

        return {
            "job_id": job_id,
            "title": job_title,
            "company": company_element.text.strip() if company_element else "Unknown",
            "url": f"{self.base_url}/job/{job_id}",
            "source": "seek",
            "matching_keyword": matching_keyword,
        }

    def _get_matching_keyword(self, title: str) -> Optional[str]:
        """Check if job title contains any target keywords."""
        if not self.target_keywords:
            return "No keywords defined"

        title_lower = title.lower()

        for keyword in self.target_keywords:
            if " " in keyword:
                if keyword in title_lower:
                    return keyword
            else:
                word_pattern = r"\b{}\b".format(re.escape(keyword))
                if re.search(word_pattern, title_lower):
                    return keyword

        return None

    def clean_location(self, location: str) -> str:
        """Map location to standard city name."""
        if not location:
            return "Unknown"

        for state, city in self.LOCATION_MAPPING.items():
            if state in location:
                return city

        return location.strip()

    def get_job_previews(self) -> List[Dict[str, Any]]:
        """Get job previews by iterating through all keyword groups."""
        all_jobs_data = []
        seen_job_ids = set()

        for keyword_index in range(len(self.keyword_groups)):
            self.current_keyword_group_index = keyword_index

            jobs_data = self._get_jobs_for_current_keyword()

            for job in jobs_data:
                job_id = job.get("job_id")
                if job_id and job_id not in seen_job_ids:
                    seen_job_ids.add(job_id)
                    all_jobs_data.append(job)

            if self.max_jobs and len(all_jobs_data) >= self.max_jobs:
                break
        return all_jobs_data

    def _get_jobs_for_current_keyword(self) -> List[Dict[str, Any]]:
        """Get job previews for the current keyword group."""
        jobs_data = []
        page = 1
        jobs_per_page = 22
        max_pages = 50

        while page <= max_pages:
            if self.max_jobs and len(jobs_data) >= self.max_jobs:
                break

            url = self.build_search_url(page)
            soup = self.make_request(url)
            if not soup:
                break

            job_elements = soup.find_all("article", attrs={"data-card-type": "JobCard"})
            if not job_elements:
                logger.debug(f"No jobs found on page {page}")
                break

            logger.debug(f"Found {len(job_elements)} job previews on page {page}")

            for job_element in job_elements:
                if self.max_jobs and len(jobs_data) >= self.max_jobs:
                    break

                job_info = self.extract_job_info(job_element)
                if job_info:
                    jobs_data.append(job_info)

            if len(job_elements) < jobs_per_page:
                logger.debug("No more pages available")
                break

            page += 1

        return jobs_data

    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed job information for a specific job."""
        url = f"{self.base_url}/job/{job_id}"
        logger.debug(f"Fetching job details from: {url}")

        try:
            soup = self.make_request(url)
            if not soup:
                logger.error(f"Failed to get HTML content for job {job_id}")
                return None

            apply_button = soup.find("a", attrs={"data-automation": "job-detail-apply"})
            quick_apply = bool(
                apply_button and "Quick apply" in apply_button.get_text()
            )
            apply_type = "quick" if quick_apply else "external"
            # For external (link-out) applies, the apply destination is always
            # Seek's own /job/{id}/apply redirect, which only resolves to the
            # employer ATS after a click; the agent applier follows it at apply
            # time. Build it from the job id rather than reading the button
            # href: the href is absent on a chunk of detail pages (25 of 105
            # captured rows had none), and every href that WAS present matched
            # this pattern exactly.
            apply_url = None
            if not quick_apply:
                apply_url = f"https://www.seek.com.au/job/{job_id}/apply"
            if self.quick_apply_only and not quick_apply and not self.capture_external:
                logger.debug(
                    f"Job {job_id} is not quick apply; retaining for market-intel tagging"
                )

            description_element = soup.find(
                "div", attrs={"data-automation": "jobAdDetails"}
            )
            if not description_element:
                logger.error(f"Could not find job description element for job {job_id}")
                return None

            description_text = description_element.get_text(separator="\n").strip()
            # Clean control characters but preserve Unicode (accented names, bullets, etc.)
            import re as _re

            description_text = _re.sub(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", description_text
            )

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

            salary = self._extract_salary(soup)

            posted_time = None
            for span in soup.find_all("span"):
                if span.text and span.text.strip().startswith("Posted "):
                    posted_time = span.text.strip()
                    break

            created_at = self._parse_relative_time(posted_time) or datetime.now()
            created_at_iso = created_at.isoformat()

            job_details = {
                "description": description_text,
                "quick_apply": quick_apply,
                "apply_type": apply_type,
                "apply_url": apply_url,
                "created_at": created_at_iso,
                "location": location,
                "work_type": work_type,
                "salary": salary,
            }

            logger.debug(
                f"Successfully extracted details for job {job_id} (Location: {location}, Work Type: {work_type})"
            )
            return job_details

        except Exception as e:
            logger.exception(f"Error extracting job details for {job_id}: {str(e)}")
            return None

    def _extract_salary(self, soup: BeautifulSoup) -> str:
        """Extract salary information from job posting."""
        try:
            salary_selectors = [
                {"data-automation": "job-detail-salary"},
                {"data-automation": "salary-range"},
                {"data-automation": "job-salary"},
                {"class": "salary"},
                {"class": "salary-range"},
                {"class": "job-salary"},
            ]

            for selector in salary_selectors:
                element = soup.find(**selector)
                if element:
                    salary_text = element.text.strip()
                    if self._is_valid_salary(salary_text):
                        return salary_text

            for element in soup.find_all(string=True):
                text = element.strip()
                if "$" in text and self._is_valid_salary(text):
                    return text

            return "Not specified"

        except Exception as e:
            logger.warning(f"Error extracting salary: {e}")
            return "Not specified"

    def _is_valid_salary(self, text: str) -> bool:
        """Check if text looks like a valid salary/rate."""
        if not text or len(text.strip()) < 3:
            return False

        text_lower = text.lower()

        if "$" not in text:
            return False

        salary_keywords = [
            "salary",
            "rate",
            "pay",
            "package",
            "remuneration",
            "hourly",
            "daily",
            "annual",
            "per hour",
            "per day",
            "per annum",
        ]
        has_keyword = any(keyword in text_lower for keyword in salary_keywords)
        has_numbers = any(char.isdigit() for char in text)

        false_positives = ["$0", "free", "volunteer", "unpaid", "internship"]
        is_false_positive = any(fp in text_lower for fp in false_positives)

        return (
            (has_keyword or has_numbers)
            and not is_false_positive
            and len(text.strip()) < 100
        )
