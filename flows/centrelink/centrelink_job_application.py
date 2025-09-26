"""
Centrelink Job Application Pipeline

This pipeline handles the automation of applying to jobs on the Workforce
Australia website.

Steps:
1. Wait for login to Workforce Australia website
2. Go to job search page and scrape job listings
3. For each job:
   a. Navigate to the job page
   b. Click through the application steps
   c. Verify successful application
4. Move to the next job
"""

import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List

# Add the parent directory to the Python path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from dotenv import load_dotenv

from core.config import load_config
from core.logging import setup_logger
from tasks.job_application.centrelink import CentrelinkApplier


class CentrelinkJobApplicationPipeline:
    def __init__(self):
        # Initialize logger
        self.logger = setup_logger()

        # Load environment variables and config
        load_dotenv()
        self.config = load_config()

        # Initialize services
        self.applier = CentrelinkApplier()

        # Pipeline context for sharing data between tasks
        self.context: Dict[str, Any] = {}

        # Default search terms
        self.search_terms = [
            "engineer",
            "developer",
            "programmer",
            "data scientist",
        ]

        # Maximum jobs to process
        self.max_jobs = 100

    def get_jobs_from_website(self) -> List[Dict]:
        """Get jobs directly from Workforce Australia website"""
        assert hasattr(self, "logger"), "Logger must be initialized"
        assert hasattr(self, "applier"), "Applier must be initialized"

        try:
            self.logger.info("Fetching jobs from Workforce Australia website")

            # Try each search term or a generic empty search to get whatever
            # jobs are available
            search_terms = self.search_terms if self.search_terms else [""]
            jobs = []  # Declare at smallest scope needed

            for search_term in search_terms:
                self.logger.info(f"Searching for jobs with term: '{search_term}'")
                # Get a batch of jobs for each search term, adjust limit to
                # avoid getting too many
                term_limit = max(100, self.max_jobs // len(search_terms))
                term_jobs = self.applier.get_jobs_from_search_page(
                    search_text=search_term, limit=term_limit
                )
                self.logger.info(
                    f"Found {len(term_jobs)} jobs for search term " f"'{search_term}'"
                )
                jobs.extend(term_jobs)

                # If we already have enough jobs, break early
                if len(jobs) >= self.max_jobs:
                    break

            # Deduplicate jobs by job_id (declare at point of use)
            unique_jobs = {job["job_id"]: job for job in jobs if job.get("job_id")}
            deduplicated_jobs = list(unique_jobs.values())

            # Cap at max_jobs
            final_jobs = deduplicated_jobs[: self.max_jobs]

            self.logger.info(f"Found {len(final_jobs)} unique jobs to process")
            self.context["pending_jobs"] = final_jobs
            return final_jobs
        except Exception as e:
            self.logger.error(f"Error fetching jobs from website: {str(e)}")
            return []

    def process_jobs(self) -> List[Dict]:
        """Process each job"""
        pending_jobs = self.context.get("pending_jobs", [])
        if not pending_jobs:
            self.logger.info("No jobs to process")
            return []

        processed_jobs = []
        for i, job in enumerate(pending_jobs):
            try:
                self.logger.info(
                    f"Processing job {i+1}/{len(pending_jobs)}: "
                    f"{job.get('title', 'Unknown Title')} (ID: {job['job_id']})"
                )
                # Try to apply to the job with error handling
                try:
                    # Apply to the job using the Centrelink applier
                    result = self.applier.apply_to_job(
                        job_id=job["job_id"],
                        job_title=job.get("title", ""),
                        company_name=job.get("company", ""),
                    )
                except Exception as apply_error:
                    self.logger.error(f"Error in apply_to_job: {str(apply_error)}")
                    result = "APP_ERROR"

                job["application_status"] = result
                processed_jobs.append(job)
                self.logger.info(
                    f"Application result for "
                    f"{job.get('title', 'Unknown job')}: {result}"
                )

                # Add a small delay between job applications
                time.sleep(2)
            except Exception as e:
                self.logger.error(
                    f"Error processing job {job.get('title', 'Unknown')}: {str(e)}"
                )
                job["application_status"] = "ERROR"
                job["error_message"] = str(e)
                processed_jobs.append(job)

        self.context["processed_jobs"] = processed_jobs
        return processed_jobs

    def print_results(self):
        """Print summary of job application results"""
        processed_jobs = self.context.get("processed_jobs", [])
        if not processed_jobs:
            self.logger.info("No Centrelink jobs were processed")
            return

        self.logger.info("\n=== Centrelink Job Application Summary ===")

        status_counts = {
            "APPLIED": 0,
            "ALREADY_APPLIED": 0,
            "UNCERTAIN": 0,
            "APP_ERROR": 0,
            "ERROR": 0,
        }

        for job in processed_jobs:
            status = job.get("application_status", "ERROR")
            status_counts[status] = status_counts.get(status, 0) + 1

            self.logger.info(
                f"\nJob: {job.get('title', 'No Title')} at "
                f"{job.get('company', 'Unknown Company')}"
                f"\nStatus: {status}"
                f"\nID: {job['job_id']}"
            )

            if status in ["ERROR", "APP_ERROR"] and "error_message" in job:
                self.logger.error(f"Error details: {job['error_message']}")

        self.logger.info("\nSummary:")
        for status, count in status_counts.items():
            if count > 0:  # Only show statuses that occurred
                self.logger.info(f"{status}: {count}")

    def run(self, save_to_airtable: bool = False) -> Dict[str, Any]:
        """
        Execute the complete Centrelink job application pipeline

        Parameters:
        - save_to_airtable: Whether to save job results to Airtable
        """
        start_time = datetime.now()
        self.logger.info("Starting Centrelink job application pipeline")

        try:
            # Reset context
            self.context = {}

            # Ensure we're logged in before starting
            self.logger.info("Ensuring login to Workforce Australia...")
            self.applier.chrome_driver.initialize()
            if not self.applier.chrome_driver.is_logged_in:
                self.applier._login_centrelink()
            self.logger.info("Login successful, proceeding with job search...")

            # Execute pipeline stages
            pending_jobs = self.get_jobs_from_website()
            if not pending_jobs:
                return {
                    "status": "completed",
                    "jobs_processed": 0,
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }

            processed_jobs = self.process_jobs()
            if processed_jobs:
                self.update_job_statuses(save_to_airtable)

            self.print_results()

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            return {
                "status": "success",
                "jobs_processed": len(processed_jobs),
                "duration_seconds": duration,
            }

        except Exception as e:
            self.logger.exception(f"Pipeline failed: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "duration_seconds": (datetime.now() - start_time).total_seconds(),
            }
        finally:
            # Clean up the applier
            self.applier.cleanup()


def main():
    try:
        pipeline = CentrelinkJobApplicationPipeline()

        # Parse command line arguments
        import argparse

        parser = argparse.ArgumentParser(
            description="Run Centrelink job application pipeline"
        )
        parser.add_argument(
            "--save-to-airtable",
            action="store_true",
            help="Save job results to Airtable",
        )
        parser.add_argument(
            "--max-jobs", type=int, default=10, help="Maximum number of jobs to process"
        )
        parser.add_argument(
            "--search",
            type=str,
            nargs="*",
            help="Search terms to use (space separated)",
        )
        args = parser.parse_args()

        # Update pipeline settings if provided
        if args.max_jobs:
            pipeline.max_jobs = args.max_jobs

        if args.search:
            pipeline.search_terms = args.search

        # Run pipeline
        results = pipeline.run(save_to_airtable=args.save_to_airtable)

        # Print final summary
        if results["status"] == "success":
            print("\nPipeline Summary:")
            print(f"Jobs Processed: {results['jobs_processed']}")
            print(f"Duration: {results['duration_seconds']: .2f} seconds")
        else:
            print(f"\nPipeline failed: {results.get('error', 'Unknown error')}")

    except Exception as e:
        print(f"Critical error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
