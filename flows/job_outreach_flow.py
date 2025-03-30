#!/usr/bin/env python
"""
Job Outreach Flow for Prefect
This flow manages follow-ups, networking, and communication with potential employers.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

# Add the parent directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))

import yaml
from dotenv import load_dotenv
from prefect import flow, task, get_run_logger
from prefect.blocks.system import Secret
from prefect.context import get_run_context

from openai import OpenAI

from utils.config import load_config
from tasks.job_outreach.outreach_manager import OutreachManager
from tasks.job_outreach.message_generator import MessageGenerator
from tasks.job_outreach.contact_finder import ContactFinder
from blocks.airtable_service import AirtableManager
from blocks.notification_service import NotificationService


@task(name="fetch_outreach_opportunities", retries=2, retry_delay_seconds=30)
def fetch_outreach_opportunities(config: Dict[str, Any], limit: int = 10) -> List[Dict]:
    """Fetch jobs and contacts that need outreach or follow-up."""
    logger = get_run_logger()
    logger.info(f"Fetching up to {limit} outreach opportunities")

    airtable = AirtableManager()

    # Get jobs and contacts needing follow-up
    followup_opportunities = airtable.get_followup_opportunities(limit=limit)
    logger.info(f"Found {len(followup_opportunities)} follow-up opportunities")

    return followup_opportunities


@task(name="find_contact_information", retries=2, retry_delay_seconds=45)
def find_contact_information(opportunity: Dict, config: Dict[str, Any]) -> Dict:
    """Find contact information for outreach opportunity if not already available."""
    logger = get_run_logger()
    opportunity_id = opportunity.get("id", "unknown")
    company = opportunity.get("company", "unknown")

    # Skip if contact info already exists
    if opportunity.get("contact_email") or opportunity.get("contact_linkedin"):
        logger.info(f"Contact information already exists for {company}")
        opportunity["contact_found"] = True
        return opportunity

    logger.info(f"Finding contact information for {company}")

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize contact finder
    contact_finder = ContactFinder(config, openai_client)

    try:
        # Find contact information
        contact_info = contact_finder.find_contact(opportunity)

        # Update opportunity with contact information
        opportunity.update(contact_info)
        opportunity["contact_found"] = bool(
            contact_info.get("contact_email") or contact_info.get("contact_linkedin")
        )

        if opportunity["contact_found"]:
            logger.info(
                f"Successfully found contact for {company}: {contact_info.get('contact_name', 'unknown')}"
            )
        else:
            logger.warning(f"Could not find contact information for {company}")

        return opportunity
    except Exception as e:
        logger.error(f"Error finding contact for {company}: {str(e)}")
        opportunity["contact_found"] = False
        opportunity["error"] = str(e)
        return opportunity


@task(name="generate_outreach_message", retries=1)
def generate_outreach_message(opportunity: Dict, config: Dict[str, Any]) -> Dict:
    """Generate personalized outreach message based on opportunity type."""
    logger = get_run_logger()
    opportunity_id = opportunity.get("id", "unknown")
    company = opportunity.get("company", "unknown")
    outreach_type = opportunity.get("outreach_type", "follow_up")

    if not opportunity.get("contact_found", False):
        logger.warning(f"No contact found for {company}. Cannot generate message.")
        opportunity["message_generated"] = False
        return opportunity

    logger.info(f"Generating {outreach_type} message for {company}")

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize message generator
    message_generator = MessageGenerator(config, openai_client)

    try:
        # Generate appropriate message
        if outreach_type == "follow_up":
            message = message_generator.generate_followup_message(opportunity)
        elif outreach_type == "initial_outreach":
            message = message_generator.generate_initial_outreach(opportunity)
        elif outreach_type == "thank_you":
            message = message_generator.generate_thank_you_message(opportunity)
        else:
            message = message_generator.generate_generic_message(opportunity)

        # Update opportunity with message
        opportunity["message"] = message
        opportunity["message_generated"] = True
        opportunity["message_date"] = datetime.now().isoformat()

        logger.info(f"Successfully generated {outreach_type} message for {company}")
        return opportunity
    except Exception as e:
        logger.error(f"Error generating message for {company}: {str(e)}")
        opportunity["message_generated"] = False
        opportunity["error"] = (
            f"{opportunity.get('error', '')} | Message error: {str(e)}".strip(" |")
        )
        return opportunity


@task(name="send_outreach_message", retries=2, retry_delay_seconds=60)
def send_outreach_message(opportunity: Dict, config: Dict[str, Any]) -> Dict:
    """Send the generated outreach message via appropriate channel."""
    logger = get_run_logger()
    opportunity_id = opportunity.get("id", "unknown")
    company = opportunity.get("company", "unknown")
    contact_name = opportunity.get("contact_name", "unknown")

    if not opportunity.get("message_generated", False):
        logger.warning(f"No message generated for {company}. Cannot send outreach.")
        opportunity["message_sent"] = False
        return opportunity

    logger.info(f"Sending outreach message to {contact_name} at {company}")

    # Initialize outreach manager
    outreach_manager = OutreachManager(config)

    try:
        # Determine delivery method
        delivery_method = "email" if opportunity.get("contact_email") else "linkedin"

        # Send message
        send_result = outreach_manager.send_message(
            opportunity, delivery_method=delivery_method
        )

        # Update opportunity with send result
        opportunity["send_result"] = send_result
        opportunity["message_sent"] = send_result.get("success", False)
        opportunity["send_date"] = datetime.now().isoformat()
        opportunity["delivery_method"] = delivery_method

        if opportunity["message_sent"]:
            opportunity["status"] = "message_sent"
            opportunity["next_followup_date"] = (
                datetime.now()
                + timedelta(days=config.get("outreach", {}).get("followup_days", 7))
            ).isoformat()
            logger.info(f"Successfully sent message to {contact_name} at {company}")
        else:
            opportunity["status"] = "send_failed"
            logger.warning(f"Failed to send message to {contact_name} at {company}")

        return opportunity
    except Exception as e:
        logger.error(f"Error sending message to {contact_name} at {company}: {str(e)}")
        opportunity["message_sent"] = False
        opportunity["status"] = "send_failed"
        opportunity["error"] = (
            f"{opportunity.get('error', '')} | Send error: {str(e)}".strip(" |")
        )
        return opportunity


@task(name="update_outreach_status", retries=2, retry_delay_seconds=30)
def update_outreach_status(opportunity: Dict) -> bool:
    """Update the outreach status in Airtable."""
    logger = get_run_logger()
    opportunity_id = opportunity.get("id", "unknown")
    company = opportunity.get("company", "unknown")

    logger.info(f"Updating outreach status for {company} (ID: {opportunity_id})")

    airtable = AirtableManager()

    try:
        # Update outreach status in Airtable
        result = airtable.update_outreach_status(opportunity)

        logger.info(
            f"Successfully updated outreach status for {company} to {opportunity.get('status', 'unknown')}"
        )
        return result
    except Exception as e:
        logger.error(f"Error updating outreach status for {company}: {str(e)}")
        return False


@flow(name="Process Single Outreach", log_prints=True)
def process_outreach_flow(opportunity: Dict) -> Dict:
    """Process a single outreach opportunity."""
    logger = get_run_logger()
    opportunity_id = opportunity.get("id", "unknown")
    company = opportunity.get("company", "unknown")

    logger.info(f"Processing outreach for {company} (ID: {opportunity_id})")

    # Load configuration
    config = load_config()

    # Step 1: Find contact information if needed
    opportunity_with_contact = find_contact_information(opportunity, config)

    # Step 2: Generate outreach message if contact found
    if opportunity_with_contact.get("contact_found", False):
        opportunity_with_message = generate_outreach_message(
            opportunity_with_contact, config
        )
    else:
        opportunity_with_message = opportunity_with_contact
        opportunity_with_message["status"] = "contact_not_found"

    # Step 3: Send outreach message if message generated
    if opportunity_with_message.get("message_generated", False):
        opportunity_after_send = send_outreach_message(opportunity_with_message, config)
    else:
        opportunity_after_send = opportunity_with_message
        if opportunity_after_send.get("status") != "contact_not_found":
            opportunity_after_send["status"] = "message_generation_failed"

    # Step 4: Update outreach status
    update_result = update_outreach_status(opportunity_after_send)
    opportunity_after_send["update_result"] = update_result

    return opportunity_after_send


@flow(name="Job Outreach", log_prints=True)
def job_outreach_flow(outreach_limit: int = 10) -> Dict[str, Any]:
    """
    Main job outreach flow that coordinates follow-ups and networking communications.

    Args:
        outreach_limit: Maximum number of outreach opportunities to process.

    Returns:
        Dictionary with results of the outreach process.
    """
    logger = get_run_logger()
    run_context = get_run_context()
    logger.info(f"Starting job outreach flow run: {run_context.flow_run.name}")

    # Load environment variables
    load_dotenv()

    # Load configuration
    config = load_config()

    # Set up notification service
    notification_service = NotificationService(config)

    # Step 1: Fetch outreach opportunities
    opportunities = fetch_outreach_opportunities(config=config, limit=outreach_limit)

    if not opportunities:
        logger.info("No outreach opportunities to process")
        return {"status": "complete", "opportunities_processed": 0}

    # Step 2: Process each outreach opportunity
    results = []
    for opportunity in opportunities:
        try:
            logger.info(
                f"Processing outreach for {opportunity.get('company', 'unknown')}"
            )
            outreach_result = process_outreach_flow(opportunity)
            results.append(outreach_result)

            # Send notification based on result
            if outreach_result.get("status") == "message_sent":
                notification_service.send_success_notification(
                    message=f"Successfully sent outreach to {outreach_result.get('contact_name', 'contact')} at {outreach_result.get('company', 'unknown')}",
                    context={
                        "opportunity_id": outreach_result.get("id", "unknown"),
                        "company": outreach_result.get("company", "unknown"),
                        "contact": outreach_result.get("contact_name", "unknown"),
                        "delivery_method": outreach_result.get(
                            "delivery_method", "unknown"
                        ),
                    },
                    pipeline_name="Job Outreach Pipeline",
                )
            elif outreach_result.get("status") in [
                "contact_not_found",
                "message_generation_failed",
                "send_failed",
            ]:
                notification_service.send_error_notification(
                    error_message=f"Failed to complete outreach for {outreach_result.get('company', 'unknown')}",
                    context={
                        "opportunity_id": outreach_result.get("id", "unknown"),
                        "company": outreach_result.get("company", "unknown"),
                        "status": outreach_result.get("status", "unknown"),
                        "error": outreach_result.get("error", "Unknown error"),
                    },
                    pipeline_name="Job Outreach Pipeline",
                )
        except Exception as e:
            logger.error(
                f"Error processing outreach for {opportunity.get('company', 'unknown')}: {str(e)}"
            )
            results.append(
                {
                    "id": opportunity.get("id", "unknown"),
                    "company": opportunity.get("company", "unknown"),
                    "status": "processing_failed",
                    "error": str(e),
                }
            )

            # Send error notification
            notification_service.send_error_notification(
                error_message=f"Error in job outreach flow for {opportunity.get('company', 'unknown')}: {str(e)}",
                context={
                    "opportunity_id": opportunity.get("id", "unknown"),
                    "company": opportunity.get("company", "unknown"),
                    "error_type": "FLOW_ERROR",
                },
                pipeline_name="Job Outreach Pipeline",
            )

    # Calculate statistics
    successful = sum(1 for r in results if r.get("status") == "message_sent")
    failed = len(results) - successful

    logger.info(
        f"Job outreach flow complete. Processed {len(results)} opportunities: {successful} successful, {failed} failed"
    )

    return {
        "status": "complete",
        "opportunities_processed": len(results),
        "successful": successful,
        "failed": failed,
        "results": results,
    }


if __name__ == "__main__":
    job_outreach_flow()
