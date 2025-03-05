import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from functools import wraps
import logging
import yaml

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from openai import OpenAI

from core.config import load_config
from tasks.job_scraping.scrapers import create_scraper
from tasks.job_scraping.job_analyzer import JobAnalyzerService
from tasks.job_scraping.tech_keywords import TechKeywordsService
from services.airtable_service import AirtableManager
from services.openai_service import OpenAIService
from services.notification_service import NotificationService
from core.logging import setup_logger


def task_handler(func):
    """Decorator to handle exceptions and logging for pipeline tasks"""

    @wraps(func)
    def wrapper(self, platform, *args, **kwargs):
        task_name = func.__name__.replace("_", " ").capitalize()
        self.logger.info(f"Starting {task_name} for {platform.upper()}")
        try:
            result = func(self, platform, *args, **kwargs)
            self.logger.info(f"Completed {task_name} for {platform.upper()}")
            return result
        except Exception as e:
            self.logger.exception(f"Error during {task_name} for {platform}: {str(e)}")
            return []

    return wrapper


class JobSearchPipeline:
    def __init__(self):
        # Initialize logger and configuration
        self.logger = setup_logger()
        self.config = self._load_config()

        # Initialize services
        self.airtable = AirtableManager()
        self.tech_keywords_service = TechKeywordsService()
        self.notification_service = NotificationService(self.config)

        # Initialize state
        self.context = {}

        # Set up OpenAI service as needed
        self._setup_openai()

    def _load_config(self):
        """Load configuration from config.yaml"""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "configs", "config.yaml"
        )
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Error loading config: {str(e)}")
            return {}

    def _setup_openai(self):
        """Configure OpenAI client with error handling"""
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            error_msg = "OPENAI_API_KEY not found in environment variables"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        try:
            self.logger.info("Initializing OpenAI client")
            client = OpenAI(api_key=openai_api_key)

            # Test the connection with a simple request
            try:
                self.logger.debug("Testing OpenAI API connection")
                test_response = client.models.list()
                self.logger.info(
                    f"OpenAI connection successful. Available models: {len(test_response.data)}"
                )
            except Exception as e:
                self.logger.warning(f"OpenAI connection test failed: {str(e)}")
                self.logger.warning(
                    "Continuing anyway, but you may experience issues with analysis"
                )

            return client
        except Exception as e:
            error_msg = f"Failed to initialize OpenAI client: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    @task_handler
    def scrape_jobs(self, platform: str) -> List[Dict]:
        """Scrape raw jobs from the platform and filter existing ones"""
        scraper = create_scraper(platform, self.config)
        self.logger.info(f"Starting job scraping from {platform}...")

        # Get job previews
        job_previews = scraper.get_job_previews() or []
        self.logger.info(f"Found {len(job_previews)} total job previews on {platform}")

        if not job_previews:
            self.logger.warning(f"No job previews found on {platform}")
            return []

        # Filter out existing jobs
        existing_job_ids = self.airtable.existing_job_ids
        self.logger.info(f"Found {len(existing_job_ids)} existing jobs in Airtable")

        new_jobs = [
            preview
            for preview in job_previews
            if preview["job_id"] not in existing_job_ids
        ]

        if not new_jobs:
            self.logger.info(
                f"All {len(job_previews)} jobs already exist in Airtable. No new jobs to process."
            )
            return []

        self.logger.info(f"Found {len(new_jobs)} new jobs to process on {platform}")

        # Fetch details for new jobs
        raw_jobs = []
        successful_fetches = 0
        failed_fetches = 0

        for i, preview in enumerate(new_jobs):
            job_id = preview["job_id"]
            job_title = preview["title"]

            try:
                self.logger.info(
                    f"Fetching details for job {i+1}/{len(new_jobs)}: {job_title} (ID: {job_id})"
                )

                job_details = scraper.get_job_details(job_id)

                if job_details:
                    # Combine preview and details
                    complete_job = {**preview, **job_details}
                    raw_jobs.append(complete_job)
                    successful_fetches += 1

                    # Fix for 'int' object is not subscriptable error
                    description = job_details.get("description", "")
                    description_preview = str(description)[:20] if description else ""
                    self.logger.info(
                        f"Successfully fetched details for {job_title} ({description_preview}...)"
                    )
                else:
                    self.logger.warning(
                        f"Failed to get details for job {job_title} (ID: {job_id}) - Empty response"
                    )
                    failed_fetches += 1
            except Exception as e:
                self.logger.error(
                    f"Error fetching details for job {job_title} (ID: {job_id}): {str(e)}"
                )
                failed_fetches += 1

        self.logger.info(
            f"Completed job details fetching: {successful_fetches} successful, {failed_fetches} failed"
        )

        if not raw_jobs:
            self.logger.warning(f"No job details could be fetched from {platform}")
            return []

        self.logger.info(
            f"Successfully scraped {len(raw_jobs)} complete jobs from {platform}"
        )
        self.context["raw_jobs"] = raw_jobs
        return raw_jobs

    @task_handler
    def analyze_jobs(self, platform: str) -> List[Dict]:
        """Analyze and enrich jobs with AI insights"""
        jobs = self.context.get("raw_jobs", [])
        if not jobs:
            self.logger.warning("No raw jobs found in context. Skipping analysis.")
            return []

        self.logger.info(f"Analyzing {len(jobs)} jobs")
        processed_jobs = []

        # Check if analyzer services are properly initialized
        if not hasattr(self, "analyzer") or not self.analyzer:
            self.logger.error("JobAnalyzerService not properly initialized")
            return []

        if not hasattr(self, "tech_keywords_service") or not self.tech_keywords_service:
            self.logger.error("TechKeywordsService not properly initialized")
            return []

        # Process each job with more detailed logging
        for job in jobs:
            try:
                self.logger.info(
                    f"Starting analysis for job: {job.get('title', 'Unknown')}"
                )

                # Get main analysis with error handling
                try:
                    enriched_job = self.analyzer.analyze_job(job)
                    if not enriched_job:
                        self.logger.warning(
                            f"Main analysis returned None for job: {job.get('title', 'Unknown')}"
                        )
                        # Skip tech keywords extraction if main analysis failed
                        continue
                except Exception as e:
                    self.logger.error(
                        f"Main analyzer failed for job '{job.get('title', 'Unknown')}': {str(e)}"
                    )
                    continue

                # Get tech keywords with error handling
                try:
                    tech_keywords_result = self.tech_keywords_service.analyze_job(job)
                    if not tech_keywords_result:
                        self.logger.warning(
                            f"Tech keywords analysis returned None for job: {job.get('title', 'Unknown')}"
                        )
                except Exception as e:
                    self.logger.error(
                        f"Tech keywords analyzer failed for job '{job.get('title', 'Unknown')}': {str(e)}"
                    )
                    # Continue with just the main analysis if tech keywords fail
                    tech_keywords_result = {"analysis": {"tech_keywords": []}}

                # Merge analyses if main analysis successful
                if enriched_job and isinstance(enriched_job.get("analysis"), dict):
                    # Add tech keywords if available
                    if tech_keywords_result and isinstance(
                        tech_keywords_result.get("analysis"), dict
                    ):
                        enriched_job["analysis"]["tech_keywords"] = (
                            tech_keywords_result["analysis"].get("tech_keywords", [])
                        )
                    else:
                        # Ensure we have an empty tech_keywords field
                        enriched_job["analysis"]["tech_keywords"] = []

                    processed_jobs.append(enriched_job)
                    score = enriched_job["analysis"].get("score", "N/A")
                    self.logger.info(
                        f"Successfully analyzed: {job['title']} (Score: {score})"
                    )
                else:
                    self.logger.warning(
                        f"Skipping job due to invalid analysis format: {job.get('title', 'Unknown')}"
                    )

            except Exception as e:
                self.logger.error(
                    f"Failed to analyze {job.get('title', 'Unknown')}: {str(e)}"
                )

        self.logger.info(
            f"Analysis complete. Processed {len(processed_jobs)} out of {len(jobs)} jobs."
        )
        self.context["processed_jobs"] = processed_jobs
        return processed_jobs

    @task_handler
    def save_jobs(self, platform: str) -> bool:
        """Save processed jobs to Airtable"""
        processed_jobs = self.context.get("processed_jobs", [])
        if not processed_jobs:
            return False

        self.logger.info(f"Saving {len(processed_jobs)} jobs to Airtable")
        try:
            # Get the actual count of successful saves
            result = self.airtable.batch_insert_jobs(processed_jobs)
            self.context["jobs_saved"] = result.get("new_jobs", 0)
            self.context["duplicate_jobs"] = result.get("duplicates", 0)
            self.context["error_jobs"] = result.get("errors", 0)

            # Send notification if there are errors
            if result.get("errors", 0) > 0:
                error_message = f"Encountered {result['errors']} errors while saving jobs to Airtable"
                self.notification_service.send_error_notification(
                    error_message=error_message,
                    context={
                        "platform": platform,
                        "jobs_processed": len(processed_jobs),
                        "jobs_saved": result.get("new_jobs", 0),
                        "jobs_errors": result.get("errors", 0),
                        "error_type": "AIRTABLE_SAVE_ERROR",
                    },
                )

            return result.get("new_jobs", 0) > 0
        except Exception as e:
            self.logger.error(f"Failed to save jobs to Airtable: {str(e)}")
            self.context["jobs_saved"] = 0
            self.context["duplicate_jobs"] = 0
            self.context["error_jobs"] = len(processed_jobs)

            # Send notification about the exception
            error_message = (
                f"Exception occurred while saving jobs to Airtable: {str(e)}"
            )
            self.notification_service.send_error_notification(
                error_message=error_message,
                context={
                    "platform": platform,
                    "jobs_processed": len(processed_jobs),
                    "jobs_errors": len(processed_jobs),
                    "exception": e,
                    "error_type": "AIRTABLE_EXCEPTION",
                },
            )

            return False

    def print_results(self, platform: str):
        """Print summary of job processing results"""
        processed_jobs = self.context.get("processed_jobs", [])
        successful_jobs = []

        self.logger.info(f"\n=== Job Processing Summary for {platform.upper()} ===")

        for job in processed_jobs:
            try:
                analysis = (
                    job.get("analysis", {})
                    if isinstance(job.get("analysis"), dict)
                    else {}
                )

                job_summary = {
                    "id": job["job_id"],
                    "title": job["title"],
                    "company": job["company"],
                    "created_at": job.get("created_at", "No date"),
                    "score": analysis.get("score", "N/A"),
                    "tech_stack": analysis.get("tech_stack", "N/A"),
                    "recommendation": analysis.get("recommendation", ""),
                    "tech_keywords": analysis.get("tech_keywords", []),
                }
                successful_jobs.append(job_summary)
            except KeyError as e:
                self.logger.error(f"Error in job summary: missing key {str(e)}")

        if successful_jobs:
            self.logger.info("\nProcessed Jobs:")
            self.logger.info("---------------")
            for job in successful_jobs:
                self.logger.info(
                    f"[{job['score']}] {job['title']} at {job['company']} "
                    f"(ID: {job['id']}) - Created: {job['created_at']}\n"
                    f"Tech Stack: {', '.join(job['tech_stack'] if isinstance(job['tech_stack'], list) else [])}\n"
                    f"Recommendation: {job['recommendation']}\n"
                )

        total = len(processed_jobs)
        successful = len(successful_jobs)
        self.logger.info(f"\nTotal jobs processed: {total}")
        self.logger.info(f"Successfully processed: {successful}")
        self.logger.info(f"Failed to process: {total - successful}")

    def process_platform(self, platform: str) -> Dict[str, Any]:
        """Process a single platform through all pipeline stages"""
        self.context = {}  # Reset context for this platform
        self.logger.info(f"===== Starting pipeline for {platform.upper()} =====")

        try:
            # Step 1: Scrape jobs
            raw_jobs = self.scrape_jobs(platform)
            if not raw_jobs:
                self.logger.warning(
                    f"No jobs found for {platform}. Skipping remaining steps."
                )
                return {
                    "status": "completed",
                    "jobs_processed": 0,
                    "platform": platform,
                }

            self.logger.info(
                f"Scraped {len(raw_jobs)} jobs from {platform}. Continuing to analysis..."
            )

            # Step 2: Analyze jobs
            processed_jobs = self.analyze_jobs(platform)

            # Step 3: Save to Airtable if we have processed jobs
            if processed_jobs:
                self.logger.info(
                    f"Proceeding to save {len(processed_jobs)} analyzed jobs to Airtable..."
                )
                save_result = self.save_jobs(platform)

                # Get the actual counts from context
                jobs_saved = self.context.get("jobs_saved", 0)
                duplicate_jobs = self.context.get("duplicate_jobs", 0)
                error_jobs = self.context.get("error_jobs", 0)

                if save_result:
                    self.logger.info(
                        f"Successfully saved {jobs_saved} jobs to Airtable"
                    )
                    if duplicate_jobs > 0:
                        self.logger.info(f"Skipped {duplicate_jobs} duplicate jobs")
                    if error_jobs > 0:
                        self.logger.warning(
                            f"Failed to save {error_jobs} jobs due to errors"
                        )
                else:
                    if jobs_saved > 0:
                        self.logger.info(
                            f"Partially successful: saved {jobs_saved} jobs to Airtable"
                        )
                        if duplicate_jobs > 0:
                            self.logger.info(f"Skipped {duplicate_jobs} duplicate jobs")
                        self.logger.error(
                            f"Failed to save {error_jobs} jobs due to errors"
                        )
                    else:
                        error_msg = f"Failed to save any jobs to Airtable. {error_jobs} jobs had errors."
                        self.logger.error(error_msg)
                        # Only send a notification if all jobs failed and none were saved
                        self.notification_service.send_error_notification(
                            error_message=error_msg,
                            context={
                                "platform": platform,
                                "jobs_processed": len(processed_jobs),
                                "jobs_errors": error_jobs,
                                "error_type": "COMPLETE_SAVE_FAILURE",
                            },
                        )

                # Print results summary
                self.print_results(platform)
            else:
                self.logger.warning(
                    "No jobs passed analysis. Nothing to save to Airtable."
                )

            self.logger.info(f"===== Completed pipeline for {platform.upper()} =====")
            return {
                "status": "success",
                "platform": platform,
                "jobs_processed": len(processed_jobs),
                "jobs_saved": self.context.get("jobs_saved", 0),
                "jobs_duplicates": self.context.get("duplicate_jobs", 0),
                "jobs_errors": self.context.get("error_jobs", 0),
            }
        except Exception as e:
            self.logger.error(f"Error processing platform {platform}: {str(e)}")

            # Send notification about the platform processing error
            error_message = f"Error processing platform {platform}: {str(e)}"
            self.notification_service.send_error_notification(
                error_message=error_message,
                context={
                    "platform": platform,
                    "exception": e,
                    "error_type": "PLATFORM_PROCESSING_ERROR",
                },
            )

            return {
                "status": "error",
                "platform": platform,
                "error": str(e),
            }

    def run(self) -> Dict[str, Any]:
        """Execute the complete pipeline for all platforms"""
        start_time = datetime.now()
        self.logger.info("Starting job search pipeline")

        try:
            platforms = ["seek"]  # Could be expanded based on config
            platform_results = []
            total_jobs_processed = 0

            for platform in platforms:
                result = self.process_platform(platform)
                platform_results.append(result)
                if result["status"] == "success":
                    total_jobs_processed += result["jobs_processed"]

            # Calculate duration
            duration = datetime.now() - start_time
            duration_seconds = duration.total_seconds()
            duration_readable = str(duration).split(".")[0]  # HH:MM:SS

            self.logger.info(f"Job search pipeline completed in {duration_readable}")
            self.logger.info(f"Total jobs processed: {total_jobs_processed}")

            return {
                "status": "success",
                "platforms": platform_results,
                "total_jobs_processed": total_jobs_processed,
                "duration_seconds": duration_seconds,
            }
        except Exception as e:
            self.logger.error(f"Error in job search pipeline: {str(e)}")

            # Send notification about the unhandled exception
            error_message = f"Unhandled exception in job search pipeline: {str(e)}"
            self.notification_service.send_error_notification(
                error_message=error_message,
                context={"exception": e, "error_type": "PIPELINE_EXCEPTION"},
            )

            return {
                "status": "error",
                "error": str(e),
            }


def main():
    try:
        pipeline = JobSearchPipeline()
        results = pipeline.run()

        # Print final summary
        if results["status"] == "success":
            print("\nPipeline Summary:")
            print(f"Platforms Processed: {results['platforms_processed']}")
            print(f"Total Jobs Processed: {results['total_jobs_processed']}")
            print(f"Duration: {results['duration_seconds']:.2f} seconds")

            for result in results["platform_results"]:
                print(
                    f"\n{result['platform'].upper()}: {result['status']} - {result['jobs_processed']} jobs processed"
                )
        else:
            print(f"\nPipeline failed: {results['error']}")

    except Exception as e:
        print(f"Critical error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
