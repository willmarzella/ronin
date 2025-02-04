#!/bin/bash

# Ensure script exits on any error
set -e

# Load environment variables from .env
if [ -f .env ]; then
  echo "Loading environment variables..."
  export $(cat .env | grep -v '^#' | xargs)
else
  echo "Error: .env file not found"
  exit 1
fi

# Check if Chrome is running
if pgrep "Google Chrome" >/dev/null; then
  echo "Please close all Chrome windows before running this script."
  echo "This is required to properly control Chrome for automation."
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

# Run the application in apply-only mode
echo "Starting job application process..."
python -c "
from app.services.job_applier import JobApplierService
applier = JobApplierService()
applier.process_pending_jobs()
"

# Deactivate virtual environment
deactivate
