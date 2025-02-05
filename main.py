import json
import os
from typing import List, Dict
from dotenv import load_dotenv
import openai
from app.utils.config import load_config
from app.scrapers import create_scraper
from app.services.job_analyzer import JobAnalyzerService
from app.services.job_applier import JobApplierService
from integrations import AirtableManager
from app.utils.logging import setup_logger

# Initialize logger
logger = setup_logger()

# Load environment variables
load_dotenv()

# Load configuration
config = load_config()


def setup_openai():
    """Configure OpenAI settings"""
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    openai.api_key = openai_api_key


def print_job_results(jobs_data: List[Dict], platform: str):
    """Print summary of job processing results for a platform"""
    logger.info(f"\n=== Job Processing Summary for {platform.upper()} ===")

    # Count successful jobs
    successful_jobs = []
    for job in jobs_data:
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
            logger.error(f"Error processing job summary: missing key {str(e)}")
            logger.error(f"Job data: {job}")

    if successful_jobs:
        logger.info("\nProcessed Jobs:")
        logger.info("---------------")
        for job in successful_jobs:
            logger.info(
                f"[{job['score']}] {job['title']} at {job['company']} "
                f"(ID: {job['id']}) - Created: {job['created_at']}\n"
                f"Tech Stack: {', '.join(job['tech_stack'])}\n"
                f"Recommendation: {job['recommendation']}\n"
            )

    logger.info(f"\nTotal jobs processed: {len(jobs_data)}")
    logger.info(f"Successfully processed: {len(successful_jobs)}")
    logger.info(f"Failed to process: {len(jobs_data) - len(successful_jobs)}")


def process_platform(
    platform: str, config: Dict, airtable: AirtableManager, analyzer: JobAnalyzerService
) -> List[Dict]:
    """Process jobs from a specific platform"""
    try:
        logger.info(f"\nStarting job processing for {platform.upper()}")

        # Step 1: Scrape raw job data
        scraper = create_scraper(platform, config)
        raw_jobs = scraper.scrape_jobs()

        if not raw_jobs:
            logger.warning(f"No jobs were found from {platform}")
            return []

        # Print raw jobs for debugging
        logger.info("\nRaw Jobs Data:")
        for job in raw_jobs:
            logger.info(
                f"Job ID: {job.get('job_id')} - Created At: {job.get('created_at', 'No date')}"
            )

        # Step 2: Filter out existing jobs
        new_jobs = [
            job for job in raw_jobs if job["job_id"] not in airtable.existing_job_ids
        ]

        if not new_jobs:
            logger.info(f"No new jobs found from {platform}")
            return []

        logger.info(f"Found {len(new_jobs)} new jobs to process")

        # Step 3: Analyze and enrich jobs
        processed_jobs = []
        for job in new_jobs:
            logger.info(f"Processing job: {job['title']}")
            # Analyze the job
            enriched_job = analyzer.analyze_job(job)
            if enriched_job and enriched_job.get("analysis"):
                processed_jobs.append(enriched_job)
                score = (
                    enriched_job["analysis"].get("score", "N/A")
                    if isinstance(enriched_job["analysis"], dict)
                    else "N/A"
                )
                logger.info(
                    f"Successfully analyzed job: {job['title']} (Score: {score})"
                )
            else:
                logger.warning(f"Failed to analyze job: {job['title']}")

        # Print detailed results
        print_job_results(processed_jobs, platform)

        # Step 4: Save results if we have any
        if processed_jobs:
            logger.info(f"Saving {len(processed_jobs)} processed jobs to Airtable")
            for job in processed_jobs:
                airtable.insert_job(job)
                logger.info(f"Saved job to Airtable: {job['title']}")

        return processed_jobs

    except Exception as e:
        logger.exception(f"Error processing {platform}: {str(e)}")
        return []


def apply_jobs():
    """Process jobs that are ready to be applied to"""
    try:
        logger.info("\nStarting job application process")

        # Initialize the job applier service
        applier = JobApplierService()

        # Process all pending jobs
        applier.process_pending_jobs()

        logger.info("Job application process completed")

    except Exception as e:
        logger.exception(f"Error in job application process: {str(e)}")
        raise


def main():
    try:
        # Setup
        setup_openai()
        logger.info("Starting job automation system")

        # Initialize services
        airtable = AirtableManager()
        analyzer = JobAnalyzerService(config)

        # Get platforms to scrape from config
        platforms = config.get("platforms", ["seek"])

        # Process new jobs
        total_jobs = []
        for platform in platforms:
            platform_jobs = process_platform(platform, config, airtable, analyzer)
            total_jobs.extend(platform_jobs)

        # Print scraping summary
        logger.info("\n=== Scraping Summary ===")
        logger.info(f"Total platforms processed: {len(platforms)}")
        logger.info(f"Total jobs found: {len(total_jobs)}")

        # Only run the job applier if we're not in GitHub Actions
        if not os.getenv("GITHUB_ACTIONS"):
            logger.info("Running locally - starting job application process")
            apply_jobs()
        else:
            logger.info("Running in GitHub Actions - skipping job application process")

        logger.info("Job automation completed successfully")

    except Exception as e:
        logger.exception(f"Main execution error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
