#!/usr/bin/env python3
"""Test script for Slack notifications."""

import os
import sys
import time

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
            "Please set SLACK_WEBHOOK_URL environment variable or update the "
            "webhook_url in configs/config.yaml"
        )
        return False

    # Get the pipeline to test from command-line arguments or use default
    pipeline_name = "Test Pipeline"
    if len(sys.argv) > 1:
        pipeline_name = sys.argv[1]
        print(f"Testing notifications for pipeline: {pipeline_name}")

    # Get notification type to test from command-line arguments or test all
    notification_type = "all"
    if len(sys.argv) > 2:
        notification_type = sys.argv[2].lower()
        print(f"Testing notification type: {notification_type}")

    success = True
    test_time = time.strftime("%Y-%m-%d %H:%M:%S")

    # Test success notification
    if notification_type in ["all", "success"]:
        result = notification_service.send_success_notification(
            message=f"This is a test SUCCESS notification from the {pipeline_name}",
            context={
                "Environment": os.environ.get("ENV", "development"),
                "Test Time": test_time,
                "Sample Data": "123",
            },
            pipeline_name=pipeline_name,
        )

        if result:
            print(f"✅ Success notification sent successfully for {pipeline_name}")
        else:
            print(f"❌ Failed to send success notification for {pipeline_name}")
            success = False

    # Test warning notification
    if notification_type in ["all", "warning"]:
        result = notification_service.send_warning_notification(
            warning_message=f"This is a test WARNING notification from the "
            f"{pipeline_name}",
            context={
                "Environment": os.environ.get("ENV", "development"),
                "Test Time": test_time,
                "Warning Level": "Medium",
            },
            pipeline_name=pipeline_name,
        )

        if result:
            print(f"✅ Warning notification sent successfully for {pipeline_name}")
        else:
            print(f"❌ Failed to send warning notification for {pipeline_name}")
            success = False

    # Test error notification
    if notification_type in ["all", "error"]:
        result = notification_service.send_error_notification(
            error_message=f"This is a test ERROR notification from the {pipeline_name}",
            context={
                "Environment": os.environ.get("ENV", "development"),
                "Test Time": test_time,
                "Error Code": "TEST-123",
                "exception": Exception("This is a test exception"),
            },
            pipeline_name=pipeline_name,
        )

        if result:
            print(f"✅ Error notification sent successfully for {pipeline_name}")
        else:
            print(f"❌ Failed to send error notification for {pipeline_name}")
            success = False

    if success:
        print("\n✅ All test notifications sent successfully!")
    else:
        print("\n❌ Some notifications failed to send.")

    print("\nUsage:")
    print("  python test_slack_notification.py [pipeline_name] [notification_type]")
    print("    pipeline_name: Name of the pipeline to test notifications for")
    print(
        "    notification_type: Type of notification to test "
        "(success, warning, error, all)"
    )
    print("\nExample:")
    print("  python test_slack_notification.py 'Job Search Pipeline' error")

    return success


if __name__ == "__main__":
    success = test_slack_notification()
    sys.exit(0 if success else 1)
