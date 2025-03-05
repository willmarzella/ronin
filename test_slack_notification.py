#!/usr/bin/env python3
"""Test script for Slack notifications."""

import os
import sys
import yaml
from services.notification_service import NotificationService


def test_slack_notification():
    """Test the Slack notification service."""
    print("Testing Slack notification service...")

    # Load configuration
    config_path = os.path.join(os.path.dirname(__file__), "configs", "config.yaml")
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {str(e)}")
        config = {}

    # Initialize notification service
    notification_service = NotificationService(config)

    # Check if webhook URL is configured
    if not notification_service.slack_webhook_url:
        print("Slack webhook URL is not configured.")
        print(
            "Please set SLACK_WEBHOOK_URL environment variable or update the webhook_url in configs/config.yaml"
        )
        return False

    # Send a test notification
    result = notification_service.send_slack_message(
        message="This is a test notification from the Job Search Pipeline",
        title="🧪 Test Notification",
        color="#36a64f",  # Green color for test
        fields={
            "Environment": os.environ.get("ENV", "development"),
            "Test Time": "Now",
        },
    )

    if result:
        print("✅ Test notification sent successfully!")
    else:
        print("❌ Failed to send test notification.")

    return result


if __name__ == "__main__":
    success = test_slack_notification()
    sys.exit(0 if success else 1)
