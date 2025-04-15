"""
Centrelink Job Application Pipeline

This pipeline handles the automation of applying to jobs on the Workforce Australia website.

Steps:
1. Wait for login to Workforce Australia website
2. Go to job search page
3. For each job:
   a. Navigate to the job page
   b. Click through the application steps
   c. Verify successful application
4. Move to the next job
"""

import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any

# Add the parent directory to the Python path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from dotenv import load_dotenv
from tasks.job_application.centrelink import CentrelinkApplier
from blocks.airtable_service import AirtableManager
from utils.config import load_config
from utils.logging import setup_logger


class CentrelinkJobApplicationPipeline:
    def __init__(self):
        # Initialize logger
        self.logger = setup_logger()

        # Load environment variables and config
        load_dotenv()
        self.config = load_config()

        # Initialize services
        self.airtable = AirtableManager()
        self.applier = CentrelinkApplier()

        # Pipeline context for sharing data between tasks
        self.context: Dict[str, Any] = {}

    def get_pending_jobs(self) -> List[Dict]:
        """Get jobs that are ready to be applied to"""
        try:
            self.logger.info("Fetching pending Centrelink jobs from Airtable")
            pending_jobs = self.airtable.get_pending_jobs(source="centrelink")
            self.logger.info(f"Found {len(pending_jobs)} pending Centrelink jobs")
            self.context["pending_jobs"] = pending_jobs
            return pending_jobs
        except Exception as e:
            self.logger.error(f"Error fetching pending Centrelink jobs: {str(e)}")
            return []

    def process_jobs(self) -> List[Dict]:
        """Process each pending job"""
        pending_jobs = self.context.get("pending_jobs", [])
        if not pending_jobs:
            self.logger.info("No pending Centrelink jobs to process")
            return []

        processed_jobs = []
        for job in pending_jobs:
            try:
                if job["source"].lower() != "centrelink":
                    self.logger.info(f"Skipping non-Centrelink job: {job['title']}")
                    continue

                self.logger.info(
                    f"Processing Centrelink job application: {job['title']} (ID: {job['job_id']})"
                )
                # Apply to the job using the Centrelink applier
                result = self.applier.apply_to_job(
                    job_id=job["job_id"],
                    job_title=job.get("title", ""),
                    company_name=job.get("company", ""),
                )
                job["application_status"] = result
                processed_jobs.append(job)
                self.logger.info(f"Application result for {job['title']}: {result}")
            except Exception as e:
                self.logger.error(f"Error applying to job {job['title']}: {str(e)}")
                job["application_status"] = "ERROR"
                job["error_message"] = str(e)
                processed_jobs.append(job)

        self.context["processed_jobs"] = processed_jobs
        return processed_jobs

    def update_job_statuses(self) -> bool:
        """Update job statuses in Airtable"""
        processed_jobs = self.context.get("processed_jobs", [])
        if processed_jobs:
            self.logger.info(
                f"Updating status for {len(processed_jobs)} Centrelink jobs in Airtable"
            )
            self.airtable.update_job_statuses(processed_jobs)
            return True
        return False

    def print_results(self):
        """Print summary of job application results"""
        processed_jobs = self.context.get("processed_jobs", [])
        if not processed_jobs:
            self.logger.info("No Centrelink jobs were processed")
            return

        self.logger.info("\n=== Centrelink Job Application Summary ===")

        status_counts = {
            "APPLIED": 0,
            "UNCERTAIN": 0,
            "APP_ERROR": 0,
            "ERROR": 0,
        }

        for job in processed_jobs:
            status = job.get("application_status", "ERROR")
            status_counts[status] = status_counts.get(status, 0) + 1

            self.logger.info(
                f"\nJob: {job.get('title', 'No Title')} at {job.get('company', 'Unknown Company')}"
                f"\nStatus: {status}"
                f"\nID: {job['job_id']}"
            )

            if status in ["ERROR", "APP_ERROR"] and "error_message" in job:
                self.logger.error(f"Error details: {job['error_message']}")

        self.logger.info("\nSummary:")
        for status, count in status_counts.items():
            self.logger.info(f"{status}: {count}")

    def run(self) -> Dict[str, Any]:
        """Execute the complete Centrelink job application pipeline"""
        start_time = datetime.now()
        self.logger.info("Starting Centrelink job application pipeline")

        try:
            # Reset context
            self.context = {}

            # Execute pipeline stages
            pending_jobs = self.get_pending_jobs()
            if not pending_jobs:
                return {
                    "status": "completed",
                    "jobs_processed": 0,
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }

            processed_jobs = self.process_jobs()
            if processed_jobs:
                self.update_job_statuses()

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
        results = pipeline.run()

        # Print final summary
        if results["status"] == "success":
            print("\nPipeline Summary:")
            print(f"Jobs Processed: {results['jobs_processed']}")
            print(f"Duration: {results['duration_seconds']:.2f} seconds")
        else:
            print(f"\nPipeline failed: {results.get('error', 'Unknown error')}")

    except Exception as e:
        print(f"Critical error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
