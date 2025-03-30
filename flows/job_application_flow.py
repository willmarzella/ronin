#!/usr/bin/env python
"""
Job Application Flow for Prefect
This flow processes job applications by preparing and submitting them.
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
from tasks.job_application.application_manager import ApplicationManager
from tasks.job_application.resume_customizer import ResumeCustomizer
from tasks.job_application.cover_letter_generator import CoverLetterGenerator
from blocks.airtable_service import AirtableManager
from blocks.notification_service import NotificationService


@task(name="fetch_pending_applications", retries=2, retry_delay_seconds=30)
def fetch_pending_applications(config: Dict[str, Any], limit: int = 5) -> List[Dict]:
    """Fetch pending job applications from Airtable."""
    logger = get_run_logger()
    logger.info(f"Fetching up to {limit} pending job applications")

    airtable = AirtableManager()

    # Get jobs marked for application
    pending_applications = airtable.get_jobs_for_application(limit=limit)
    logger.info(f"Found {len(pending_applications)} pending applications")

    return pending_applications


@task(name="prepare_application_materials", retries=1)
def prepare_application_materials(job: Dict, config: Dict[str, Any]) -> Dict:
    """Prepare customized resume and cover letter for the job."""
    logger = get_run_logger()
    job_id = job.get("id", "unknown")
    job_title = job.get("title", "unknown")
    logger.info(f"Preparing application materials for job: {job_title} (ID: {job_id})")

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize services
    resume_customizer = ResumeCustomizer(config, openai_client)
    cover_letter_generator = CoverLetterGenerator(config, openai_client)

    # Prepare application package
    try:
        # Customize resume
        logger.info(f"Customizing resume for job: {job_title}")
        resume_path = resume_customizer.create_customized_resume(job)

        # Generate cover letter
        logger.info(f"Generating cover letter for job: {job_title}")
        cover_letter_path = cover_letter_generator.generate_cover_letter(job)

        # Update job with application materials paths
        job["resume_path"] = resume_path
        job["cover_letter_path"] = cover_letter_path
        job["materials_ready"] = True

        logger.info(f"Successfully prepared materials for job: {job_title}")
        return job
    except Exception as e:
        logger.error(f"Error preparing materials for job {job_title}: {str(e)}")
        job["materials_ready"] = False
        job["error"] = str(e)
        return job


@task(name="submit_application", retries=2, retry_delay_seconds=60)
def submit_application(job: Dict, config: Dict[str, Any]) -> Dict:
    """Submit the job application through the appropriate channel."""
    logger = get_run_logger()
    job_id = job.get("id", "unknown")
    job_title = job.get("title", "unknown")

    if not job.get("materials_ready", False):
        logger.warning(
            f"Materials not ready for job: {job_title}. Skipping submission."
        )
        return job

    logger.info(f"Submitting application for job: {job_title} (ID: {job_id})")

    # Initialize application manager
    application_manager = ApplicationManager(config)

    try:
        # Submit application
        submission_result = application_manager.submit_application(job)

        # Update job with submission result
        job["submission_result"] = submission_result
        job["submission_date"] = datetime.now().isoformat()
        job["status"] = (
            "submitted"
            if submission_result.get("success", False)
            else "submission_failed"
        )

        logger.info(f"Application submission for job {job_title}: {job['status']}")
        return job
    except Exception as e:
        logger.error(f"Error submitting application for job {job_title}: {str(e)}")
        job["submission_result"] = {"success": False, "error": str(e)}
        job["status"] = "submission_failed"
        return job


@task(name="update_application_status", retries=2, retry_delay_seconds=30)
def update_application_status(job: Dict) -> bool:
    """Update the job application status in Airtable."""
    logger = get_run_logger()
    job_id = job.get("id", "unknown")
    job_title = job.get("title", "unknown")
    logger.info(f"Updating application status for job: {job_title} (ID: {job_id})")

    airtable = AirtableManager()

    try:
        # Update job status in Airtable
        result = airtable.update_job_application_status(job)
        logger.info(
            f"Successfully updated status for job: {job_title} to {job.get('status', 'unknown')}"
        )
        return result
    except Exception as e:
        logger.error(f"Error updating status for job {job_title}: {str(e)}")
        return False


@flow(name="Process Single Application", log_prints=True)
def process_application_flow(job: Dict) -> Dict:
    """Process a single job application."""
    logger = get_run_logger()
    job_id = job.get("id", "unknown")
    job_title = job.get("title", "unknown")
    logger.info(f"Processing application for job: {job_title} (ID: {job_id})")

    # Load configuration
    config = load_config()

    # Step 1: Prepare application materials
    job_with_materials = prepare_application_materials(job, config)

    # Step 2: Submit application if materials are ready
    if job_with_materials.get("materials_ready", False):
        job_after_submission = submit_application(job_with_materials, config)
    else:
        job_after_submission = job_with_materials
        job_after_submission["status"] = "preparation_failed"

    # Step 3: Update application status
    update_result = update_application_status(job_after_submission)
    job_after_submission["update_result"] = update_result

    return job_after_submission


@flow(name="Job Application", log_prints=True)
def job_application_flow(application_limit: int = 5) -> Dict[str, Any]:
    """
    Main job application flow that coordinates the preparation and submission of applications.

    Args:
        application_limit: Maximum number of applications to process.

    Returns:
        Dictionary with results of the application process.
    """
    logger = get_run_logger()
    run_context = get_run_context()
    logger.info(f"Starting job application flow run: {run_context.flow_run.name}")

    # Load environment variables
    load_dotenv()

    # Load configuration
    config = load_config()

    # Set up notification service
    notification_service = NotificationService(config)

    # Step 1: Fetch pending applications
    pending_applications = fetch_pending_applications(
        config=config, limit=application_limit
    )

    if not pending_applications:
        logger.info("No pending applications to process")
        return {"status": "complete", "applications_processed": 0}

    # Step 2: Process each application
    results = []
    for job in pending_applications:
        try:
            logger.info(
                f"Processing application for job: {job.get('title', 'unknown')}"
            )
            application_result = process_application_flow(job)
            results.append(application_result)

            # Send notification based on result
            if application_result.get("status") == "submitted":
                notification_service.send_success_notification(
                    message=f"Successfully submitted application for {job.get('title', 'unknown')}",
                    context={
                        "job_id": job.get("id", "unknown"),
                        "job_title": job.get("title", "unknown"),
                        "company": job.get("company", "unknown"),
                    },
                    pipeline_name="Job Application Pipeline",
                )
            elif application_result.get("status") in [
                "preparation_failed",
                "submission_failed",
            ]:
                notification_service.send_error_notification(
                    error_message=f"Failed to process application for {job.get('title', 'unknown')}",
                    context={
                        "job_id": job.get("id", "unknown"),
                        "job_title": job.get("title", "unknown"),
                        "company": job.get("company", "unknown"),
                        "error": application_result.get("error", "Unknown error"),
                    },
                    pipeline_name="Job Application Pipeline",
                )
        except Exception as e:
            logger.error(
                f"Error processing application for job {job.get('title', 'unknown')}: {str(e)}"
            )
            results.append(
                {
                    "id": job.get("id", "unknown"),
                    "title": job.get("title", "unknown"),
                    "status": "processing_failed",
                    "error": str(e),
                }
            )

            # Send error notification
            notification_service.send_error_notification(
                error_message=f"Error in job application flow for {job.get('title', 'unknown')}: {str(e)}",
                context={
                    "job_id": job.get("id", "unknown"),
                    "job_title": job.get("title", "unknown"),
                    "company": job.get("company", "unknown"),
                    "error_type": "FLOW_ERROR",
                },
                pipeline_name="Job Application Pipeline",
            )

    # Calculate statistics
    successful = sum(1 for r in results if r.get("status") == "submitted")
    failed = len(results) - successful

    logger.info(
        f"Job application flow complete. Processed {len(results)} applications: {successful} successful, {failed} failed"
    )

    return {
        "status": "complete",
        "applications_processed": len(results),
        "successful": successful,
        "failed": failed,
        "results": results,
    }


if __name__ == "__main__":
    job_application_flow()
