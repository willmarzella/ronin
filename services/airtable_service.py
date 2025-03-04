"""Airtable integration for job management."""

import json
import logging
import os
import time
from typing import Optional, Set, Dict, List
from urllib.parse import urlparse
from datetime import datetime, timedelta

from pyairtable import Api, Base, Table


class AirtableManager:
    """Manager for Airtable integration."""

    # Map of job board domains to source names
    JOB_BOARD_MAPPING = {
        "seek.com.au": "seek",
        "linkedin.com": "linkedin",
        "indeed.com": "indeed",
        "boards.greenhouse.io": "greenhouse",
        "jobs.lever.co": "lever",
    }

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

            # Initialize companies table
            self.companies_table_name = "Companies"
            self.companies_table = Table(
                self.api_key, self.base_id, self.companies_table_name
            )

            # Cache for existing companies
            self.existing_companies = {}

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

    def _get_job_source(self, url: str) -> str:
        """Determine job source from URL."""
        try:
            domain = urlparse(url).netloc.lower()
            for board_domain, source in self.JOB_BOARD_MAPPING.items():
                if board_domain in domain:
                    return source
            return "unknown"
        except:
            return "unknown"

    def _get_job_id_from_url(self, url: str, source: str) -> Optional[str]:
        """Extract job ID from URL based on source."""
        try:
            if source == "seek":
                return url.split("/job/")[1].split("/")[0].split("?")[0]
            elif source == "linkedin":
                return url.split("/view/")[1].strip("/").split("?")[0]
            elif source == "indeed":
                return url.split("jk=")[1].split("&")[0]
            elif source == "greenhouse":
                return url.split("/jobs/")[1].split("?")[0]
            elif source == "lever":
                return url.split("/")[-1].split("?")[0]
        except:
            pass
        return None

    def _get_existing_job_ids(self) -> Set[str]:
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
                    continue

                # If no Job ID, try to extract from URL
                url = fields.get("URL", "")
                if url:
                    source = self._get_job_source(url)
                    job_id = self._get_job_id_from_url(url, source)
                    if job_id:
                        job_ids.add(job_id)
                        records_with_url += 1

            # Log detailed summary
            logging.info(f"Airtable records summary:")
            logging.info(f"- Total records processed: {records_processed}")
            logging.info(f"- Records with direct Job IDs: {records_with_id}")
            logging.info(f"- Records with extracted URLs: {records_with_url}")
            logging.info(f"- Total unique job IDs found: {len(job_ids)}")

            return job_ids

        except Exception as e:
            logging.error(f"Error fetching existing job IDs: {str(e)}")
            logging.error("Returning empty set to allow processing of all jobs")
            return set()

    def _is_duplicate_job(self, title: str, company: str, created_at: str) -> bool:
        """
        Check if a job with similar title and company exists within a recent time window.
        Args:
            title: Job title
            company: Company name
            created_at: ISO format date string
        """
        try:
            # Normalize strings for comparison
            title = title.lower().strip()
            company = company.lower().strip()

            # Parse the job's creation date, handling potential time information
            try:
                # Try parsing with time information
                job_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                # Fallback to just date parsing
                job_date = datetime.strptime(created_at, "%Y-%m-%d")

            # Calculate date range (3 days before and after)
            date_min = (job_date - timedelta(days=3)).strftime("%Y-%m-%d")
            date_max = (job_date + timedelta(days=3)).strftime("%Y-%m-%d")

            # Create formula to search for matching title and company within date range
            formula = f"""AND(
                LOWER({{Title}}) = '{title}',
                LOWER({{Company}}) = '{company}',
                IS_AFTER({{Created At}}, '{date_min}'),
                IS_BEFORE({{Created At}}, '{date_max}')
            )"""

            # Search for matching records
            matching_records = self.table.all(formula=formula)
            return len(matching_records) > 0
        except Exception as e:
            logging.error(f"Error checking for duplicate job: {str(e)}")
            return False

    def _get_or_create_company(self, company_name: str) -> Optional[str]:
        """
        Get existing company record ID or create a new one if it doesn't exist.

        Args:
            company_name: Name of the company

        Returns:
            str: Record ID of the company or None if error
        """
        if not company_name:
            logging.warning("Empty company name provided, cannot create company record")
            return None

        # Check if company already exists in cache (case-insensitive)
        company_lower = company_name.lower()
        if company_lower in self.existing_companies:
            logging.debug(f"Company '{company_name}' found in cache")
            return self.existing_companies[company_lower]

        try:
            # Look up company in Airtable
            formula = f"LOWER({{Name}}) = '{company_lower}'"
            company_records = self.companies_table.all(formula=formula)

            if company_records:
                # Company exists, save to cache and return ID
                company_id = company_records[0]["id"]
                self.existing_companies[company_lower] = company_id
                logging.info(
                    f"Found existing company record for '{company_name}' with ID: {company_id}"
                )
                return company_id

            # Create new company record
            company_data = {
                "Name": company_name,
                "Created At": datetime.now().isoformat(),
            }

            new_record = self.companies_table.create(company_data)
            company_id = new_record["id"]

            # Add to cache
            self.existing_companies[company_lower] = company_id
            logging.info(
                f"Created new company record for '{company_name}' with ID: {company_id}"
            )

            return company_id
        except Exception as e:
            logging.error(
                f"Error getting/creating company record for '{company_name}': {str(e)}"
            )
            return None

    def insert_job(self, job_data: Dict) -> bool:
        """Insert a job into Airtable if it doesn't exist"""
        job_id = job_data["job_id"]

        # Skip if job ID already exists
        if job_id in self.existing_job_ids:
            logging.info(f"Job {job_id} already exists in Airtable, skipping")
            return False

        try:
            # Get analysis data (already a dict from OpenAI)
            analysis_data = job_data["analysis"]

            # Get job source from URL
            url = job_data.get("url", "")
            source = job_data.get("source") or self._get_job_source(url)

            # Get or create company record
            company_name = job_data.get("company", "")
            company_record_id = self._get_or_create_company(company_name)

            # Format the data for Airtable
            airtable_data = {
                "Title": job_data["title"],
                "Job ID": job_id,
                "Description": job_data["description"],
                "Score": analysis_data.get("score", 0),
                "Tech Stack": analysis_data.get("tech_stack", "N/A"),
                "Recommendation": analysis_data.get("recommendation", ""),
                "URL": url,
                "Source": source,  # Add source field
                "Quick Apply": job_data.get("quick_apply", False),
                "Created At": job_data.get("created_at"),
                "Pay": job_data.get("pay_rate", ""),
                "Type": job_data.get("work_type", ""),
                "Location": job_data.get("location", ""),
                "Status": "DISCOVERED",  # Initial status
                "Keywords": ", ".join(analysis_data.get("tech_keywords", [])),
            }

            # Add company link if we have a company record ID
            if company_record_id:

                airtable_data["Company"] = [
                    company_record_id
                ]  # Airtable requires an array for links
                logging.info(
                    f"Linking job {job_id} to company '{company_name}' (ID: {company_record_id})"
                )

            # Create record in Airtable
            self.table.create(airtable_data)
            self.existing_job_ids.add(job_id)  # Add to local cache
            logging.info(f"Successfully added job {job_id} to Airtable")
            return True

        except Exception as e:
            logging.error(f"Error adding job to Airtable: {str(e)}")
            raise

    def batch_insert_jobs(self, jobs_data: List[Dict]):
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

    def get_pending_jobs(self) -> List[Dict]:
        """Get jobs from Airtable that are ready to apply to."""
        try:
            # Get all records where Status is 'DISCOVERED' and Quick Apply is True
            formula = "AND({Status} = 'DISCOVERED', {Quick Apply} = TRUE())"
            records = self.table.all(formula=formula)

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
                            source = self._get_job_source(url)

                        # Get job ID based on source
                        job_id = self._get_job_id_from_url(url, source)
                        if not job_id:
                            logging.warning(
                                f"Could not extract job ID from URL {url}, skipping"
                            )
                            continue

                        jobs.append(
                            {
                                "job_id": job_id,
                                "description": fields.get("Description", ""),
                                "title": fields.get("Title", ""),
                                "tech_stack": fields.get("Tech Stack", ""),
                                "record_id": record["id"],
                                "source": source,
                                "url": url,
                                "score": fields.get("Score", ""),
                                "company": fields.get("Company", ""),
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

    def update_job_statuses(self, processed_jobs: List[Dict]):
        """Update job statuses in Airtable based on application results."""
        for job in processed_jobs:
            try:
                record_id = job.get("record_id")
                status = job.get("application_status")

                if not record_id or not status:
                    logging.warning(
                        f"Missing record_id or status for job: {job.get('title', 'Unknown')}"
                    )
                    continue
                print(
                    f"Updating status for job {job.get('title', 'Unknown')} to {status}"
                )

                fields = {"Status": status}

                # Add error message if available
                if status == "ERROR" and "error_message" in job:
                    fields["APP_ERROR"] = job["error_message"]

                self.update_record(record_id, fields)
                logging.info(
                    f"Updated status for job {job.get('title', 'Unknown')} to {status}"
                )

            except Exception as e:
                logging.error(
                    f"Failed to update status for job {job.get('title', 'Unknown')}: {str(e)}"
                )

    def get_jobs_by_source(
        self, source: str, status: Optional[str] = None
    ) -> List[Dict]:
        """Get jobs filtered by source and optionally by status."""
        try:
            formula = f"{{Source}} = '{source}'"
            if status:
                formula = f"AND({formula}, {{Status}} = '{status}')"

            records = self.table.all(formula=formula)
            return [{"id": r["id"], **r["fields"]} for r in records]
        except Exception as e:
            logging.error(f"Error getting jobs by source {source}: {str(e)}")
            return []
