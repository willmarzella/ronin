.PHONY: help install search blog apply centrelink outreach clean setup

# Default target
help:
	@echo "Available commands:"
	@echo "  make install    - Install dependencies"
	@echo "  make search     - Run job search"
	@echo "  make blog       - Generate blog posts"
	@echo "  make apply      - Run job application"
	@echo "  make centrelink - Run centrelink job application"
	@echo "  make outreach   - Run job outreach"
	@echo "  make clean      - Clean up temporary files"
	@echo "  make setup      - Initial project setup"

# Install Python dependencies
install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt

# Job search automation
search:
	@echo "Running job search..."
	python -B dags/job_search_dag.py

# Blog post generation
blog:
	@echo "Generating blog posts..."
	python -B dags/blog_generator_dag.py

# Job application automation
apply:
	@echo "Running job application..."
	./scripts/run_job_application.sh

# Centrelink job application
centrelink:
	@echo "Running centrelink job application..."
	./scripts/run_centrelink_job_application.sh

# Job outreach automation
outreach:
	@echo "Running job outreach..."
	./scripts/run_job_outreach.sh

# Clean up temporary files
clean:
	@echo "Cleaning up..."
	./scripts/clean.sh

# Initial project setup
setup:
	@echo "Setting up project..."
	./scripts/setup.sh