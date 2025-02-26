import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from core.config import load_config
from tasks.job_scraping.scrapers import create_scraper
from tasks.job_scraping.job_analyzer import JobAnalyzerService
from services.airtable_service import AirtableManager
from core.logging import setup_logger


class JobSearchPipeline:
    def __init__(self):
        # Initialize logger
        self.logger = setup_logger()

        # Load environment variables and config
        load_dotenv()
        self.config = load_config()

        # Initialize services
        self.openai_client = self._setup_openai()
        self.airtable = AirtableManager()
        self.analyzer = JobAnalyzerService(self.config, self.openai_client)

        # Pipeline context for sharing data between tasks
        self.context: Dict[str, Any] = {}

    def _setup_openai(self):
        """Configure OpenAI settings"""
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        from openai import OpenAI

        return OpenAI(api_key=openai_api_key)

    def scrape_jobs(self, platform: str) -> List[Dict]:
        """
        Task 1: Scrape raw jobs from the platform
        Returns only new jobs that don't exist in Airtable
        """
        self.logger.info(f"Starting job scraping for {platform.upper()}")

        scraper = create_scraper(platform, self.config)

        # Get job previews first (minimal info including IDs)
        job_previews = scraper.get_job_previews()

        if not job_previews:
            self.logger.warning(f"No jobs were found from {platform}")
            return []

        # Filter out existing jobs but check all previews
        new_jobs = []
        for preview in job_previews:
            if preview["job_id"] in self.airtable.existing_job_ids:
                self.logger.info(
                    f"Skipping existing job: {preview['title']} (ID: {preview['job_id']})"
                )
                continue
            new_jobs.append(preview)
            self.logger.info(
                f"Found new job preview: {preview['title']} (ID: {preview['job_id']})"
            )

        if not new_jobs:
            self.logger.info("No new jobs to process")
            return []

        # Only fetch full details for new jobs
        raw_jobs = []
        for preview in new_jobs:
            job_details = scraper.get_job_details(preview["job_id"])
            if job_details:
                full_job = {**preview, **job_details}
                raw_jobs.append(full_job)
                self.logger.info(
                    f"Fetched details for new job: {preview['title']} (ID: {preview['job_id']})"
                )

        self.context["raw_jobs"] = raw_jobs
        return raw_jobs

    def filter_existing_jobs(self, platform: str) -> List[Dict]:
        """
        Task 2: Filter out jobs that already exist in Airtable
        This is now a pass-through since filtering is done during scraping
        """
        raw_jobs = self.context.get("raw_jobs", [])
        self.logger.info(f"Proceeding with {len(raw_jobs)} pre-filtered new jobs")
        self.context["new_jobs"] = raw_jobs
        return raw_jobs

    def analyze_jobs(self, platform: str) -> List[Dict]:
        """
        Task 3: Analyze and enrich new jobs
        """
        new_jobs = self.context.get("new_jobs", [])
        if not new_jobs:
            self.logger.info(f"No new jobs to analyze from {platform}")
            return []

        self.logger.info(f"Analyzing {len(new_jobs)} new jobs")

        processed_jobs = []
        for job in new_jobs:
            try:
                self.logger.info(
                    f"Processing job: {job['title']} (ID: {job['job_id']})"
                )
                enriched_job = self.analyzer.analyze_job(job)
                if enriched_job and enriched_job.get("analysis"):
                    processed_jobs.append(enriched_job)
                    score = (
                        enriched_job["analysis"].get("score", "N/A")
                        if isinstance(enriched_job["analysis"], dict)
                        else "N/A"
                    )
                    self.logger.info(
                        f"Successfully analyzed job: {job['title']} (Score: {score})"
                    )
                else:
                    self.logger.warning(f"Failed to analyze job: {job['title']}")
            except Exception as e:
                self.logger.error(f"Error processing job {job['title']}: {str(e)}")
                continue

        self.context["processed_jobs"] = processed_jobs
        return processed_jobs

    def save_jobs(self, platform: str) -> bool:
        """
        Task 4: Save processed jobs to Airtable
        """
        processed_jobs = self.context.get("processed_jobs", [])
        if processed_jobs:
            self.logger.info(f"Saving {len(processed_jobs)} processed jobs to Airtable")
            self.airtable.batch_insert_jobs(processed_jobs)
            return True
        return False

    def print_results(self, platform: str):
        """
        Task 5: Print summary of job processing results
        """
        processed_jobs = self.context.get("processed_jobs", [])
        self.logger.info(f"\n=== Job Processing Summary for {platform.upper()} ===")

        # Count successful jobs
        successful_jobs = []
        for job in processed_jobs:
            try:
                job_summary = {
                    "id": job["job_id"],
                    "title": job["title"],
                    "company": job["company"],
                    "created_at": job.get("created_at", "No date"),
                    "score": (
                        job.get("analysis", {}).get("score", "N/A")
                        if isinstance(job.get("analysis"), dict)
                        else "N/A"
                    ),
                    "tech_stack": (
                        job.get("analysis", {}).get("tech_stack", [])
                        if isinstance(job.get("analysis"), dict)
                        else []
                    ),
                    "recommendation": (
                        job.get("analysis", {}).get("recommendation", "")
                        if isinstance(job.get("analysis"), dict)
                        else ""
                    ),
                }
                successful_jobs.append(job_summary)
            except KeyError as e:
                self.logger.error(f"Error processing job summary: missing key {str(e)}")
                self.logger.error(f"Job data: {job}")

        if successful_jobs:
            self.logger.info("\nProcessed Jobs:")
            self.logger.info("---------------")
            for job in successful_jobs:
                self.logger.info(
                    f"[{job['score']}] {job['title']} at {job['company']} "
                    f"(ID: {job['id']}) - Created: {job['created_at']}\n"
                    f"Tech Stack: {', '.join(job['tech_stack'])}\n"
                    f"Recommendation: {job['recommendation']}\n"
                )

        self.logger.info(f"\nTotal jobs processed: {len(processed_jobs)}")
        self.logger.info(f"Successfully processed: {len(successful_jobs)}")
        self.logger.info(
            f"Failed to process: {len(processed_jobs) - len(successful_jobs)}"
        )

    def process_platform(self, platform: str) -> Dict[str, Any]:
        """
        Process a single platform through all pipeline stages
        """
        try:
            # Reset context for this platform
            self.context = {}

            # Execute pipeline stages
            raw_jobs = self.scrape_jobs(platform)
            if not raw_jobs:
                return {
                    "status": "completed",
                    "jobs_processed": 0,
                    "platform": platform,
                }

            new_jobs = self.filter_existing_jobs(platform)
            if not new_jobs:
                return {
                    "status": "completed",
                    "jobs_processed": 0,
                    "platform": platform,
                }

            processed_jobs = self.analyze_jobs(platform)
            if processed_jobs:
                self.save_jobs(platform)

            self.print_results(platform)

            return {
                "status": "success",
                "platform": platform,
                "jobs_processed": len(processed_jobs),
                "jobs_saved": len(processed_jobs),
            }

        except Exception as e:
            self.logger.exception(f"Error processing {platform}: {str(e)}")
            return {"status": "error", "platform": platform, "error": str(e)}

    def run(self) -> Dict[str, Any]:
        """
        Execute the complete pipeline for all platforms
        """
        start_time = datetime.now()
        self.logger.info("Starting job search pipeline")

        try:
            # Get platforms to scrape from config
            platforms = ["seek"]  # Could be expanded based on config

            platform_results = []
            total_jobs_processed = 0

            for platform in platforms:
                result = self.process_platform(platform)
                platform_results.append(result)
                if result["status"] == "success":
                    total_jobs_processed += result["jobs_processed"]

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            pipeline_results = {
                "status": "success",
                "platforms_processed": len(platforms),
                "total_jobs_processed": total_jobs_processed,
                "duration_seconds": duration,
                "platform_results": platform_results,
            }

            self.logger.info(
                f"Pipeline completed successfully in {duration:.2f} seconds"
            )
            return pipeline_results

        except Exception as e:
            self.logger.exception(f"Pipeline failed: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "duration_seconds": (datetime.now() - start_time).total_seconds(),
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

            for platform_result in results["platform_results"]:
                platform = platform_result["platform"]
                status = platform_result["status"]
                jobs = platform_result.get("jobs_processed", 0)
                print(f"\n{platform.upper()}: {status} - {jobs} jobs processed")
        else:
            print(f"\nPipeline failed: {results['error']}")

    except Exception as e:
        print(f"Critical error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
