import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any
from functools import wraps

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from openai import OpenAI

from core.config import load_config
from tasks.job_scraping.scrapers import create_scraper
from tasks.job_scraping.job_analyzer import JobAnalyzerService
from tasks.job_scraping.tech_keywords import TechKeywordsService
from services.airtable_service import AirtableManager
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
        load_dotenv()
        self.config = load_config()

        # Initialize services
        self.openai_client = self._setup_openai()
        self.airtable = AirtableManager()
        self.analyzer = JobAnalyzerService(self.config, self.openai_client)
        self.tech_keywords_service = TechKeywordsService(
            self.config, self.openai_client
        )
        self.context = {}

    def _setup_openai(self):
        """Configure OpenAI client"""
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        return OpenAI(api_key=openai_api_key)

    @task_handler
    def scrape_jobs(self, platform: str) -> List[Dict]:
        """Scrape raw jobs from the platform and filter existing ones"""
        scraper = create_scraper(platform, self.config)
        job_previews = scraper.get_job_previews() or []

        # Filter out existing jobs
        new_jobs = [
            preview
            for preview in job_previews
            if preview["job_id"] not in self.airtable.existing_job_ids
        ]

        if not new_jobs:
            self.logger.info("No new jobs to process")
            return []

        # Fetch details for new jobs
        raw_jobs = []
        for preview in new_jobs:
            job_id = preview["job_id"]
            self.logger.info(f"Fetching details for: {preview['title']} (ID: {job_id})")

            job_details = scraper.get_job_details(job_id)
            if job_details:
                raw_jobs.append({**preview, **job_details})

        self.context["raw_jobs"] = raw_jobs
        return raw_jobs

    @task_handler
    def analyze_jobs(self, platform: str) -> List[Dict]:
        """Analyze and enrich jobs with AI insights"""
        jobs = self.context.get("raw_jobs", [])
        if not jobs:
            return []

        self.logger.info(f"Analyzing {len(jobs)} jobs")
        processed_jobs = []

        for job in jobs:
            try:
                # Get main analysis and tech keywords
                enriched_job = self.analyzer.analyze_job(job)
                tech_keywords_result = self.tech_keywords_service.analyze_job(job)

                # Merge analyses if both successful
                if (
                    enriched_job
                    and tech_keywords_result
                    and isinstance(enriched_job.get("analysis"), dict)
                ):
                    if isinstance(tech_keywords_result.get("analysis"), dict):
                        enriched_job["analysis"]["tech_keywords"] = (
                            tech_keywords_result["analysis"].get("tech_keywords", [])
                        )

                    processed_jobs.append(enriched_job)
                    score = enriched_job["analysis"].get("score", "N/A")
                    self.logger.info(f"Analyzed: {job['title']} (Score: {score})")
            except Exception as e:
                self.logger.error(f"Failed to analyze {job['title']}: {str(e)}")

        self.context["processed_jobs"] = processed_jobs
        return processed_jobs

    @task_handler
    def save_jobs(self, platform: str) -> bool:
        """Save processed jobs to Airtable"""
        processed_jobs = self.context.get("processed_jobs", [])
        if not processed_jobs:
            return False

        self.logger.info(f"Saving {len(processed_jobs)} jobs to Airtable")
        self.airtable.batch_insert_jobs(processed_jobs)
        return True

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

        # Execute pipeline stages
        raw_jobs = self.scrape_jobs(platform)
        if not raw_jobs:
            return {"status": "completed", "jobs_processed": 0, "platform": platform}

        processed_jobs = self.analyze_jobs(platform)
        jobs_saved = 0

        if processed_jobs:
            self.save_jobs(platform)
            jobs_saved = len(processed_jobs)
            self.print_results(platform)

        return {
            "status": "success",
            "platform": platform,
            "jobs_processed": len(processed_jobs),
            "jobs_saved": jobs_saved,
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

            duration = (datetime.now() - start_time).total_seconds()

            pipeline_results = {
                "status": "success",
                "platforms_processed": len(platforms),
                "total_jobs_processed": total_jobs_processed,
                "duration_seconds": duration,
                "platform_results": platform_results,
            }

            self.logger.info(f"Pipeline completed in {duration:.2f} seconds")
            return pipeline_results

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.exception(f"Pipeline failed: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "duration_seconds": duration,
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
