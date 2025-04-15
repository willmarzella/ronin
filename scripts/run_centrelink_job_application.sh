#!/bin/bash

# Script to run the Centrelink job application pipeline

# Move to project root directory
cd "$(dirname "$0")/.." || exit

# Ensure virtual environment is active
if [[ "$VIRTUAL_ENV" == "" ]]; then
  echo "Activating virtual environment..."
  source venv/bin/activate || {
    echo "Failed to activate virtual environment. Make sure it exists."
    exit 1
  }
else
  echo "Already in virtual environment: $VIRTUAL_ENV"
fi

# Run the Centrelink job application pipeline
echo "Starting Centrelink job application pipeline..."
python -m flows.centrelink.centrelink_job_application

# Capture exit status
exit_status=$?

# Exit with the same status
echo "Pipeline exited with status: $exit_status"
exit $exit_status
