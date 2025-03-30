#!/usr/bin/env python
"""
Job Search Flow for Prefect
This flow scrapes, analyzes, and saves job listings from multiple platforms.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add the parent directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))

import yaml
from dotenv import load_dotenv
from prefect import flow, task, get_run_logger
from prefect.blocks.system import Secret
from prefect.context import get_run_context

from openai import OpenAI

from utils.config import load_config
from tasks.job_scraping.scrapers import create_scraper
from tasks.job_scraping.job_analyzer import JobAnalyzerService
from tasks.job_scraping.tech_keywords import TechKeywordsService
from blocks.airtable_service import AirtableManager
from blocks.notification_service import NotificationService


@task(name="scrape_jobs", retries=2, retry_delay_seconds=60)
def scrape_jobs(platform: str, config: Dict[str, Any]) -> List[Dict]:
    """Scrape raw jobs from the platform and filter existing ones."""
    logger = get_run_logger()
    logger.info(f"Starting job scraping from {platform}...")

    scraper = create_scraper(platform, config)
    scraper.headers = get_default_headers()

    # Get job previews
    job_previews = scraper.get_job_previews() or []
    logger.info(f"Found {len(job_previews)} total job previews on {platform}")

    if not job_previews:
        logger.warning(f"No job previews found on {platform}")
        return []

    # Filter out existing jobs
    airtable = AirtableManager()
    existing_job_ids = airtable.existing_job_ids
    logger.info(f"Found {len(existing_job_ids)} existing jobs in Airtable")

    new_jobs = [
        preview for preview in job_previews if preview["job_id"] not in existing_job_ids
    ]

    if not new_jobs:
        logger.info(
            f"All {len(job_previews)} jobs already exist in Airtable. No new jobs to process."
        )
        return []

    logger.info(f"Found {len(new_jobs)} new jobs to process on {platform}")

    # Fetch details for new jobs
    raw_jobs = []
    successful_fetches = 0
    failed_fetches = 0

    for i, preview in enumerate(new_jobs):
        job_id = preview["job_id"]
        job_title = preview["title"]

        try:
            logger.info(
                f"Fetching details for job {i+1}/{len(new_jobs)}: {job_title} (ID: {job_id})"
            )

            job_details = scraper.get_job_details(job_id)

            if job_details:
                # Combine preview and details
                complete_job = {**preview, **job_details}
                raw_jobs.append(complete_job)
                successful_fetches += 1

                # Preview of description for logging
                description = job_details.get("description", "")
                description_preview = str(description)[:20] if description else ""
                logger.info(
                    f"Successfully fetched details for {job_title} ({description_preview}...)"
                )
            else:
                logger.warning(
                    f"Failed to get details for job {job_title} (ID: {job_id}) - Empty response"
                )
                failed_fetches += 1
        except Exception as e:
            logger.error(
                f"Error fetching details for job {job_title} (ID: {job_id}): {str(e)}"
            )
            failed_fetches += 1

    logger.info(
        f"Job scraping complete for {platform}: {successful_fetches} successful, {failed_fetches} failed"
    )
    return raw_jobs


@task(name="analyze_jobs", retries=1)
def analyze_jobs(
    raw_jobs: List[Dict], platform: str, config: Dict[str, Any]
) -> List[Dict]:
    """Analyze jobs using the JobAnalyzerService."""
    logger = get_run_logger()
    logger.info(f"Starting job analysis for {len(raw_jobs)} jobs from {platform}")

    if not raw_jobs:
        logger.info(f"No jobs to analyze for {platform}")
        return []

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize services
    analyzer = JobAnalyzerService(config, openai_client)
    tech_keywords_service = TechKeywordsService(config, openai_client)

    analyzed_jobs = []
    successful_analyses = 0
    failed_analyses = 0

    for i, job in enumerate(raw_jobs):
        job_id = job.get("job_id", "unknown")
        title = job.get("title", "unknown")

        try:
            logger.info(f"Analyzing job {i+1}/{len(raw_jobs)}: {title} (ID: {job_id})")

            # Add platform metadata
            job["platform"] = platform
            job["scrape_date"] = datetime.now().isoformat()

            # Core analysis
            match_score = analyzer.analyze_job_match(job)
            job["match_score"] = match_score
            job["match_analysis"] = analyzer.get_match_explanation(job)

            # Technical keywords extraction
            tech_keywords = tech_keywords_service.extract_tech_keywords(job)
            job["tech_keywords"] = tech_keywords

            # Calculate overall priority score
            job["priority_score"] = analyzer.calculate_priority_score(job)

            analyzed_jobs.append(job)
            successful_analyses += 1

            logger.info(f"Successfully analyzed job: {title} (Score: {match_score})")
        except Exception as e:
            logger.error(f"Error analyzing job {title} (ID: {job_id}): {str(e)}")
            failed_analyses += 1

    logger.info(
        f"Job analysis complete for {platform}: {successful_analyses} successful, {failed_analyses} failed"
    )
    return analyzed_jobs


@task(name="save_jobs", retries=2, retry_delay_seconds=30)
def save_jobs(analyzed_jobs: List[Dict], platform: str) -> bool:
    """Save analyzed jobs to Airtable."""
    logger = get_run_logger()
    logger.info(
        f"Saving {len(analyzed_jobs)} analyzed jobs from {platform} to Airtable"
    )

    if not analyzed_jobs:
        logger.info(f"No jobs to save for {platform}")
        return True

    # Initialize AirtableManager
    airtable = AirtableManager()

    # Save jobs to Airtable
    successful_saves = 0
    failed_saves = 0

    for i, job in enumerate(analyzed_jobs):
        job_id = job.get("job_id", "unknown")
        title = job.get("title", "unknown")

        try:
            logger.info(
                f"Saving job {i+1}/{len(analyzed_jobs)}: {title} (ID: {job_id})"
            )

            # Save job to Airtable
            result = airtable.save_job(job)

            if result:
                successful_saves += 1
                logger.info(f"Successfully saved job: {title} (ID: {job_id})")
            else:
                failed_saves += 1
                logger.warning(f"Failed to save job: {title} (ID: {job_id})")
        except Exception as e:
            logger.error(f"Error saving job {title} (ID: {job_id}): {str(e)}")
            failed_saves += 1

    logger.info(
        f"Job saving complete for {platform}: {successful_saves} successful, {failed_saves} failed"
    )
    return successful_saves > 0


def get_default_headers():
    """Get realistic browser headers for requests."""
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "DNT": "1",
        "Cache-Control": "max-age=0",
    }


@flow(name="Process Platform", log_prints=True)
def process_platform_flow(platform: str) -> Dict[str, Any]:
    """Process a single platform for job search."""
    logger = get_run_logger()
    start_time = datetime.now()
    logger.info(f"Starting job search pipeline for platform: {platform}")

    # Load configuration
    config = load_config()

    # Step 1: Scrape Jobs
    raw_jobs = scrape_jobs(platform=platform, config=config)

    # Step 2: Analyze Jobs
    analyzed_jobs = analyze_jobs(raw_jobs=raw_jobs, platform=platform, config=config)

    # Step 3: Save Jobs
    save_result = save_jobs(analyzed_jobs=analyzed_jobs, platform=platform)

    # Calculate execution time
    end_time = datetime.now()
    execution_time = (end_time - start_time).total_seconds()

    # Prepare result summary
    result = {
        "platform": platform,
        "raw_jobs_count": len(raw_jobs),
        "analyzed_jobs_count": len(analyzed_jobs),
        "save_status": save_result,
        "execution_time_seconds": execution_time,
    }

    logger.info(
        f"Summary for {platform}: found {len(raw_jobs)} new jobs, analyzed {len(analyzed_jobs)}"
    )
    logger.info(f"Pipeline execution time: {execution_time:.2f} seconds")

    return result


@flow(name="Job Search", log_prints=True)
def job_search_flow(platforms: List[str] = None) -> Dict[str, Any]:
    """
    Main job search flow that coordinates the scraping, analysis, and saving of jobs.

    Args:
        platforms: List of platforms to search. If None, uses config values.

    Returns:
        Dictionary with results for each platform.
    """
    logger = get_run_logger()
    run_context = get_run_context()
    logger.info(f"Starting job search flow run: {run_context.flow_run.name}")

    # Load environment variables
    load_dotenv()

    # Load configuration
    config = load_config()

    # Use provided platforms or default from config
    if not platforms:
        platforms = config.get("job_search", {}).get(
            "platforms", ["linkedin", "indeed"]
        )

    # Set up notification service
    notification_service = NotificationService(config)

    # Process each platform
    results = {}
    for platform in platforms:
        try:
            logger.info(f"Processing platform: {platform}")
            platform_result = process_platform_flow(platform)
            results[platform] = platform_result
        except Exception as e:
            logger.error(f"Error processing platform {platform}: {str(e)}")
            results[platform] = {"error": str(e)}

            # Send error notification
            notification_service.send_error_notification(
                error_message=f"Error in job search flow for platform {platform}: {str(e)}",
                context={
                    "platform": platform,
                    "error_type": "PLATFORM_ERROR",
                },
                pipeline_name="Job Search Pipeline",
            )

    # Calculate overall statistics
    total_raw_jobs = sum(
        r.get("raw_jobs_count", 0) for r in results.values() if isinstance(r, dict)
    )
    total_analyzed_jobs = sum(
        r.get("analyzed_jobs_count", 0) for r in results.values() if isinstance(r, dict)
    )

    logger.info(
        f"Job search flow complete. Found {total_raw_jobs} new jobs, analyzed {total_analyzed_jobs}"
    )

    return results


if __name__ == "__main__":
    job_search_flow()
