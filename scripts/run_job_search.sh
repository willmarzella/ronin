#!/bin/bash

# Exit on any error
set -e

# Load .env if it exists
[ -f .env ] && source .env

# Clean up any existing venv
rm -rf venv

# Create fresh venv
echo "Creating fresh virtual environment..."
python3 -m venv venv

# Activate and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

# Run the job search
echo "Running job search..."
python -B dags/job_search_dag.py

# Clean up
echo "Cleaning up..."
deactivate
rm -rf venv
