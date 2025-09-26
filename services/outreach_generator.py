"""Service for generating recruiter outreach content and markdown files."""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from services.airtable_service import AirtableManager
from services.recruiter_service import RecruiterOutreachService
from services.ai_service import AIService


class OutreachGenerator:
    """Generate outreach content and markdown files for recruiters."""

    def __init__(self, airtable: AirtableManager, ai_service: AIService):
        """Initialize the outreach generator."""
        self.airtable = airtable
        self.outreach_service = RecruiterOutreachService(ai_service)
        self.logger = logging.getLogger(__name__)

        # Create outreach directory if it doesn't exist
        self.outreach_dir = "outreach"
        os.makedirs(self.outreach_dir, exist_ok=True)

    def get_jobs_with_recruiters(self, status: str = "DISCOVERED") -> List[Dict]:
        """
        Get jobs that have linked recruiters and match the specified status.

        Args:
            status: Job status to filter by

        Returns:
            List of jobs with recruiter information
        """
        try:
            # Get jobs with the specified status that have recruiter links
            formula = f"AND({{Status}} = '{status}', {{Recruiter}} != BLANK())"
            job_records = self.airtable.table.all(formula=formula)

            jobs_with_recruiters = []
            for record in job_records:
                fields = record["fields"]

                # Get recruiter information
                recruiter_links = fields.get("Recruiter", [])
                if not recruiter_links:
                    continue

                # Get the first linked recruiter
                recruiter_id = recruiter_links[0]
                try:
                    recruiter_record = self.airtable.people_table.get(recruiter_id)
                    recruiter_fields = recruiter_record["fields"]

                    job_data = {
                        "job_id": fields.get("Job ID", ""),
                        "title": fields.get("Title", ""),
                        "company": fields.get("Company Name", ""),
                        "description": fields.get("Description", ""),
                        "score": fields.get("Score", 0),
                        "tech_stack": fields.get("Tech Stack", ""),
                        "url": fields.get("URL", ""),
                        "recruiter": {
                            "id": recruiter_id,
                            "name": recruiter_fields.get("Name", ""),
                            "email": recruiter_fields.get("Email", ""),
                            "phone": recruiter_fields.get("Phone", ""),
                            "role": recruiter_fields.get("Role", ""),
                            "company": recruiter_fields.get("Company Name", ""),
                        },
                    }

                    jobs_with_recruiters.append(job_data)

                except Exception as e:
                    self.logger.error(
                        f"Error getting recruiter details for ID {recruiter_id}: {str(e)}"
                    )
                    continue

            self.logger.info(f"Found {len(jobs_with_recruiters)} jobs with recruiters")
            return jobs_with_recruiters

        except Exception as e:
            self.logger.error(f"Error getting jobs with recruiters: {str(e)}")
            return []

    def generate_outreach_content(self, job: Dict) -> Dict:
        """
        Generate email and text outreach content for a job's recruiter.

        Args:
            job: Job data with recruiter information

        Returns:
            Dict with email and text content
        """
        try:
            recruiter = job["recruiter"]

            # Generate email content
            email_content = self.outreach_service.generate_email_content(recruiter, job)

            # Generate text content if phone number is available
            text_content = None
            if recruiter.get("phone"):
                text_content = self.outreach_service.generate_text_content(
                    recruiter, job
                )

            return {
                "email": email_content,
                "text": text_content,
                "has_phone": bool(recruiter.get("phone")),
                "has_email": bool(recruiter.get("email")),
            }

        except Exception as e:
            self.logger.error(
                f"Error generating outreach content for job {job.get('title', 'Unknown')}: {str(e)}"
            )
            return {
                "email": {
                    "subject": "Error generating content",
                    "body": "Please generate manually",
                },
                "text": None,
                "has_phone": False,
                "has_email": False,
            }

    def generate_outreach_markdown(self, jobs_with_outreach: List[Dict]) -> str:
        """
        Generate a markdown file with all outreach content.

        Args:
            jobs_with_outreach: List of jobs with generated outreach content

        Returns:
            Path to the generated markdown file
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"recruiter_outreach_{timestamp}.md"
        filepath = os.path.join(self.outreach_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(
                    f"# Recruiter Outreach - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                )
                f.write(
                    f"Generated outreach content for {len(jobs_with_outreach)} jobs with recruiters.\n\n"
                )
                f.write("---\n\n")

                for i, job in enumerate(jobs_with_outreach, 1):
                    recruiter = job["recruiter"]
                    outreach = job["outreach"]

                    f.write(f"## {i}. {job['title']} at {job['company']}\n\n")

                    # Job details
                    f.write("### Job Details\n")
                    f.write(f"- **Job ID**: {job['job_id']}\n")
                    f.write(f"- **Score**: {job['score']}/100\n")
                    f.write(f"- **Tech Stack**: {job['tech_stack']}\n")
                    f.write(f"- **URL**: {job['url']}\n\n")

                    # Recruiter details
                    f.write("### Recruiter Information\n")
                    f.write(f"- **Name**: {recruiter['name']}\n")
                    if recruiter.get("email"):
                        f.write(f"- **Email**: {recruiter['email']}\n")
                    if recruiter.get("phone"):
                        f.write(f"- **Phone**: {recruiter['phone']}\n")
                    if recruiter.get("role"):
                        f.write(f"- **Role**: {recruiter['role']}\n")
                    f.write("\n")

                    # Email content
                    if outreach["has_email"] and outreach["email"]:
                        f.write("### 📧 Email Outreach\n")
                        f.write(f"**Subject**: {outreach['email']['subject']}\n\n")
                        f.write("**Body**:\n")
                        f.write("```\n")
                        f.write(outreach["email"]["body"])
                        f.write("\n```\n\n")

                    # Text message content
                    if outreach["has_phone"] and outreach["text"]:
                        f.write("### 📱 Text Message\n")
                        f.write("```\n")
                        f.write(outreach["text"])
                        f.write("\n```\n\n")

                    # Action items
                    f.write("### ✅ Action Items\n")
                    if outreach["has_email"]:
                        f.write("- [ ] Send email to recruiter\n")
                    if outreach["has_phone"]:
                        f.write("- [ ] Send text message to recruiter\n")
                    f.write("- [ ] Follow up in 3-5 business days\n")
                    f.write("- [ ] Update job status in Airtable after contact\n\n")

                    f.write("---\n\n")

                # Summary section
                f.write("## 📊 Summary\n\n")
                email_count = sum(
                    1 for job in jobs_with_outreach if job["outreach"]["has_email"]
                )
                text_count = sum(
                    1 for job in jobs_with_outreach if job["outreach"]["has_phone"]
                )

                f.write(f"- **Total Jobs**: {len(jobs_with_outreach)}\n")
                f.write(f"- **Email Outreach**: {email_count}\n")
                f.write(f"- **Text Message Outreach**: {text_count}\n")
                f.write(
                    f"- **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                )

                f.write("## 📋 Quick Action Checklist\n\n")
                for i, job in enumerate(jobs_with_outreach, 1):
                    recruiter_name = job["recruiter"]["name"]
                    job_title = job["title"]
                    f.write(f"- [ ] Contact {recruiter_name} about {job_title}\n")

            self.logger.info(f"Generated outreach markdown file: {filepath}")
            return filepath

        except Exception as e:
            self.logger.error(f"Error generating outreach markdown: {str(e)}")
            raise

    def process_jobs_for_outreach(self, status: str = "DISCOVERED") -> str:
        """
        Complete process: get jobs with recruiters, generate outreach content, create markdown.

        Args:
            status: Job status to process

        Returns:
            Path to generated markdown file
        """
        try:
            # Get jobs with recruiters
            jobs_with_recruiters = self.get_jobs_with_recruiters(status)

            if not jobs_with_recruiters:
                self.logger.info("No jobs with recruiters found")
                return None

            # Generate outreach content for each job
            jobs_with_outreach = []
            for job in jobs_with_recruiters:
                self.logger.info(
                    f"Generating outreach for: {job['title']} (Recruiter: {job['recruiter']['name']})"
                )
                outreach_content = self.generate_outreach_content(job)
                job["outreach"] = outreach_content
                jobs_with_outreach.append(job)

            # Generate markdown file
            markdown_path = self.generate_outreach_markdown(jobs_with_outreach)

            self.logger.info(
                f"Outreach generation complete. Generated content for {len(jobs_with_outreach)} jobs"
            )
            return markdown_path

        except Exception as e:
            self.logger.error(f"Error in outreach processing: {str(e)}")
            raise
