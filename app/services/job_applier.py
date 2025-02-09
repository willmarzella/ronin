"""Service for applying to jobs."""

import logging
from typing import List, Dict, Any
from urllib.parse import urlparse

from integrations.airtable import AirtableManager
from app.appliers.factory import JobApplierFactory


class JobApplierService:
    """Service for applying to jobs."""

    def __init__(self):
        """Initialize the job applier service."""
        self.airtable = AirtableManager()

    def _get_job_board_from_url(self, url: str) -> str:
        """Extract job board name from URL."""
        domain = urlparse(url).netloc.lower()

        # Map domains to job board names
        domain_mapping = {
            "seek.com.au": "seek",
            "boards.greenhouse.io": "greenhouse",
            "jobs.lever.co": "lever",
            # Add more mappings as needed
        }

        for domain_part, board in domain_mapping.items():
            if domain_part in domain:
                return board

        return "unknown"

    def _get_job_id_from_url(self, url: str, job_board: str) -> str:
        """Extract job ID from URL based on job board."""
        try:
            if job_board == "seek":
                return url.split("/")[-1]
            elif job_board == "greenhouse":
                # Example: https://boards.greenhouse.io/company/jobs/123456
                return url.split("/")[-1]
            elif job_board == "lever":
                # Example: https://jobs.lever.co/company/123456
                return url.split("/")[-1]
            else:
                return url  # Return full URL if unknown format
        except Exception as e:
            logging.error(f"Failed to parse job URL {url}: {str(e)}")
            return url

    def _get_pending_jobs(self) -> List[Dict[str, Any]]:
        """Get jobs from Airtable that are ready to apply to."""
        try:
            # Get all records where Status is 'Ready to Apply' and Quick Apply is True
            formula = (
                "AND(OR({Status} = 'DISCOVERED', {Status} = 'APPLICATION_FAILED'), "
                "{Quick Apply} = TRUE(), {TESTING} = FALSE())"
            )
            records = self.airtable.table.all(formula=formula)

            jobs = []
            if records:
                for record in records:
                    fields = record["fields"]
                    url = fields.get("URL", "")
                    if not url:
                        logging.warning(
                            f"Job record {record['id']} has no URL, skipping"
                        )
                        continue

                    try:
                        # Get source from Airtable record or determine from URL
                        source = fields.get("Source", "unknown")
                        if source == "unknown":
                            source = self.airtable._get_job_source(url)

                        # Get job ID based on source
                        job_id = self.airtable._get_job_id_from_url(url, source)
                        if not job_id:
                            logging.warning(
                                f"Could not extract job ID from URL {url}, skipping"
                            )
                            continue

                        jobs.append(
                            {
                                "id": job_id,
                                "description": fields.get("Description", ""),
                                "title": fields.get("Title", ""),
                                "tech_stack": fields.get("Tech Stack", ""),
                                "record_id": record["id"],
                                "source": source,
                                "url": url,
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

    def process_pending_jobs(self):
        """Process all pending job applications."""
        try:
            # Get jobs that are ready to apply to
            jobs = self._get_pending_jobs()
            if not jobs:
                logging.info("No jobs to process")
                return

            logging.info(f"Found {len(jobs)} jobs to process")

            # Group jobs by source to minimize browser sessions
            jobs_by_source = {}
            for job in jobs:
                jobs_by_source.setdefault(job["source"], []).append(job)

            # Process each source's jobs
            for source, source_jobs in jobs_by_source.items():
                applier = None
                try:
                    applier = JobApplierFactory.create_applier(source)
                    if not applier:
                        logging.warning(f"No applier available for source: {source}")
                        continue

                    # Process each job for this source
                    for job in source_jobs:
                        try:
                            logging.info(f"Processing job: {job['title']}")

                            # Apply to the job
                            result = applier.apply_to_job(
                                job["id"], job["description"], job["tech_stack"]
                            )

                            # Update status in Airtable based on result
                            if result == "NEEDS_MANUAL_APPLICATION":
                                self.airtable.update_record(
                                    job["record_id"],
                                    {
                                        "Status": "NEEDS_MANUAL_APPLICATION",
                                        "APP_ERROR": "Job requires manual application due to role requirements",
                                    },
                                )
                                logging.info(
                                    f"Job marked for manual application: {job['title']}"
                                )
                            elif result == "SUCCESS":
                                self.airtable.update_record(
                                    job["record_id"], {"Status": "APPLIED"}
                                )
                                logging.info(
                                    f"Successfully applied to job: {job['title']}"
                                )
                            else:  # FAILED
                                self.airtable.update_record(
                                    job["record_id"], {"Status": "APPLICATION_FAILED"}
                                )
                                logging.error(f"Failed to apply to job: {job['title']}")

                        except Exception as e:
                            logging.error(
                                f"Error processing job {job['title']}: {str(e)}"
                            )
                            self.airtable.update_record(
                                job["record_id"], {"Status": "APPLICATION_FAILED"}
                            )
                            continue

                finally:
                    # Clean up the applier for this source
                    if applier:
                        applier.cleanup()

        except Exception as e:
            logging.error(f"Error in process_pending_jobs: {str(e)}")
            raise

        logging.info("Finished processing all pending jobs")
