"""
LinkedIn Outreach DAG for contacting potential hiring managers and recruiters.

This DAG:
1. Retrieves job listings from Airtable
2. For each job:
   - Logs into LinkedIn
   - Navigates to the company's LinkedIn page
   - Searches for people with titles like "talent", "recruiter", or "engineering"
   - Sends a connection request with note or direct message
   - Uses OpenAI to generate personalized messages
"""

import json
import os
import sys
import time
import random
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from services.airtable_service import AirtableManager
from services.ai_service import AIService
from tasks.job_outreach import (
    LinkedInLoginHandler,
    LinkedInSearcher,
    LinkedInCompanyHandler,
    LinkedInPeopleHandler,
    LinkedInMessageGenerator,
    OutreachTracker,
)
from core.config import load_config
from core.logging import setup_logger


class LinkedInOutreachPipeline:
    """Pipeline for LinkedIn outreach to potential hiring contacts."""

    def __init__(self):
        """Initialize the LinkedIn outreach pipeline."""
        # Initialize logger
        self.logger = setup_logger()

        # Load environment variables and config
        load_dotenv()
        self.config = load_config()

        # Initialize services and utilities
        self.airtable = AirtableManager()
        self.ai_service = AIService()
        self.message_generator = LinkedInMessageGenerator()
        self.outreach_tracker = OutreachTracker()

        # Track visited companies to avoid duplicates
        self.visited_companies = set()

        # Configure Chrome
        self.driver = None
        self.login_handler = None

        # Pipeline context for sharing data between tasks
        self.context: Dict[str, Any] = {}

    def _setup_webdriver(self) -> bool:
        """Set up and configure the Selenium WebDriver."""
        try:
            self.logger.info("Setting up Chrome WebDriver")

            from selenium.webdriver.chrome.service import Service
            import os

            chrome_options = Options()

            # First check if CHROME_BINARY_PATH environment variable is set
            chrome_env_path = os.environ.get("CHROME_BINARY_PATH")
            if chrome_env_path and os.path.exists(chrome_env_path):
                chrome_options.binary_location = chrome_env_path
                self.logger.info(
                    f"Using Chrome at path from environment variable: {chrome_env_path}"
                )
            else:
                # Try multiple common Chrome locations on macOS
                chrome_locations = [
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # Standard location
                    os.path.expanduser(
                        "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                    ),  # User's Applications folder
                    "/Applications/Chromium.app/Contents/MacOS/Chromium",  # Chromium alternative
                    os.path.expanduser(
                        "~/Applications/Chromium.app/Contents/MacOS/Chromium"
                    ),  # User's Chromium
                ]

                chrome_found = False
                for location in chrome_locations:
                    if os.path.exists(location):
                        chrome_options.binary_location = location
                        chrome_found = True
                        self.logger.info(f"Found Chrome at: {location}")
                        break

                if not chrome_found:
                    self.logger.warning(
                        "Chrome binary not found in common locations. Proceeding without setting binary location."
                    )
                    self.logger.warning(
                        "Consider setting CHROME_BINARY_PATH in your .env file to specify the Chrome location."
                    )

            # Minimal essential options
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--disable-extensions")

            # Exclude automation flags to avoid detection
            chrome_options.add_experimental_option(
                "excludeSwitches", ["enable-automation"]
            )
            chrome_options.add_experimental_option("useAutomationExtension", False)

            # If headless mode is needed (not recommended for LinkedIn)
            # chrome_options.add_argument("--headless")

            # Attempt initialization with retries
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                try:
                    self.driver = webdriver.Chrome(options=chrome_options)

                    # Set implicit wait time
                    self.driver.implicitly_wait(10)

                    # Initialize the login handler
                    self.login_handler = LinkedInLoginHandler(self.driver)

                    self.logger.info("Chrome WebDriver initialized successfully")
                    return True
                except Exception as e:
                    retry_count += 1
                    self.logger.warning(
                        f"Attempt {retry_count}/{max_retries} to initialize Chrome WebDriver failed: {str(e)}"
                    )

                    # Wait a bit before retrying
                    time.sleep(2)

                    if retry_count >= max_retries:
                        self.logger.error(
                            f"Failed to initialize Chrome WebDriver after {max_retries} attempts"
                        )
                        return False

        except Exception as e:
            self.logger.error(f"Error in WebDriver setup: {str(e)}")
            return False

    def get_pending_jobs(self) -> List[Dict]:
        """Get jobs from Airtable that need outreach."""
        try:
            self.logger.info("Fetching pending jobs from Airtable")

            # Get jobs where outreach has not been done yet
            # This uses a custom outreach status if it exists, or creates one if needed
            jobs = self.airtable.get_jobs_by_source("seek")

            # Filter jobs where outreach is pending or not done
            pending_jobs = jobs

            # [
            #     job
            #     for job in jobs
            #     if job.get("outreach_status") not in ["COMPLETED", "IN_PROGRESS"]
            # ]

            self.logger.info(f"Found {len(pending_jobs)} jobs needing outreach")
            self.context["pending_jobs"] = pending_jobs
            return pending_jobs
        except Exception as e:
            self.logger.error(f"Error fetching pending jobs: {str(e)}")
            return []

    def process_jobs(self) -> List[Dict]:
        """Process each job for outreach."""
        pending_jobs = self.context.get("pending_jobs", [])
        if not pending_jobs:
            self.logger.info("No pending jobs to process")
            return []

        # Setup WebDriver and login to LinkedIn
        if not self._setup_webdriver():
            self.logger.error("Failed to set up WebDriver, aborting job processing")
            return []

        if not self.login_handler.login():
            self.logger.error("Failed to log in to LinkedIn, aborting job processing")
            self.driver.quit()
            return []

        # Initialize LinkedIn handler classes
        searcher = LinkedInSearcher(self.driver)
        company_handler = LinkedInCompanyHandler(self.driver)
        people_handler = LinkedInPeopleHandler(self.driver)

        processed_jobs = []

        try:
            # Process each job
            for job in pending_jobs:
                print(f"Job: {job}")
                try:
                    job_id = job.get("Job ID", "unknown")
                    company_name = job.get("Company", "")
                    job_title = job.get("Title", "")

                    if not company_name:
                        self.logger.warning(
                            f"Missing company name for job {job_id}, skipping"
                        )
                        continue

                    # Skip company if already visited to avoid duplicates
                    if company_name in self.visited_companies:
                        self.logger.info(
                            f"Already processed company {company_name}, skipping"
                        )
                        continue

                    self.logger.info(
                        f"Processing outreach for {company_name}, job: {job_title}"
                    )

                    # Update job status to IN_PROGRESS
                    # job["outreach_status"] = "IN_PROGRESS"
                    # job["outreach_timestamp"] = datetime.now().isoformat()
                    # self.airtable.update_record(
                    #     job["id"], {"outreach_status": "IN_PROGRESS"}
                    # )

                    # Navigate to company page
                    if searcher.go_to_company_page(company_name):
                        # Extract company info
                        company_info = company_handler.extract_company_info()

                        # Search for people with relevant titles
                        search_titles = [
                            "talent",
                            "recruiter",
                            "recruiting",
                            "hr",
                            "hiring",
                            "engineering manager",
                        ]
                        people = searcher.search_people_at_company(
                            company_name, search_titles, max_results=5
                        )

                        if people:
                            job["outreach_people_found"] = len(people)

                            # For each person, visit profile and attempt contact
                            for person in people:
                                # Add some waiting time between profile visits
                                time.sleep(random.uniform(10, 15))

                                profile_url = person.get("profile_url", "")
                                if not profile_url:
                                    continue

                                # Skip if this profile was already contacted
                                if self.outreach_tracker.was_contacted(profile_url):
                                    self.logger.info(
                                        f"Already contacted {person.get('name')}, skipping"
                                    )
                                    continue

                                # Visit profile
                                if people_handler.visit_profile(profile_url):
                                    # Record the profile visit
                                    self.outreach_tracker.record_profile_visit(
                                        profile_url
                                    )

                                    # Extract profile details
                                    profile_info = people_handler.extract_profile_info()

                                    person_name = profile_info.get(
                                        "name"
                                    ) or person.get("name", "")
                                    person_title = profile_info.get(
                                        "title"
                                    ) or person.get("title", "")

                                    # Check if we can message directly
                                    if people_handler.can_message_directly():
                                        # Generate direct message
                                        success, message = (
                                            self.message_generator.generate_direct_message(
                                                person_name=person_name,
                                                person_title=person_title,
                                                company_name=company_name,
                                                job_title=job_title,
                                            )
                                        )

                                        if success and message:
                                            # Send direct message
                                            dm_sent = (
                                                people_handler.send_direct_message(
                                                    message
                                                )
                                            )
                                            # Record the direct message attempt
                                            self.outreach_tracker.record_direct_message(
                                                profile_url, person_name, dm_sent
                                            )
                                    else:
                                        # Generate connection request note
                                        success, note = (
                                            self.message_generator.generate_connection_request(
                                                person_name=person_name,
                                                person_title=person_title,
                                                company_name=company_name,
                                                job_title=job_title,
                                            )
                                        )

                                        if success and note:
                                            # Send connection request with note
                                            conn_sent = (
                                                people_handler.send_connection_request(
                                                    note
                                                )
                                            )
                                            # Record the connection request attempt
                                            self.outreach_tracker.record_connection_request(
                                                profile_url, person_name, conn_sent
                                            )

                                # Add some random delay between profiles
                                time.sleep(random.uniform(20, 30))

                            # Mark company as visited
                            self.visited_companies.add(company_name)

                            # Update job with outreach stats
                            stats = self.outreach_tracker.get_stats()
                            job["outreach_stats"] = stats
                            job["outreach_status"] = "COMPLETED"
                        else:
                            self.logger.warning(
                                f"No suitable contacts found at {company_name}"
                            )
                            job["outreach_status"] = "NO_CONTACTS"
                    else:
                        self.logger.warning(
                            f"Failed to navigate to company page for {company_name}"
                        )
                        job["outreach_status"] = "COMPANY_NOT_FOUND"

                    processed_jobs.append(job)

                except Exception as e:
                    self.logger.error(
                        f"Error processing job {job.get('job_id')}: {str(e)}"
                    )
                    job["outreach_status"] = "ERROR"
                    job["error_message"] = str(e)
                    processed_jobs.append(job)

                # Add a delay between jobs to avoid rate limiting
                time.sleep(random.uniform(30, 45))

        finally:
            # Always close the WebDriver when done
            if self.driver:
                # Try to log out first
                if self.login_handler:
                    try:
                        self.login_handler.logout()
                    except:
                        self.logger.warning("Failed to log out from LinkedIn")

                self.driver.quit()
                self.driver = None

        self.context["processed_jobs"] = processed_jobs
        return processed_jobs

    def update_job_statuses(self) -> bool:
        """Update job statuses in Airtable."""
        processed_jobs = self.context.get("processed_jobs", [])
        if processed_jobs:
            self.logger.info(
                f"Updating status for {len(processed_jobs)} jobs in Airtable"
            )

            for job in processed_jobs:
                update_fields = {
                    "outreach_status": job.get("outreach_status", "UNKNOWN"),
                    "outreach_timestamp": job.get(
                        "outreach_timestamp", datetime.now().isoformat()
                    ),
                }

                # Add stats if available
                if "outreach_stats" in job:
                    update_fields["outreach_stats"] = json.dumps(job["outreach_stats"])

                # Add error message if available
                if "error_message" in job:
                    update_fields["error_message"] = job["error_message"]

                self.airtable.update_record(job["id"], update_fields)

            return True
        return False

    def print_results(self):
        """Print summary of outreach results."""
        processed_jobs = self.context.get("processed_jobs", [])
        if not processed_jobs:
            self.logger.info("No jobs were processed for outreach")
            return

        self.logger.info("=== LinkedIn Outreach Summary ===")
        self.logger.info(f"Total jobs processed: {len(processed_jobs)}")

        # Count jobs by status
        status_counts = {}
        for job in processed_jobs:
            status = job.get("outreach_status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1

        for status, count in status_counts.items():
            self.logger.info(f"  {status}: {count} jobs")

        # Print outreach stats if available
        if hasattr(self, "outreach_tracker"):
            stats = self.outreach_tracker.get_stats()
            self.logger.info("Outreach statistics:")
            self.logger.info(f"  Profiles visited: {stats['total_profiles_visited']}")
            self.logger.info(
                f"  Connection requests sent: {stats['connection_requests_sent']}"
            )
            self.logger.info(f"  Direct messages sent: {stats['direct_messages_sent']}")
            self.logger.info(f"  Failed attempts: {stats['failed_attempts']}")

    def run(self) -> Dict[str, Any]:
        """Run the complete LinkedIn outreach pipeline."""
        start_time = datetime.now()
        self.logger.info(f"Starting LinkedIn outreach pipeline at {start_time}")

        results = {
            "success": False,
            "start_time": start_time.isoformat(),
            "end_time": None,
            "jobs_processed": 0,
            "error": None,
        }

        try:
            # Get pending jobs
            pending_jobs = self.get_pending_jobs()
            if not pending_jobs:
                self.logger.info("No pending jobs to process, exiting")
                results["success"] = True
                results["message"] = "No pending jobs to process"
                return results

            # Process jobs
            processed_jobs = self.process_jobs()
            results["jobs_processed"] = len(processed_jobs)

            # Update job statuses
            self.update_job_statuses()

            # Print results
            self.print_results()

            results["success"] = True

        except Exception as e:
            self.logger.error(f"Error in LinkedIn outreach pipeline: {str(e)}")
            results["error"] = str(e)
            results["success"] = False

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        results["end_time"] = end_time.isoformat()
        results["duration_seconds"] = duration

        self.logger.info(
            f"LinkedIn outreach pipeline completed in {duration:.2f} seconds"
        )

        return results


def main():
    """Run the LinkedIn outreach pipeline."""
    pipeline = LinkedInOutreachPipeline()
    results = pipeline.run()

    print(json.dumps(results, indent=2))

    return 0 if results["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
