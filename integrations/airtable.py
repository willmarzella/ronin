import json
import logging
import os

from pyairtable import Api, Base, Table


class AirtableManager:
    def __init__(self):
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        if not self.api_key:
            raise ValueError("AIRTABLE_API_KEY environment variable not set")

        self.base_id = "appho2dXd2ZlfresS"
        if not self.base_id:
            raise ValueError("AIRTABLE_BASE_ID environment variable not set")

        self.table_name = "Jobs"

        # Initialize table directly with API key
        self.table = Table(self.api_key, self.base_id, self.table_name)
        self.existing_job_ids = self._get_existing_job_ids()

    def _get_existing_job_ids(self):
        """Get set of existing job IDs from Airtable"""
        try:
            records = self.table.all()
            return {
                record["fields"].get("Job ID")
                for record in records
                if "Job ID" in record["fields"]
            }
        except Exception as e:
            logging.error(f"Error fetching existing job IDs: {str(e)}")
            return set()

    def insert_job(self, job_data):
        """Insert a job into Airtable if it doesn't exist"""
        job_id = job_data["job_id"]

        # Skip if job already exists
        if job_id in self.existing_job_ids:
            logging.info(f"Job {job_id} already exists in Airtable, skipping")
            return False

        try:
            # Get analysis data (already a dict from OpenAI)
            analysis_data = job_data["analysis"]

            # Format the data for Airtable
            airtable_data = {
                "Title": job_data["title"],
                "Company": job_data["company"],
                "Job ID": job_id,
                "Description": job_data["description"],
                "Score": analysis_data.get("score", 0),
                "Tech Stack": ", ".join(analysis_data.get("tech_stack", [])),
                "Recommendation": analysis_data.get("recommendation", ""),
                "URL": job_data.get("url", f"https://www.seek.com.au/job/{job_id}"),
                "Quick Apply": job_data.get("quick_apply", False),
                "Created At": job_data.get("created_at"),  # ISO format datetime string
                "Pay Rate": job_data.get("pay_rate", ""),
            }

            # Create record in Airtable
            self.table.create(airtable_data)
            self.existing_job_ids.add(job_id)  # Add to local cache
            logging.info(f"Successfully added job {job_id} to Airtable")
            return True

        except Exception as e:
            logging.error(f"Error adding job to Airtable: {str(e)}")
            raise

    def batch_insert_jobs(self, jobs_data):
        """Insert multiple jobs into Airtable, stopping if duplicate found"""
        new_jobs_count = 0
        duplicate_found = False

        for job in jobs_data:
            try:
                if self.insert_job(job):
                    new_jobs_count += 1
                else:
                    duplicate_found = True
                    break
            except Exception as e:
                logging.error(f"Failed to insert job {job['job_id']}: {str(e)}")
                continue

        logging.info(f"Added {new_jobs_count} new jobs to Airtable")
        if duplicate_found:
            logging.info("Stopped processing due to duplicate job found")

    def update_record(self, record_id: str, fields: dict):
        """Update an existing record in Airtable"""
        try:
            self.table.update(record_id, fields)
            logging.info(f"Successfully updated record {record_id}")
        except Exception as e:
            logging.error(f"Error updating record {record_id}: {str(e)}")
            raise
