#!/usr/bin/env python
"""
Script to register and set up Prefect blocks for the Ronin project.
This script sets up secrets, storage, and notifications blocks.
"""

import os
from pathlib import Path
import sys
import yaml
from typing import Dict, Any

# Add the parent directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from prefect.blocks.system import Secret
from prefect.blocks.notifications import SlackWebhook
from prefect_aws.s3 import S3Bucket
from prefect_aws.credentials import AwsCredentials
from prefect.filesystems import LocalFileSystem

from dotenv import load_dotenv


def load_config() -> Dict[str, Any]:
    """Load configuration from YAML file."""
    config_path = Path(__file__).parent.parent / "configs" / "config.yaml"
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {str(e)}")
        return {}


def create_secret_blocks():
    """Create secret blocks from environment variables."""
    # Load environment variables from .env file
    load_dotenv()

    # Create OpenAI API Key secret block
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        Secret(value=openai_api_key).save(name="openai-api-key", overwrite=True)
        print("✅ Created OpenAI API Key secret block")
    else:
        print("❌ Missing OPENAI_API_KEY environment variable")

    # Create Airtable API Key secret block
    airtable_api_key = os.environ.get("AIRTABLE_API_KEY")
    if airtable_api_key:
        Secret(value=airtable_api_key).save(name="airtable-api-key", overwrite=True)
        print("✅ Created Airtable API Key secret block")
    else:
        print("❌ Missing AIRTABLE_API_KEY environment variable")


def create_storage_blocks():
    """Create storage blocks for flow code and data."""
    # Create local storage block for development
    local_storage = LocalFileSystem(basepath=str(Path(__file__).parent.parent))
    local_storage.save(name="local-file-system", overwrite=True)
    print("✅ Created local file system block")

    # Create S3 storage block if credentials are available
    aws_access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

    if aws_access_key_id and aws_secret_access_key:
        aws_creds = AwsCredentials(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        aws_creds.save(name="aws-credentials", overwrite=True)
        print("✅ Created AWS credentials block")

        # Create S3 bucket block
        s3_bucket_name = os.environ.get("S3_BUCKET_NAME", "ronin-prefect")
        s3_bucket = S3Bucket(
            bucket_name=s3_bucket_name,
            credentials=aws_creds,
        )
        s3_bucket.save(name="s3-bucket", overwrite=True)
        print(f"✅ Created S3 bucket block for {s3_bucket_name}")
    else:
        print("❌ Missing AWS credentials")


def create_notification_blocks():
    """Create notification blocks for alerts and monitoring."""
    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if slack_webhook_url:
        slack_webhook = SlackWebhook(url=slack_webhook_url)
        slack_webhook.save(name="slack-notifications", overwrite=True)
        print("✅ Created Slack webhook notification block")
    else:
        print("❌ Missing SLACK_WEBHOOK_URL environment variable")


def main():
    """Run the block creation functions."""
    print("Setting up Prefect blocks for Ronin project...")

    create_secret_blocks()
    create_storage_blocks()
    create_notification_blocks()

    print("\nPrefect blocks setup complete!")


if __name__ == "__main__":
    main()
