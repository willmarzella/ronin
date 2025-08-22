#!/bin/bash

# Script to run the Centrelink job application pipeline

# Move to project root directory
cd "$(dirname "$0")/.." || exit

# Ensure virtual environment exists and is active
if [[ "$VIRTUAL_ENV" == "" ]]; then
  if [[ ! -d "venv" ]]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv || {
      echo "Failed to create virtual environment."
      exit 1
    }
    echo "Virtual environment created successfully."
  fi

  echo "Activating virtual environment..."
  source venv/bin/activate || {
    echo "Failed to activate virtual environment."
    exit 1
  }

  # Install requirements if requirements.txt exists
  if [[ -f "requirements.txt" ]]; then
    echo "Installing requirements..."
    pip install -r requirements.txt || {
      echo "Failed to install requirements."
      exit 1
    }
  fi
else
  echo "Already in virtual environment: $VIRTUAL_ENV"
fi

# Default values
MAX_JOBS=100
SAVE_TO_AIRTABLE=""
SEARCH_TERMS=""

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
  --max-jobs)
    MAX_JOBS="$2"
    shift 2
    ;;
  --save-to-airtable)
    SAVE_TO_AIRTABLE="--save-to-airtable"
    shift
    ;;
  --search)
    shift
    # Collect search terms until the next flag
    SEARCH_TERMS=""
    while [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; do
      SEARCH_TERMS="$SEARCH_TERMS \"$1\""
      shift
    done
    ;;
  *)
    echo "Unknown option: $1"
    exit 1
    ;;
  esac
done

# Build the command
CMD="python -m flows.centrelink.centrelink_job_application --max-jobs $MAX_JOBS $SAVE_TO_AIRTABLE"

# Add search terms if provided
if [[ -n "$SEARCH_TERMS" ]]; then
  CMD="$CMD --search $SEARCH_TERMS"
fi

# Run the Centrelink job application pipeline
echo "Starting Centrelink job application pipeline..."
echo "Running: $CMD"
eval $CMD

# Capture exit status
exit_status=$?

# Exit with the same status
echo "Pipeline exited with status: $exit_status"
exit $exit_status
