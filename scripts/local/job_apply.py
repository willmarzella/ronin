#!/usr/bin/env python3
"""
📝 Job Application Script
Simple script to apply to jobs locally.
"""

import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ronin.apps.job_automation.application.appliers import SeekApplier
from ronin.apps.job_automation.search.scrapers import SeekScraper
from ronin.core.config import load_config


def main():
    """Main job application function."""
    print("📝 Starting job applications...")

    try:
        # Load configuration
        config = load_config()
        print(f"📋 Loaded config for keywords: {config['search']['keywords']}")

        # Initialize job scraper and applier
        scraper = SeekScraper(config)
        applier = SeekApplier()
        print("✅ Job scraper and applier initialized")

        # First, search for jobs
        print("🔍 Searching for jobs to apply to...")
        jobs = scraper.scrape_jobs()

        if not jobs:
            print("ℹ️ No jobs found to apply to")
            return

        print(f"📋 Found {len(jobs)} jobs. Starting applications...")

        # Apply to first few jobs (limit to avoid overwhelming)
        max_applications = min(3, len(jobs))
        successful_applications = 0

        for i, job in enumerate(jobs[:max_applications], 1):
            print(
                f"\n📝 Applying to job {i}/{max_applications}: {job.get('title', 'N/A')}"
            )
            print(f"   Company: {job.get('company', 'N/A')}")

            try:
                # Extract job details for application
                job_id = job.get("id", "")
                job_description = job.get("description", "")
                company_name = job.get("company", "")
                title = job.get("title", "")

                # Apply to the job
                result = applier.apply_to_job(
                    job_id=job_id,
                    job_description=job_description,
                    score=0,  # Default score
                    tech_stack=[],  # Default tech stack
                    company_name=company_name,
                    title=title,
                )

                if result:
                    print(f"✅ Successfully applied to {title} at {company_name}")
                    successful_applications += 1
                else:
                    print(f"❌ Failed to apply to {title} at {company_name}")

            except Exception as e:
                print(f"❌ Error applying to {job.get('title', 'N/A')}: {e}")

        print(f"\n🎉 Application process complete!")
        print(
            f"✅ Successfully applied to {successful_applications}/{max_applications} jobs"
        )

    except Exception as e:
        print(f"❌ Error during job applications: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
