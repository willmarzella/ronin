"""Message generation and sending functionality for LinkedIn outreach."""

import logging
import json
from typing import Dict, Any, Tuple, Optional

from services.ai_service import AIService
from tasks.job_outreach import prompts


class LinkedInMessageGenerator:
    """Class to generate and manage LinkedIn outreach messages."""

    def __init__(self):
        """Initialize LinkedIn message generator."""
        self.logger = logging.getLogger(__name__)
        self.ai_service = AIService()

    def generate_connection_request(
        self,
        person_name: str,
        person_title: str,
        company_name: str,
        job_title: str,
    ) -> Tuple[bool, str]:
        """
        Generate a LinkedIn connection request note using OpenAI.

        Args:
            person_name: Name of the person to connect with
            person_title: Title of the person
            company_name: Company name
            job_title: Job title of the position you're interested in

        Returns:
            Tuple of (success, message)
        """
        try:
            self.logger.info(
                f"Generating connection request for {person_name} at {company_name}"
            )

            system_prompt = prompts.CONNECTION_REQUEST_PROMPT_SYSTEM
            user_prompt = prompts.get_connection_request_user_prompt(
                person_name=person_name,
                person_title=person_title,
                company_name=company_name,
                job_title=job_title,
            )

            response = self.ai_service.chat_completion(
                system_prompt=system_prompt, user_message=user_prompt, temperature=0.7
            )

            if not response:
                self.logger.error("Failed to generate connection request")
                return False, ""

            try:
                # Extract the message from the response JSON
                message = response.get("message", "")
                if not message:
                    self.logger.warning("AI generated empty connection request")
                    return False, ""

                # Check if message is within LinkedIn's character limit
                if len(message) > 300:
                    self.logger.warning(
                        f"Connection request too long ({len(message)} chars), truncating"
                    )
                    message = message[:297] + "..."

                self.logger.info(f"Generated connection request: {message[:50]}...")
                return True, message
            except Exception as e:
                self.logger.error(
                    f"Error parsing connection request response: {str(e)}"
                )
                return False, ""

        except Exception as e:
            self.logger.error(f"Error generating connection request: {str(e)}")
            return False, ""

    def generate_direct_message(
        self,
        person_name: str,
        person_title: str,
        company_name: str,
        job_title: str,
    ) -> Tuple[bool, str]:
        """
        Generate a LinkedIn direct message using OpenAI.

        Args:
            person_name: Name of the person to message
            person_title: Title of the person
            company_name: Company name
            job_title: Job title of the position you're interested in

        Returns:
            Tuple of (success, message)
        """
        try:
            self.logger.info(
                f"Generating direct message for {person_name} at {company_name}"
            )

            system_prompt = prompts.DIRECT_MESSAGE_PROMPT_SYSTEM
            user_prompt = prompts.get_direct_message_user_prompt(
                person_name=person_name,
                person_title=person_title,
                company_name=company_name,
                job_title=job_title,
            )

            response = self.ai_service.chat_completion(
                system_prompt=system_prompt, user_message=user_prompt, temperature=0.7
            )

            if not response:
                self.logger.error("Failed to generate direct message")
                return False, ""

            try:
                # Extract the message from the response JSON
                message = response.get("message", "")
                if not message:
                    self.logger.warning("AI generated empty direct message")
                    return False, ""

                self.logger.info(f"Generated direct message: {message[:50]}...")
                return True, message
            except Exception as e:
                self.logger.error(f"Error parsing direct message response: {str(e)}")
                return False, ""

        except Exception as e:
            self.logger.error(f"Error generating direct message: {str(e)}")
            return False, ""


class OutreachTracker:
    """Class to track outreach attempts and results."""

    def __init__(self):
        """Initialize outreach tracker."""
        self.logger = logging.getLogger(__name__)
        self.outreach_stats = {
            "total_profiles_visited": 0,
            "connection_requests_sent": 0,
            "direct_messages_sent": 0,
            "failed_attempts": 0,
        }
        self.contacted_profiles = set()

    def record_profile_visit(self, profile_url: str) -> None:
        """Record a profile visit."""
        self.outreach_stats["total_profiles_visited"] += 1
        self.logger.info(f"Visited profile: {profile_url}")

    def record_connection_request(
        self, profile_url: str, person_name: str, success: bool
    ) -> None:
        """Record a connection request attempt."""
        if success:
            self.outreach_stats["connection_requests_sent"] += 1
            self.contacted_profiles.add(profile_url)
            self.logger.info(f"Connection request sent to: {person_name}")
        else:
            self.outreach_stats["failed_attempts"] += 1
            self.logger.warning(f"Failed to send connection request to: {person_name}")

    def record_direct_message(
        self, profile_url: str, person_name: str, success: bool
    ) -> None:
        """Record a direct message attempt."""
        if success:
            self.outreach_stats["direct_messages_sent"] += 1
            self.contacted_profiles.add(profile_url)
            self.logger.info(f"Direct message sent to: {person_name}")
        else:
            self.outreach_stats["failed_attempts"] += 1
            self.logger.warning(f"Failed to send direct message to: {person_name}")

    def was_contacted(self, profile_url: str) -> bool:
        """Check if a profile was previously contacted."""
        return profile_url in self.contacted_profiles

    def get_stats(self) -> Dict[str, Any]:
        """Get current outreach statistics."""
        return self.outreach_stats
