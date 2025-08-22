import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from tasks.job_application.appliers import SeekApplier
from services.airtable_service import AirtableManager
from core.config import load_config
from core.logging import setup_logger


class JobApplicationPipeline:
    def __init__(self):
        # Initialize logger
        self.logger = setup_logger()

        # Load environment variables and config
        load_dotenv()
        self.config = load_config()

        # Initialize services
        self.airtable = AirtableManager()
        self.applier = SeekApplier()

        # Pipeline context for sharing data between tasks
        self.context: Dict[str, Any] = {}

    def get_pending_jobs(self) -> List[Dict]:
        """Get jobs that are ready to be applied to"""
        try:
            self.logger.info("Fetching pending jobs from Airtable")
            pending_jobs = self.airtable.get_pending_jobs()
            self.logger.info(f"Found {len(pending_jobs)} pending jobs")
            self.context["pending_jobs"] = pending_jobs
            return pending_jobs
        except Exception as e:
            self.logger.error(f"Error fetching pending jobs: {str(e)}")
            return []

    def process_jobs(self) -> List[Dict]:
        """Process each pending job"""
        pending_jobs = self.context.get("pending_jobs", [])
        if not pending_jobs:
            self.logger.info("No pending jobs to process")
            return []

        processed_jobs = []
        for job in pending_jobs:
            try:
                if job["source"].lower() != "seek":
                    self.logger.info(f"Skipping non-Seek job: {job['title']}")
                    continue

                self.logger.info(
                    f"Processing job application: {job['title']} (ID: {job['job_id']})"
                )
                # Apply to the job using the Seek applier
                result = self.applier.apply_to_job(
                    job_id=job["job_id"],
                    job_description=job["description"],
                    score=job["score"],
                    tech_stack=job["tech_stack"],
                    company_name=job["company"],
                    title=job["title"],
                )
                job["application_status"] = result

                # Update job status in Airtable immediately after processing
                self._update_job_status_immediately(job)

                processed_jobs.append(job)
                self.logger.info(f"Application result for {job['title']}: {result}")
            except Exception as e:
                # Check if this is an OpenAI API error
                error_str = str(e)
                if "OpenAI API error" in error_str or "insufficient_quota" in error_str:
                    self.logger.error(f"OpenAI API error detected: {error_str}")
                    # Propagate the error to stop the entire workflow
                    raise Exception(
                        f"Stopping workflow due to OpenAI API error: {error_str}"
                    )

                self.logger.error(f"Error applying to job {job['title']}: {str(e)}")
                job["application_status"] = "ERROR"
                job["error_message"] = str(e)

                # Update job status in Airtable immediately after error
                self._update_job_status_immediately(job)

                processed_jobs.append(job)

        self.context["processed_jobs"] = processed_jobs
        return processed_jobs

    def _update_job_status_immediately(self, job: Dict) -> None:
        """Update a single job's status in Airtable immediately after processing."""
        try:
            record_id = job.get("record_id")
            status = job.get("application_status")

            if not record_id or not status:
                self.logger.warning(
                    f"Missing record_id or status for job: {job.get('title', 'Unknown')}"
                )
                return

            self.logger.info(
                f"Updating status for job {job.get('title', 'Unknown')} to {status}"
            )

            fields = {"Status": status}

            # Add error message if available
            if status == "ERROR" and "error_message" in job:
                fields["APP_ERROR"] = job["error_message"]

            self.airtable.update_record(record_id, fields)
            self.logger.info(
                f"Successfully updated status for job {job.get('title', 'Unknown')} to {status}"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to update status for job {job.get('title', 'Unknown')}: {str(e)}"
            )
            # Don't re-raise the exception - we don't want to stop the pipeline
            # just because of a status update failure

    def update_job_statuses(self) -> bool:
        """Update job statuses in Airtable (now handled immediately per job)"""
        processed_jobs = self.context.get("processed_jobs", [])
        if processed_jobs:
            self.logger.info(
                f"Job status updates already completed for {len(processed_jobs)} jobs "
                "(updated immediately after each application)"
            )
            return True
        return False

    def print_results(self):
        """Print summary of job application results"""
        processed_jobs = self.context.get("processed_jobs", [])
        if not processed_jobs:
            self.logger.info("No jobs were processed")
            return

        self.logger.info("\n=== Job Application Summary ===")

        status_counts = {
            "SUCCESS": 0,
            "FAILED": 0,
            "NEEDS_MANUAL_APPLICATION": 0,
            "ERROR": 0,
        }

        for job in processed_jobs:
            status = job.get("application_status", "ERROR")
            status_counts[status] = status_counts.get(status, 0) + 1

            self.logger.info(
                f"\nJob: {job['title']} at {job['company']}"
                f"\nStatus: {status}"
                f"\nID: {job['job_id']}"
            )

            if status == "ERROR" and "error_message" in job:
                self.logger.error(f"Error details: {job['error_message']}")

        self.logger.info("\nSummary:")
        for status, count in status_counts.items():
            self.logger.info(f"{status}: {count}")

    def run(self) -> Dict[str, Any]:
        """Execute the complete job application pipeline"""
        start_time = datetime.now()
        self.logger.info("Starting job application pipeline")

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
        pipeline = JobApplicationPipeline()
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
