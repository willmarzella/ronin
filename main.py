#!/usr/bin/env python3
"""
🐒 Ronin - AI-Powered Job Automation Platform
Simple local scripts for job automation, blog generation, and book scraping.
"""

import argparse
import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ronin.apps.blog_generation.generation import BlogGenerator
from ronin.apps.book_scraping.actualized_scraper import ActualizedScraper
from ronin.apps.job_automation.application.appliers import SeekApplier
from ronin.apps.job_automation.search.scrapers import JobScraper


def job_search():
    """Search for jobs."""
    print("🔍 Starting job search...")
    scraper = JobScraper()
    # Add your job search logic here
    print("✅ Job search complete!")


def job_apply():
    """Apply to jobs."""
    print("📝 Starting job applications...")
    applier = SeekApplier()
    # Add your job application logic here
    print("✅ Job applications complete!")


def blog_generate():
    """Generate blog posts."""
    print("✍️ Starting blog generation...")
    generator = BlogGenerator()
    # Add your blog generation logic here
    print("✅ Blog generation complete!")


def book_scrape():
    """Scrape book content."""
    print("📚 Starting book scraping...")
    scraper = ActualizedScraper()
    # Add your book scraping logic here
    print("✅ Book scraping complete!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="🐒 Ronin - AI-Powered Job Automation Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py job-search     # Search for jobs
  python main.py job-apply      # Apply to jobs
  python main.py blog           # Generate blog posts
  python main.py book           # Scrape book content
  python main.py all            # Run everything
        """,
    )

    parser.add_argument(
        "command",
        choices=["job-search", "job-apply", "blog", "book", "all"],
        help="Command to run",
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to config file (optional)",
    )

    args = parser.parse_args()

    print("🐒 Ronin - AI-Powered Job Automation Platform")
    print("=" * 50)

    try:
        if args.command == "job-search":
            job_search()
        elif args.command == "job-apply":
            job_apply()
        elif args.command == "blog":
            blog_generate()
        elif args.command == "book":
            book_scrape()
        elif args.command == "all":
            print("🚀 Running all automation tasks...")
            job_search()
            job_apply()
            blog_generate()
            book_scrape()
            print("🎉 All tasks complete!")

    except KeyboardInterrupt:
        print("\n⏹️ Stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
