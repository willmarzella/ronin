import json
import logging
import os
import time
from typing import Any, Dict, Optional

import requests


class NotificationService:
    """Service for sending notifications to various platforms."""

    def __init__(self, config: Dict = None):
        """Initialize notification service with configuration.

        Args:
            config: Configuration dictionary with notification settings
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

        # Get Slack webhook URL from environment variable or config
        self.slack_webhook_url = os.environ.get(
            "SLACK_WEBHOOK_URL",
            self.config.get("notifications", {})
            .get("slack", {})
            .get("webhook_url", ""),
        )

        if not self.slack_webhook_url:
            self.logger.warning(
                "Slack webhook URL not configured. "
                "Set SLACK_WEBHOOK_URL environment variable or update config."
            )

    def send_slack_message(
        self,
        message: str,
        title: Optional[str] = None,
        color: str = "#36a64f",  # Default green for normal messages
        fields: Optional[Dict[str, Any]] = None,
        footer: Optional[str] = None,
        footer_icon: Optional[str] = None,
    ) -> bool:
        """Send a message to Slack.

        Args:
            message: The message to send
            title: Optional title for the message
            color: Color of the message sidebar (default: green)
            fields: Optional additional fields to include in the message
            footer: Optional footer text
            footer_icon: Optional footer icon URL

        Returns:
            bool: True if the message was sent successfully, False otherwise
        """
        if not self.slack_webhook_url:
            self.logger.error("Cannot send Slack message: webhook URL not configured")
            return False

        try:
            # Create a basic Slack message attachment
            attachment = {
                "color": color,
                "text": message,
                "mrkdwn_in": ["text", "fields"],
            }

            if title:
                attachment["title"] = title

            if fields:
                attachment["fields"] = [
                    {"title": key, "value": str(value), "short": True}
                    for key, value in fields.items()
                ]

            if footer:
                attachment["footer"] = footer

            if footer_icon:
                attachment["footer_icon"] = footer_icon

            # Add timestamp
            attachment["ts"] = int(time.time())

            payload = {"attachments": [attachment]}

            response = requests.post(
                self.slack_webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 200:
                self.logger.info("Slack notification sent successfully")
                return True
            else:
                self.logger.error(
                    f"Failed to send Slack notification. "
                    f"Status code: {response.status_code}, Response: {response.text}"
                )
                return False

        except Exception as e:
            self.logger.error(f"Error sending Slack notification: {str(e)}")
            return False

    def send_error_notification(
        self,
        error_message: str,
        context: Dict[str, Any] = None,
        pipeline_name: str = "Pipeline",
    ) -> bool:
        """Send an error notification to configured channels.

        Args:
            error_message: The error message
            context: Additional context about the error
            pipeline_name: Name of the pipeline generating the error

        Returns:
            bool: True if notifications were sent successfully
        """
        context = context or {}

        # Format additional information for the notification
        fields = {}

        # Add standard fields if they exist in context
        for key in ["platform", "jobs_processed", "jobs_errors", "error_type"]:
            if key in context:
                # Convert to title case for field names
                field_name = " ".join(word.capitalize() for word in key.split("_"))
                fields[field_name] = context[key]

        # Add any custom fields from context that aren't in the standard fields
        for key, value in context.items():
            if key not in [
                "platform",
                "jobs_processed",
                "jobs_errors",
                "error_type",
                "exception",
            ]:
                # Convert to title case for field names
                field_name = " ".join(word.capitalize() for word in key.split("_"))
                fields[field_name] = value

        # Add exception at the end if it exists
        if "exception" in context:
            fields["Exception"] = str(context["exception"])[:200]  # Limit length

        # Send to Slack
        title = f"🚨 Error in {pipeline_name}"
        return self.send_slack_message(
            message=error_message,
            title=title,
            color="#ff0000",  # Red for errors
            fields=fields,
            footer=f"{pipeline_name} | {os.environ.get('ENV', 'production')}",
        )

    def send_success_notification(
        self,
        message: str,
        context: Dict[str, Any] = None,
        pipeline_name: str = "Pipeline",
    ) -> bool:
        """Send a success notification to configured channels.

        Args:
            message: The success message
            context: Additional context about the success
            pipeline_name: Name of the pipeline reporting success

        Returns:
            bool: True if notifications were sent successfully
        """
        # Check if success notifications are enabled
        if (
            not self.config.get("notifications", {})
            .get("slack", {})
            .get("notify_on_success", False)
        ):
            self.logger.debug("Success notifications are disabled in config")
            return False

        context = context or {}

        # Format additional information for the notification
        fields = {}

        # Add any fields from context
        for key, value in context.items():
            if key != "exception":  # Skip exception field in success notifications
                # Convert to title case for field names
                field_name = " ".join(word.capitalize() for word in key.split("_"))
                fields[field_name] = value

        # Send to Slack
        title = f"✅ Success in {pipeline_name}"
        return self.send_slack_message(
            message=message,
            title=title,
            color="#36a64f",  # Green for success
            fields=fields,
            footer=f"{pipeline_name} | {os.environ.get('ENV', 'production')}",
        )

    def send_warning_notification(
        self,
        warning_message: str,
        context: Dict[str, Any] = None,
        pipeline_name: str = "Pipeline",
    ) -> bool:
        """Send a warning notification to configured channels.

        Args:
            warning_message: The warning message
            context: Additional context about the warning
            pipeline_name: Name of the pipeline reporting the warning

        Returns:
            bool: True if notifications were sent successfully
        """
        # Check if warning notifications are enabled
        if (
            not self.config.get("notifications", {})
            .get("slack", {})
            .get("notify_on_warning", True)
        ):
            self.logger.debug("Warning notifications are disabled in config")
            return False

        context = context or {}

        # Format additional information for the notification
        fields = {}

        # Add any fields from context
        for key, value in context.items():
            # Convert to title case for field names
            field_name = " ".join(word.capitalize() for word in key.split("_"))
            fields[field_name] = value

        # Send to Slack
        title = f"⚠️ Warning in {pipeline_name}"
        return self.send_slack_message(
            message=warning_message,
            title=title,
            color="#ffcc00",  # Yellow for warnings
            fields=fields,
            footer=f"{pipeline_name} | {os.environ.get('ENV', 'production')}",
        )
