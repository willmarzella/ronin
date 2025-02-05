"""Service for applying to jobs."""

import logging
import time
from typing import List, Dict, Any

from integrations.airtable import AirtableManager
from app.appliers.seek import SeekApplier


class JobApplierService:
    """Service for applying to jobs."""

    def __init__(self):
        """Initialize the job applier service."""
        self.airtable = AirtableManager()
        self.seek_applier = SeekApplier()

    def _get_pending_jobs(self) -> List[Dict[str, Any]]:
        """Get jobs from Airtable that are ready to apply to"""
        try:
            # Get all records where Status is 'Ready to Apply' and Quick Apply is True
            formula = (
                "AND(OR({Status} = 'APPLYING', {Status} = 'APPLICATION_FAILED'), "
                "{Quick Apply} = TRUE(), {TESTING} = FALSE())"
            )
            records = self.airtable.table.all(formula=formula)

            jobs = []
            if records:
                for record in records:
                    fields = record["fields"]
                    # Extract job ID from the URL
                    url = fields.get("URL", "")
                    if not url:
                        logging.warning(
                            f"Job record {record['id']} has no URL, skipping"
                        )
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
            logging.error(f"Error getting pending jobs: {str(e)}")
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
        """Process all pending job applications."""
        try:
            # Get jobs that are ready to apply to
            jobs = self._get_pending_jobs()
            if not jobs:
                logging.info("No jobs to process")
                return

            logging.info(f"Found {len(jobs)} jobs to process")

            # Process each job
            for job in jobs:
                try:
                    logging.info(f"Processing job: {job['title']}")

                    # Apply to the job
                    success = self.seek_applier.apply_to_job(
                        job["id"], job["description"], job["tech_stack"]
                    )

                    # Update status in Airtable
                    if success:
                        self.airtable.update_record(
                            job["record_id"], {"Status": "APPLIED"}
                        )
                        logging.info(f"Successfully applied to job: {job['title']}")
                    else:
                        self.airtable.update_record(
                            job["record_id"], {"Status": "APPLICATION_FAILED"}
                        )
                        logging.error(f"Failed to apply to job: {job['title']}")

                except Exception as e:
                    logging.error(f"Error processing job {job['title']}: {str(e)}")
                    self.airtable.update_record(
                        job["record_id"], {"Status": "APPLICATION_FAILED"}
                    )
                    continue

        except Exception as e:
            logging.error(f"Error in process_pending_jobs: {str(e)}")
            raise

        finally:
            # Always cleanup the browser
            self.seek_applier.cleanup()

        logging.info("Finished processing all pending jobs")
