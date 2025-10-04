.PHONY: help install search apply blog book all format lint check clean setup test

# 🐒 Ronin - AI-Powered Job Automation Platform
# Simple Makefile for local development

# Default target
help:
	@echo "🐒 Ronin - AI-Powered Job Automation Platform"
	@echo "=============================================="
	@echo ""
	@echo "Available commands:"
	@echo "  make install    - Install dependencies"
	@echo "  make setup      - Initial project setup"
	@echo ""
	@echo "🚀 Automation Commands:"
	@echo "  make search     - Search for jobs"
	@echo "  make apply      - Apply to jobs"
	@echo "  make blog       - Generate blog posts"
	@echo "  make book       - Scrape book content"
	@echo "  make all        - Run all automation tasks"
	@echo ""
	@echo "🛠️ Development Commands:"
	@echo "  make format     - Format code with Black"
	@echo "  make lint       - Lint code with Flake8"
	@echo "  make check      - Run both formatting and linting"
	@echo "  make test       - Test the new structure"
	@echo "  make clean      - Clean up temporary files"
	@echo ""
	@echo "📖 Usage Examples:"
	@echo "  make search     # Search for jobs"
	@echo "  make apply      # Apply to jobs"
	@echo "  make all        # Run everything"

# Install Python dependencies
install:
	@echo "📦 Installing dependencies..."
	@if [ ! -d "venv" ]; then python3 -m venv venv; fi
	@source venv/bin/activate && pip install -r requirements.txt
	@echo "✅ Dependencies installed!"

# Initial project setup
setup:
	@echo "🚀 Setting up Ronin..."
	@$(MAKE) install
	@echo "✅ Setup complete!"
	@echo ""
	@echo "🐒 Ready to automate! Try:"
	@echo "  make search     # Search for jobs"
	@echo "  make apply      # Apply to jobs"
	@echo "  make blog       # Generate blog posts"

# Job search automation
search:
	@echo "🔍 Searching for jobs..."
	@source venv/bin/activate && PYTHONPATH=src python scripts/local/job_search.py
	@echo "✅ Job search complete!"

# Job application automation
apply:
	@echo "📝 Applying to jobs..."
	@source venv/bin/activate && PYTHONPATH=src python scripts/local/job_apply.py
	@echo "✅ Job applications complete!"

# Blog post generation
blog:
	@echo "✍️ Generating blog posts..."
	@source venv/bin/activate && PYTHONPATH=src python scripts/local/blog_generate.py
	@echo "✅ Blog generation complete!"

# Book scraping
book:
	@echo "📚 Scraping book content..."
	@source venv/bin/activate && PYTHONPATH=src python scripts/local/book_scrape.py
	@echo "✅ Book scraping complete!"

# Run all automation tasks
all:
	@echo "🚀 Running all automation tasks..."
	@$(MAKE) search
	@$(MAKE) apply
	@$(MAKE) blog
	@$(MAKE) book
	@echo "🎉 All automation tasks complete!"

# Test the new structure
test:
	@echo "🧪 Testing new structure..."
	@source venv/bin/activate && PYTHONPATH=src python -c "import ronin; from ronin.core.config import load_config; from ronin.services.ai_service import AIService; print('✅ All imports successful!')"
	@echo "✅ Structure test complete!"

# Format code with Black
format:
	@echo "🎨 Formatting code with Black..."
	@source venv/bin/activate && black --line-length 88 --target-version py311 src/
	@echo "✅ Code formatted!"

# Lint code with Flake8
lint:
	@echo "🔍 Linting code with Flake8..."
	@source venv/bin/activate && flake8 --max-line-length 88 --extend-ignore E203,W503 src/
	@echo "✅ Code linted!"

# Run both formatting and linting
check:
	@echo "🛠️ Running code quality checks..."
	@$(MAKE) format
	@$(MAKE) lint
	@echo "✅ Code quality checks completed!"

# Clean up temporary files
clean:
	@echo "🧹 Cleaning up..."
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -delete
	@find . -type f -name "*.log" -delete
	@echo "✅ Cleanup complete!"
