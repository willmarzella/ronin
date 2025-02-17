"""Indeed job board scraper."""

import time
import logging
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from urllib.parse import urlencode

from app.scrapers.base import BaseScraper


class IndeedJobScraper(BaseScraper):
    """Scraper for Indeed jobs."""

    def __init__(self, config: Dict):
        """Initialize the Indeed scraper."""
        super().__init__(config)
        self.base_url = "https://au.indeed.com/jobs"
        self.location = config.get("search", {}).get("location", "Australia")
        self.keywords = config.get("search", {}).get("keywords", [])
        self.driver = None
        self.is_logged_in = False

    def _setup_driver(self):
        """Initialize Chrome WebDriver with local browser"""
        if self.driver:
            return

        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)
        options.add_argument("--user-data-dir=chrome-data")
        options.add_argument("--profile-directory=Default")

        try:
            service = Service()
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.implicitly_wait(10)
            self.driver.set_window_size(1920, 1080)
            logging.info("Chrome WebDriver initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize Chrome WebDriver: {str(e)}")
            raise

    def _login(self):
        """Handle Indeed.com login process."""
        if self.is_logged_in:
            return

        try:
            self.driver.get("https://au.indeed.com")
            print("\n=== Login Required ===")
            print("1. Please sign in with Google in the browser window")
            print("2. Make sure you're fully logged in")
            print("3. Press Enter when ready to continue...")
            input()
            self.is_logged_in = True
            logging.info("Successfully logged into Indeed")
        except Exception as e:
            raise Exception(f"Failed to login to Indeed: {str(e)}")

    def build_search_url(self, page: int) -> str:
        """Build the search URL for the given page number."""
        keyword_string = (
            self.keywords
            if isinstance(self.keywords, str)
            else " ".join(self.keywords) if isinstance(self.keywords, list) else ""
        )
        location = self.location.replace("All ", "")

        params = {
            "q": keyword_string,
            "l": location,
            "sort": "date",
            "fromage": "14",
            "start": (page - 1) * 10,
        }

        return f"{self.base_url}?{urlencode(params)}"

    def find_job_elements(self, soup: Optional[BeautifulSoup] = None) -> List:
        """Find all job elements on the current page."""
        try:
            WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located((By.CLASS_NAME, "job_seen_beacon"))
            )
            return self.driver.find_elements(By.CLASS_NAME, "job_seen_beacon")
        except (TimeoutException, Exception) as e:
            logging.error(f"Error finding job elements: {str(e)}")
            return []

    def extract_job_info(self, job_element: BeautifulSoup) -> Optional[Dict]:
        """Extract job information from a job card/element."""
        try:
            # Get basic info before clicking
            title_element = job_element.find_element(By.CLASS_NAME, "jcs-JobTitle")
            title = title_element.find_element(By.TAG_NAME, "span").text
            job_id = title_element.get_attribute("id").replace("job_", "")
            job_url = title_element.get_attribute("href")
            company = job_element.find_element(
                By.CSS_SELECTOR, "[data-testid='company-name']"
            ).text
            location = job_element.find_element(
                By.CSS_SELECTOR, "[data-testid='text-location']"
            ).text

            # Click using JavaScript
            self.driver.execute_script("arguments[0].click();", title_element)

            # Check for quick apply
            quick_apply = False
            try:
                apply_elem = job_element.find_element(
                    By.CSS_SELECTOR, "[data-testid='indeedApply']"
                )
                quick_apply = "Easily apply" in apply_elem.text
            except NoSuchElementException:
                pass

            # Get description
            description = ""
            try:
                description_elem = WebDriverWait(self.driver, 1).until(
                    EC.presence_of_element_located((By.ID, "jobDescriptionText"))
                )
                description = description_elem.text
            except (TimeoutException, NoSuchElementException):
                try:
                    description = job_element.find_element(
                        By.CSS_SELECTOR, "[class*='job-snippet']"
                    ).text
                except NoSuchElementException:
                    logging.warning(f"No description found for job {job_id}")

            return {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "url": job_url,
                "description": description,
                "source": "indeed",
                "quick_apply": quick_apply,
                "created_at": time.strftime("%Y-%m-%d"),
            }

        except Exception as e:
            logging.error(f"Error extracting job info: {str(e)}")
            return None

    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get detailed information for a specific job."""
        # For Indeed, we get all details during initial extraction
        return None

    def scrape_jobs(self) -> List[Dict]:
        """Scrape jobs from Indeed using Selenium."""
        jobs = []
        page = 1
        total_jobs = 0

        try:
            if not self.driver:
                self._setup_driver()
                self._login()

            # Handle cookie notice once at the start
            try:
                cookie_notice = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((By.ID, "CookiePrivacyNotice"))
                )
                if cookie_notice.is_displayed():
                    accept_button = self.driver.find_element(
                        By.CSS_SELECTOR, "[data-gnav-element-name='Cookies.accept']"
                    )
                    accept_button.click()
            except (TimeoutException, NoSuchElementException):
                pass

            while True:
                url = self.build_search_url(page)
                self.driver.get(url)

                job_elements = self.find_job_elements()
                print(f"Found {len(job_elements)} job elements on page {page}")
                if not job_elements:
                    break

                for job_element in job_elements:
                    if self.max_jobs and total_jobs >= self.max_jobs:
                        return jobs

                    job_info = self.extract_job_info(job_element)
                    if job_info:
                        jobs.append(job_info)
                        total_jobs += 1
                    print(f"Extracted job info for job {job_info['job_id']}")

                page += 1

            return jobs

        except Exception as e:
            logging.error(f"Error during job scraping: {str(e)}")
            return jobs
        finally:
            if self.driver:
                self.driver.quit()
                self.driver = None
