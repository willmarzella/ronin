"""Implements the logic to apply to jobs on Workforce Australia (Centrelink)"""

from typing import Dict, Optional
import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from core.config import load_config
from services.airtable_service import AirtableManager
from tasks.job_application.chrome import ChromeDriver


class CentrelinkApplier:
    """Handles job applications on Workforce Australia (Centrelink)."""

    def __init__(self):
        self.config = load_config()
        self.airtable = AirtableManager()
        self.chrome_driver = ChromeDriver()
        self.base_url = "https://www.workforceaustralia.gov.au"

    def _login_centrelink(self):
        """Handle Workforce Australia login process."""
        if self.chrome_driver.is_logged_in:
            return

        try:
            self.chrome_driver.navigate_to(f"{self.base_url}/individuals/jobs/search")

            print("\n=== Login Required ===")
            print("1. Please sign in to Workforce Australia in the browser window")
            print("2. Make sure you're fully logged in")
            print("3. Press Enter when ready to continue...")
            input()

            self.chrome_driver.is_logged_in = True
            logging.info("Successfully logged into Workforce Australia")

        except Exception as e:
            raise Exception(f"Failed to login to Workforce Australia: {str(e)}")

    def _navigate_to_job_search(self):
        """Navigate to the job search page."""
        try:
            search_url = f"{self.base_url}/individuals/jobs/search?searchText=&sort=DateAddedDescending"
            self.chrome_driver.navigate_to(search_url)
            time.sleep(2)  # Give page time to load
        except Exception as e:
            raise Exception(f"Failed to navigate to job search page: {str(e)}")

    def _navigate_to_job(self, job_id: str):
        """Navigate to the specific job application page."""
        try:
            url = f"{self.base_url}/individuals/jobs/apply/{job_id}"
            self.chrome_driver.navigate_to(url)
            time.sleep(2)  # Give page time to load
        except Exception as e:
            raise Exception(f"Failed to navigate to job {job_id}: {str(e)}")

    def _click_next_step(self) -> bool:
        """Click the 'Next step' button on the application form."""
        try:
            next_button = WebDriverWait(self.chrome_driver.driver, 5).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".mint-button.primary.mobileBlock")
                )
            )
            next_button.click()
            time.sleep(1)  # Short wait for page transition
            return True
        except TimeoutException:
            logging.warning("Could not find the 'Next step' button")
            return False
        except Exception as e:
            logging.error(f"Error clicking next step button: {str(e)}")
            return False

    def _complete_application_steps(self) -> bool:
        """Complete all steps in the application process by clicking 'Next step' buttons."""
        try:
            # There are typically 4 steps in the application
            for step in range(4):
                logging.info(f"Processing application step {step+1}")
                if not self._click_next_step():
                    logging.warning(f"Failed on step {step+1}, but will continue")
                time.sleep(1)  # Wait between steps

            return True
        except Exception as e:
            logging.error(f"Error completing application steps: {str(e)}")
            return False

    def _check_application_success(self) -> bool:
        """Check if the application was successful."""
        try:
            # Check if we're on the success page
            return "success" in self.chrome_driver.current_url
        except Exception as e:
            logging.error(f"Error checking application success: {str(e)}")
            return False

    def apply_to_job(
        self, job_id: str, job_title: str = "", company_name: str = ""
    ) -> str:
        """Apply to a specific job on Workforce Australia"""
        try:
            # Initialize chrome driver if not already initialized
            self.chrome_driver.initialize()

            # Make sure we're logged in
            if not self.chrome_driver.is_logged_in:
                self._login_centrelink()

            # Navigate to the job application page
            self._navigate_to_job(job_id)

            # Complete all the application steps
            if self._complete_application_steps():
                # Check if application was successful
                if self._check_application_success():
                    logging.info(f"Successfully applied to job {job_id}")
                    return "APPLIED"
                else:
                    logging.warning(
                        f"Application process completed but success not confirmed for job {job_id}"
                    )
                    return "UNCERTAIN"
            else:
                logging.warning(
                    f"Failed to complete application steps for job {job_id}"
                )
                return "APP_ERROR"

        except Exception as e:
            logging.error(f"Exception during application for job {job_id}: {str(e)}")
            # Check if we somehow ended up on the success page despite errors
            if (
                self.chrome_driver.driver
                and "success" in self.chrome_driver.current_url
            ):
                logging.info(f"Application successful despite errors for job {job_id}")
                return "APPLIED"
            return "APP_ERROR"

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        self.chrome_driver.cleanup()
