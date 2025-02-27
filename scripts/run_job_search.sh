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

# Only setup virtual environment and install dependencies if not running in GitHub Actions
if [ -z "$GITHUB_ACTIONS" ]; then
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
else
  echo "Running in GitHub Actions - skipping local environment setup..."
fi

# Run the scraping
python -B dags/job_search_dag.py

# Deactivate virtual environment if we created one
if [ -z "$GITHUB_ACTIONS" ]; then
  deactivate
fi
