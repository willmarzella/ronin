#!/bin/bash

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

# Check if virtual environment exists, create if it doesn't
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "Installing/updating dependencies..."
pip install -r requirements.txt

# Set GitHub Actions environment variable to ensure only scraping runs
export GITHUB_ACTIONS=true

# Run the scraping
python -B dags/job_search_dag.py

# Deactivate virtual environment
deactivate
