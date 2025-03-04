"""Airtable script to create company records and link jobs to companies."""

import os
import sys
from datetime import datetime
from typing import Dict, List, Set

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from services.airtable_service import AirtableManager
from core.logging import setup_logger

# Load environment variables
load_dotenv()

# Setup logging
logger = setup_logger()


class CompanyLinkManager(AirtableManager):
    """Manager for handling company records and linking jobs to companies."""

    def __init__(self):
        super().__init__()

        # Initialize companies table
        self.companies_table_name = "Companies"
        self.companies_table = self._init_companies_table()

        # Cache for existing companies to avoid duplicate API calls
        self.existing_companies = self._get_existing_companies()

    def _init_companies_table(self):
        """Initialize the Companies table connection."""
        try:
            from pyairtable import Table

            companies_table = Table(
                self.api_key, self.base_id, self.companies_table_name
            )

            # Test the connection by making a simple request
            test_records = companies_table.all(max_records=1)
            logger.info(
                f"Successfully connected to Companies table. Found {len(test_records)} test record(s)"
            )
            return companies_table
        except Exception as e:
            logger.error(f"Failed to connect to Companies table: {str(e)}")
            raise

    def _get_existing_companies(self) -> Dict[str, str]:
        """
        Get mapping of company names to their record IDs.

        Returns:
            Dict[str, str]: Dictionary mapping company names (lowercase) to their record IDs
        """
        try:
            records = self.companies_table.all()
            logger.info(f"Retrieved {len(records)} existing company records")

            # Create a mapping of company names (lowercase) to record IDs
            company_map = {}
            for record in records:
                company_name = record.get("fields", {}).get("Name", "")
                if company_name:
                    company_map[company_name.lower()] = record["id"]

            logger.info(f"Cached {len(company_map)} company names")
            return company_map
        except Exception as e:
            logger.error(f"Error fetching existing companies: {str(e)}")
            return {}

    def create_company_record(self, company_name: str) -> str:
        """
        Create a new company record if it doesn't exist.

        Args:
            company_name: Name of the company

        Returns:
            str: Record ID of the company
        """
        # Check if company already exists in cache (case-insensitive)
        company_lower = company_name.lower()
        if company_lower in self.existing_companies:
            logger.debug(f"Company '{company_name}' already exists, skipping creation")
            return self.existing_companies[company_lower]

        try:
            # Create new company record
            company_data = {
                "Name": company_name,
                "Created At": datetime.now().isoformat(),
            }

            new_record = self.companies_table.create(company_data)
            record_id = new_record["id"]

            # Add to cache
            self.existing_companies[company_lower] = record_id
            logger.info(
                f"Created new company record for '{company_name}' with ID: {record_id}"
            )

            return record_id
        except Exception as e:
            logger.error(
                f"Error creating company record for '{company_name}': {str(e)}"
            )
            raise

    def link_jobs_to_companies(self):
        """
        Loop through all job records, create companies if needed, and link jobs to companies.
        """
        # Get all jobs
        try:
            jobs = self.table.all()
            logger.info(f"Processing {len(jobs)} job records")

            # Count for reporting
            processed_count = 0
            linked_count = 0
            skipped_count = 0
            error_count = 0

            for job in jobs:
                job_id = job.get("id")
                fields = job.get("fields", {})
                company_name = fields.get("Company")

                # Skip if no company name or already linked
                if not company_name:
                    logger.warning(f"Job {job_id} has no company name, skipping")
                    skipped_count += 1
                    continue

                if fields.get("company_link"):
                    logger.debug(f"Job {job_id} already linked to a company, skipping")
                    skipped_count += 1
                    continue

                try:
                    # Create or get company record ID
                    company_record_id = self.create_company_record(company_name)

                    # Link job to company
                    self.table.update(
                        job_id,
                        {
                            "company_link": [
                                company_record_id
                            ]  # Airtable requires an array for links
                        },
                    )

                    logger.info(
                        f"Linked job '{fields.get('Title', 'Unknown')}' to company '{company_name}'"
                    )
                    linked_count += 1

                except Exception as e:
                    logger.error(f"Error processing job {job_id}: {str(e)}")
                    error_count += 1

                processed_count += 1

                # Log progress periodically
                if processed_count % 50 == 0:
                    logger.info(f"Processed {processed_count}/{len(jobs)} jobs...")

            logger.info(
                f"Job linking complete: {linked_count} jobs linked, "
                f"{skipped_count} skipped, {error_count} errors"
            )

        except Exception as e:
            logger.error(f"Error linking jobs to companies: {str(e)}")
            raise


def main():
    """Main function to run the company linking script."""
    logger.info("Starting company linking process")

    try:
        # Initialize manager and run linking process
        manager = CompanyLinkManager()
        manager.link_jobs_to_companies()
        logger.info("Company linking process completed successfully")
    except Exception as e:
        logger.error(f"Company linking process failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
