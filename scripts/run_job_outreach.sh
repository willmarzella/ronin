#!/bin/bash

# ----------------------------------------------------------------
# LinkedIn Job Outreach Script
#
# This script runs the LinkedIn outreach DAG that:
# 1. Retrieves job listings from Airtable
# 2. Logs into LinkedIn
# 3. Finds relevant people (recruiters, talent, etc.) at companies with job listings
# 4. Sends connection requests or direct messages
# 5. Updates job statuses in Airtable
#
# Required environment variables (in .env file):
# - LINKEDIN_USERNAME: Your LinkedIn email/username
# - LINKEDIN_PASSWORD: Your LinkedIn password
# - OPENAI_API_KEY: API key for OpenAI (for message generation)
# - AIRTABLE_API_KEY: API key for Airtable
# ----------------------------------------------------------------

# Ensure script exits on any error
set -e

# Load environment variables from .env
if [ -f .env ]; then
  echo "Loading environment variables..."
  set -a
  source .env
  set +a
else
  echo "Error: .env file not found"
  exit 1
fi

# Check for required environment variables
if [ -z "$LINKEDIN_USERNAME" ] || [ -z "$LINKEDIN_PASSWORD" ]; then
  echo "Error: LinkedIn credentials not found in environment variables"
  echo "Please make sure LINKEDIN_USERNAME and LINKEDIN_PASSWORD are set in your .env file"
  exit 1
fi

if [ -z "$OPENAI_API_KEY" ]; then
  echo "Error: OpenAI API key not found in environment variables"
  echo "Please make sure OPENAI_API_KEY is set in your .env file"
  exit 1
fi

if [ -z "$AIRTABLE_API_KEY" ]; then
  echo "Error: Airtable API key not found in environment variables"
  echo "Please make sure AIRTABLE_API_KEY is set in your .env file"
  exit 1
fi

# Setup virtual environment
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
else
  echo "Using existing virtual environment..."
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "Installing/updating dependencies..."
pip install -r requirements.txt

# Check if ChromeDriver is installed and in PATH
if ! command -v chromedriver &>/dev/null; then
  echo "Warning: ChromeDriver not found in PATH"
  echo "The script may install it automatically, but if you encounter issues,"
  echo "please install ChromeDriver manually: https://chromedriver.chromium.org/downloads"
fi

# Run the LinkedIn outreach DAG
echo "Starting LinkedIn outreach process..."
python -B dags/job_outreach_dag.py

# Deactivate virtual environment
deactivate

echo "LinkedIn outreach process complete!"
