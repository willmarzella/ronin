.PHONY: help install search blog apply centrelink outreach clean setup generate-outreach

# Default target
help:
	@echo "Available commands:"
	@echo "  make install    - Install dependencies"
	@echo "  make search     - Run job search"
	@echo "  make blog       - Generate blog posts"
	@echo "  make apply      - Run job application"
	@echo "  make centrelink - Run centrelink job application"
	@echo "  make outreach   - Run job outreach"
	@echo "  make generate-outreach - Generate recruiter outreach content"
	@echo "  make clean      - Clean up temporary files"
	@echo "  make setup      - Initial project setup"

# Install Python dependencies
install:
	@echo "Installing dependencies..."
	@if [ ! -d "venv" ]; then python3 -m venv venv; fi
	@source venv/bin/activate && pip install -r requirements.txt

# Job search automation
search:
	@echo "Running job search..."
	@source venv/bin/activate && python -B dags/job_search_dag.py

# Blog post generation
blog:
	@echo "Generating blog posts..."
	@source venv/bin/activate && python -B dags/blog_generator_dag.py

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

# Generate recruiter outreach content
generate-outreach:
	@echo "Generating recruiter outreach content..."
	@source venv/bin/activate && python -c "from services.outreach_generator import OutreachGenerator; from services.airtable_service import AirtableManager; from services.ai_service import AIService; generator = OutreachGenerator(AirtableManager(), AIService()); print('Generated:', generator.process_jobs_for_outreach())"

# Initial project setup
setup:
	@echo "Setting up project..."
	./scripts/setup.sh