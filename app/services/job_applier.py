import logging
import time
from typing import List, Dict, Any

from integrations.airtable import AirtableManager
from app.appliers.seek import SeekApplier


class JobApplierService:
    def __init__(self):
        self.airtable = AirtableManager()
        self.seek_applier = SeekApplier()

    def _get_pending_jobs(self) -> List[Dict[str, Any]]:
        """Get jobs from Airtable that are ready to apply to"""
        try:
            # Get all records where Status is 'Ready to Apply' and Quick Apply is True
            formula = "AND(OR({Status} = 'APPLYING', {Status} = 'APPLICATION_FAILED'), {Quick Apply} = TRUE(), {TESTING} = FALSE())"
            records = self.airtable.table.all(formula=formula)

            jobs = []
            if records:
                for record in records:
                    fields = record["fields"]
                    # Extract job ID from the URL
                    url = fields.get("URL", "")
                    if not url:
                        logging.warning(f"Job record {record['id']} has no URL, skipping")
                        continue

                    try:
                        # URL format: https://www.seek.com.au/job/{job_id}
                        job_id = url.split("/")[-1]
                        jobs.append(
                            {
                                "id": job_id,
                                "description": fields.get("Description", ""),
                                "title": fields.get("Title", ""),
                                "tech_stack": fields.get("Tech Stack", ""),
                                "record_id": record["id"],
                            }
                        )
                    except Exception as e:
                        logging.error(f"Failed to parse job URL {url}: {str(e)}")
                        continue

                return jobs
            else:
                logging.info("No pending jobs found")
                return []
        except Exception as e:
            logging.error(f"Failed to fetch pending jobs from Airtable: {str(e)}")
            return []

    def _mark_job_status(self, record_id: str, status: str, error: str = None):
        """Update job status in Airtable"""
        try:
            fields = {"Status": status}
            if error:
                fields["APP_ERROR"] = error

            self.airtable.table.update(record_id, fields)
            logging.info(f"Updated job {record_id} status to {status}")
        except Exception as e:
            logging.error(f"Failed to update job status in Airtable: {str(e)}")

    def process_pending_jobs(self):
        """Main method to process all pending job applications"""
        logging.info("Starting to process pending jobs")
        jobs = self._get_pending_jobs()

        if not jobs:
            logging.info("No pending jobs found to process")
            return

        logging.info(f"Found {len(jobs)} jobs to process")

        try:
            for job in jobs:
                try:
                    logging.info(f"Processing job {job['id']}: {job['title']}")

                    # Mark job as in progress
                    self._mark_job_status(job["record_id"], "APPLYING")

                    # Attempt to apply
                    success = self.seek_applier.apply_to_job(
                        job_id=job["id"],
                        job_description=job["description"],
                        tech_stack=job["tech_stack"],
                    )

                    if success:
                        self._mark_job_status(job["record_id"], "APPLIED")
                    else:
                        self._mark_job_status(
                            job["record_id"],
                            "APPLICATION_FAILED",
                            "Failed to apply to job - see logs for details",
                        )

                except Exception as e:
                    error_msg = f"Error processing job {job['id']}: {str(e)}"
                    logging.error(error_msg)
                    self._mark_job_status(
                        job["record_id"], "APPLICATION_FAILED", error_msg
                    )

                # Small delay between applications to avoid overwhelming the system
                time.sleep(2)

        finally:
            # Clean up browser resources
            self.seek_applier.cleanup()

        logging.info("Finished processing all pending jobs")
