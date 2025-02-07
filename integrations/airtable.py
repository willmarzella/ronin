import json
import logging
import os

from pyairtable import Api, Base, Table


class AirtableManager:
    def __init__(self):
        try:
            self.api_key = os.getenv("AIRTABLE_API_KEY")
            if not self.api_key:
                raise ValueError("AIRTABLE_API_KEY environment variable not set")

            # Log first/last few characters of API key for verification
            masked_key = f"{self.api_key[:4]}...{self.api_key[-4:]}"
            logging.info(f"Using Airtable API key: {masked_key}")

            self.base_id = "appho2dXd2ZlfresS"
            self.table_name = "Jobs"
            logging.info(
                f"Initializing Airtable connection to base {self.base_id}, table {self.table_name}"
            )

            # Initialize table directly with API key
            self.table = Table(self.api_key, self.base_id, self.table_name)

            # Test the connection by making a simple request
            try:
                logging.info("Testing Airtable connection...")
                test_records = self.table.all(max_records=1)
                logging.info(
                    f"Successfully connected to Airtable. Found {len(test_records)} test record(s)"
                )
            except Exception as e:
                logging.error(f"Failed to connect to Airtable: {str(e)}")
                raise

            # Initialize existing job IDs
            logging.info("Initializing existing job IDs cache...")
            self.existing_job_ids = self._get_existing_job_ids()
            logging.info(
                f"Initialized with {len(self.existing_job_ids)} existing job IDs"
            )

        except Exception as e:
            logging.error(f"Failed to initialize AirtableManager: {str(e)}")
            raise

    def _get_existing_job_ids(self):
        """Get set of existing job IDs from Airtable"""
        try:
            logging.info("Fetching records from Airtable...")
            records = self.table.all()
            logging.info(f"Retrieved {len(records)} records from Airtable")

            if not records:
                logging.warning("No existing records found in Airtable")
                return set()

            job_ids = set()
            records_processed = 0
            records_with_id = 0
            records_with_url = 0

            # Log the first few records for debugging
            if records:
                logging.info("Sample of first 3 records:")
                for record in records[:3]:
                    logging.info(f"Record ID: {record.get('id')}")
                    logging.info(f"Fields: {record.get('fields', {})}")

            for record in records:
                records_processed += 1
                fields = record.get("fields", {})

                # Try to get Job ID directly first
                job_id = fields.get("Job ID")
                if job_id:
                    job_ids.add(job_id)
                    records_with_id += 1
                    logging.debug(
                        f"Found job ID directly: {job_id} (Record ID: {record.get('id')})"
                    )
                    continue

                # If no Job ID, try to extract from URL
                url = fields.get("URL", "")
                if url and "seek.com.au/job/" in url:
                    try:
                        # Extract job ID from URL format: https://www.seek.com.au/job/{job_id}
                        job_id = url.split("/job/")[1].split("/")[0].split("?")[0]
                        job_ids.add(job_id)
                        records_with_url += 1
                        logging.debug(f"Extracted job ID from URL: {job_id} ({url})")
                    except (IndexError, AttributeError):
                        logging.warning(f"Could not extract job ID from URL: {url}")

            # Log detailed summary
            logging.info(f"Airtable records summary:")
            logging.info(f"- Total records processed: {records_processed}")
            logging.info(f"- Records with direct Job IDs: {records_with_id}")
            logging.info(f"- Records with extracted URLs: {records_with_url}")
            logging.info(f"- Total unique job IDs found: {len(job_ids)}")

            if job_ids:
                logging.info(
                    f"First few job IDs for verification: {sorted(list(job_ids))[:5]}"
                )
                logging.info(
                    f"Last few job IDs for verification: {sorted(list(job_ids))[-5:]}"
                )

            return job_ids

        except Exception as e:
            logging.error(f"Error fetching existing job IDs: {str(e)}")
            logging.error("Returning empty set to allow processing of all jobs")
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
                "Pay": job_data.get("pay_rate", ""),
                "Type": job_data.get("work_type", ""),
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
        """Insert multiple jobs into Airtable"""
        new_jobs_count = 0
        duplicate_count = 0
        error_count = 0

        for job in jobs_data:
            try:
                if self.insert_job(job):
                    new_jobs_count += 1
                    logging.info(
                        f"Successfully inserted job {job['job_id']}: {job['title']}"
                    )
                else:
                    duplicate_count += 1
                    logging.debug(
                        f"Skipped duplicate job {job['job_id']}: {job['title']}"
                    )
            except Exception as e:
                error_count += 1
                logging.error(f"Failed to insert job {job['job_id']}: {str(e)}")
                continue

        logging.info(
            f"Batch insert complete: {new_jobs_count} new jobs added, "
            f"{duplicate_count} duplicates skipped, {error_count} errors"
        )

    def update_record(self, record_id: str, fields: dict):
        """Update an existing record in Airtable"""
        try:
            self.table.update(record_id, fields)
            logging.info(f"Successfully updated record {record_id}")
        except Exception as e:
            logging.error(f"Error updating record {record_id}: {str(e)}")
            raise
