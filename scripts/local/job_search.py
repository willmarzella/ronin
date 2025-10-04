#!/usr/bin/env python3
"""
🔍 Job Search Script
Simple script to search for jobs locally.
"""

import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import openai

from ronin.apps.job_automation.search.job_analyzer import JobAnalyzerService
from ronin.apps.job_automation.search.scrapers import SeekScraper
from ronin.core.config import load_config
from ronin.services.airtable_service import AirtableManager


def main():
    """Main job search function."""
    print("🔍 Starting job search...")

    try:
        # Load configuration
        config = load_config()
        print(f"📋 Loaded config for keywords: {config['search']['keywords']}")

        # Initialize OpenAI client
        openai_client = openai.OpenAI(api_key=config.get("openai", {}).get("api_key"))

        # Initialize job scraper, analyzer, and Airtable manager
        scraper = SeekScraper(config)
        analyzer = JobAnalyzerService(config, openai_client)
        airtable_manager = AirtableManager()
        print("✅ Job scraper, analyzer, and Airtable manager initialized")

        # Start job search
        print("🔍 Starting job search...")
        jobs = scraper.scrape_jobs()

        if jobs:
            print(f"✅ Found {len(jobs)} jobs!")
            print("\n📋 Job Summary:")
            for i, job in enumerate(jobs[:5], 1):  # Show first 5 jobs
                print(f"  {i}. {job.get('title', 'N/A')} - {job.get('company', 'N/A')}")
                print(f"     Location: {job.get('location', 'N/A')}")
                print(f"     Salary: {job.get('salary', 'N/A')}")
                print(f"     URL: {job.get('url', 'N/A')}")
                print()

            if len(jobs) > 5:
                print(f"  ... and {len(jobs) - 5} more jobs")

            # Analyze and add jobs to Airtable
            print("\n🤖 Analyzing jobs and adding to Airtable...")
            analyzed_jobs = []

            for i, job in enumerate(jobs, 1):
                print(f"📊 Analyzing job {i}/{len(jobs)}: {job.get('title', 'N/A')}")

                try:
                    # Analyze the job
                    analyzed_job = analyzer.analyze_job(job)

                    if analyzed_job:
                        analyzed_jobs.append(analyzed_job)
                        print(f"✅ Analyzed: {analyzed_job.get('title', 'N/A')}")
                    else:
                        print(f"❌ Failed to analyze: {job.get('title', 'N/A')}")

                except Exception as e:
                    print(f"❌ Error analyzing job {job.get('title', 'N/A')}: {e}")

            # Add analyzed jobs to Airtable
            if analyzed_jobs:
                print(f"\n💾 Adding {len(analyzed_jobs)} analyzed jobs to Airtable...")
                results = airtable_manager.batch_insert_jobs(analyzed_jobs)

                print(f"✅ Airtable Results:")
                print(f"  📝 New jobs added: {results['new_jobs']}")
                print(f"  🔄 Duplicates skipped: {results['duplicates']}")
                print(f"  ❌ Errors: {results['errors']}")
            else:
                print("ℹ️ No jobs were successfully analyzed")
        else:
            print("ℹ️ No jobs found matching your criteria")

        print("✅ Job search complete!")

    except Exception as e:
        print(f"❌ Error during job search: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
