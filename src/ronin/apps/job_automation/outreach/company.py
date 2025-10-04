"""Company-related functionality for LinkedIn outreach."""

import logging
import random
import time
from typing import Any, Dict, Optional

from selenium.webdriver.common.by import By


class LinkedInCompanyHandler:
    """Class to handle company-related operations on LinkedIn."""

    def __init__(self, driver):
        """Initialize with a Selenium WebDriver instance."""
        self.driver = driver
        self.logger = logging.getLogger(__name__)

    def extract_company_info(self) -> Dict[str, Any]:
        """
        Extract company information from the current company page.

        Returns:
            Dictionary with company information
        """
        company_info = {
            "name": "",
            "description": "",
            "company_size": "",
            "industry": "",
            "website": "",
            "headquarters": "",
            "linkedin_url": "",
        }

        try:
            self.logger.info("Starting company information extraction")
            company_info["linkedin_url"] = self.driver.current_url
            self.logger.info(f"Current company URL: {company_info['linkedin_url']}")

            # Extract company name from header
            try:
                self.logger.info("Attempting to extract company name...")
                company_name_element = self.driver.find_element(
                    By.CSS_SELECTOR,
                    ".org-top-card-summary__title, h1[class*='org-top-card-summary__title']",
                )
                company_info["name"] = company_name_element.text.strip()
                self.logger.info(
                    f"Successfully extracted company name: {company_info['name']}"
                )
            except Exception as e:
                self.logger.warning(f"Could not extract company name: {str(e)}")

            # Navigate directly to the About page instead of clicking on the tab
            try:
                # Get the current URL and check if we're already on the about page
                current_url = self.driver.current_url
                if "/about/" not in current_url:
                    # Construct the about URL and navigate to it
                    about_url = current_url
                    if about_url.endswith("/"):
                        about_url += "about/"
                    else:
                        about_url += "/about/"

                    self.logger.info(f"Navigating to about page: {about_url}")
                    self.driver.get(about_url)
                    self.logger.info("Waiting for about page to load...")
                    time.sleep(random.uniform(2, 4))

                # Extract description
                try:
                    self.logger.info("Attempting to extract company description...")
                    description_selectors = [
                        ".org-about-us-organization-description__text",
                        "[data-test-id='about-us__description']",
                        "[data-test-id='organization-about-description']",
                        "p.break-words.white-space-pre-wrap.t-black--light.text-body-medium",
                        "section.artdeco-card p.break-words",
                        "section.artdeco-card p",
                    ]

                    for selector in description_selectors:
                        try:
                            self.logger.info(f"Trying selector: {selector}")
                            description = self.driver.find_element(
                                By.CSS_SELECTOR, selector
                            )
                            if description and description.text.strip():
                                company_info["description"] = description.text.strip()
                                self.logger.info(
                                    "Successfully extracted company description"
                                )
                                break
                        except Exception:
                            self.logger.debug(
                                f"Selector {selector} not found, trying next..."
                            )
                            continue

                    if not company_info["description"]:
                        self.logger.warning(
                            "Company description not found with any selector"
                        )
                except Exception as e:
                    self.logger.warning(
                        f"Could not extract company description: {str(e)}"
                    )

                # Extract other company details
                try:
                    self.logger.info(
                        "Attempting to extract additional company details..."
                    )
                    # New approach to extract details from the definition list
                    dt_selectors = [
                        "section.artdeco-card dl dt",
                        "dl.overflow-hidden dt",
                    ]

                    dt_elements = []
                    for selector in dt_selectors:
                        try:
                            self.logger.info(
                                f"Looking for details with selector: {selector}"
                            )
                            elements = self.driver.find_elements(
                                By.CSS_SELECTOR, selector
                            )
                            if elements:
                                dt_elements = elements
                                self.logger.info(
                                    f"Found {len(elements)} detail elements"
                                )
                                break
                        except Exception:
                            self.logger.debug(
                                f"Selector {selector} not found, trying next..."
                            )
                            continue

                    for dt in dt_elements:
                        try:
                            # Extract the label (usually in an h3)
                            try:
                                heading = dt.find_element(By.TAG_NAME, "h3")
                                label = heading.text.strip().lower()
                                self.logger.info(f"Found detail label: {label}")
                            except Exception:
                                label = dt.text.strip().lower()
                                self.logger.info(f"Using text as label: {label}")

                            # Find the corresponding dd (definition description)
                            dd = dt.find_element(By.XPATH, "following-sibling::dd[1]")
                            if not dd:
                                self.logger.warning(
                                    f"No value found for label: {label}"
                                )
                                continue

                            value = dd.text.strip()
                            self.logger.info(f"Found value for {label}: {value}")

                            # Handle website which might be in an anchor
                            if "website" in label:
                                try:
                                    link = dd.find_element(By.TAG_NAME, "a")
                                    value = (
                                        link.get_attribute("href") or link.text.strip()
                                    )
                                    self.logger.info(f"Extracted website URL: {value}")
                                except Exception:
                                    self.logger.warning("Could not extract website URL")

                            # Map to the appropriate field
                            if "website" in label:
                                company_info["website"] = value
                            elif "industry" in label:
                                company_info["industry"] = value
                            elif "company size" in label:
                                # Get just the employee count, not the associated members
                                company_info["company_size"] = (
                                    value.split("\n")[0] if "\n" in value else value
                                )
                            elif "headquarters" in label:
                                company_info["headquarters"] = value
                        except Exception as e:
                            self.logger.warning(
                                f"Error extracting detail: {label if 'label' in locals() else 'unknown'}: {str(e)}"
                            )
                            continue
                except Exception as e:
                    self.logger.warning(f"Could not extract company details: {str(e)}")
            except Exception:
                self.logger.warning("Could not navigate to about page")

            self.logger.info("Company information extraction completed")
            self.logger.info(f"Extracted info for: {company_info['name']}")
            return company_info

        except Exception as e:
            self.logger.error(f"Error extracting company info: {str(e)}")
            return company_info

    def get_job_details(self, job_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Get details about a job posting.

        Args:
            job_url: URL of the job posting (if None, will use current page)

        Returns:
            Dictionary with job details
        """
        job_details = {
            "title": "",
            "company": "",
            "location": "",
            "description": "",
            "posted_date": "",
            "job_url": "",
        }

        try:
            self.logger.info(
                f"Starting job details extraction from: {job_url or 'current page'}"
            )

            # Navigate to job URL if provided
            if job_url:
                self.logger.info(f"Navigating to job URL: {job_url}")
                self.driver.get(job_url)
                self.logger.info("Waiting for job page to load...")
                time.sleep(random.uniform(3, 5))

            job_details["job_url"] = self.driver.current_url
            self.logger.info(f"Current job URL: {job_details['job_url']}")

            # Extract job title
            try:
                self.logger.info("Attempting to extract job title...")
                title_element = self.driver.find_element_by_css_selector(
                    ".top-card-layout__title"
                )
                job_details["title"] = title_element.text.strip()
                self.logger.info(
                    f"Successfully extracted job title: {job_details['title']}"
                )
            except Exception:
                self.logger.warning("Could not extract job title")

            # Extract company name
            try:
                self.logger.info("Attempting to extract company name...")
                company_element = self.driver.find_element_by_css_selector(
                    ".topcard__org-name-link"
                )
                job_details["company"] = company_element.text.strip()
                self.logger.info(
                    f"Successfully extracted company name: {job_details['company']}"
                )
            except Exception:
                self.logger.warning("Could not extract company name from job")

            # Extract location
            try:
                self.logger.info("Attempting to extract job location...")
                location_element = self.driver.find_element_by_css_selector(
                    ".topcard__flavor--bullet"
                )
                job_details["location"] = location_element.text.strip()
                self.logger.info(
                    f"Successfully extracted location: {job_details['location']}"
                )
            except Exception:
                self.logger.warning("Could not extract job location")

            # Extract description
            try:
                self.logger.info("Attempting to extract job description...")
                description_element = self.driver.find_element_by_css_selector(
                    ".description__text"
                )
                job_details["description"] = description_element.text.strip()
                self.logger.info("Successfully extracted job description")
            except Exception:
                self.logger.warning("Could not extract job description")

            # Extract posted date
            try:
                self.logger.info("Attempting to extract posted date...")
                date_element = self.driver.find_element_by_css_selector(
                    ".posted-time-ago__text"
                )
                job_details["posted_date"] = date_element.text.strip()
                self.logger.info(
                    f"Successfully extracted posted date: {job_details['posted_date']}"
                )
            except Exception:
                self.logger.warning("Could not extract job posted date")

            self.logger.info("Job details extraction completed")
            return job_details

        except Exception as e:
            self.logger.error(f"Error extracting job details: {str(e)}")
            return job_details
