.PHONY: help install search blog apply centrelink outreach clean setup generate-outreach format lint check pre-commit-install pre-commit-run

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
	@echo "  make format     - Format code with Black"
	@echo "  make lint       - Lint code with Flake8"
	@echo "  make check      - Run both formatting and linting"
	@echo "  make pre-commit-install - Install pre-commit hooks"
	@echo "  make pre-commit-run     - Run pre-commit on all files"
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

# Format code with Black
format:
	@echo "Formatting code with Black..."
	@source venv/bin/activate && black --line-length 88 --target-version py311 .

# Lint code with Flake8
lint:
	@echo "Linting code with Flake8..."
	@source venv/bin/activate && flake8 --max-line-length 88 --extend-ignore E203,W503 .

# Run both formatting and linting
check:
	@echo "Running code quality checks..."
	@$(MAKE) format
	@$(MAKE) lint
	@echo "✅ Code quality checks completed!"

# Install pre-commit hooks
pre-commit-install:
	@echo "Installing pre-commit hooks..."
	@source venv/bin/activate && pre-commit install
	@echo "✅ Pre-commit hooks installed!"

# Run pre-commit on all files
pre-commit-run:
	@echo "Running pre-commit on all files..."
	@source venv/bin/activate && pre-commit run --all-files

# Initial project setup
setup:
	@echo "Setting up project..."
	./scripts/setup.sh
