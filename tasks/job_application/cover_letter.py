"""Cover letter generation functionality for job applications."""

import logging
from typing import Any, Dict, Optional

from services.ai_service import AIService


class CoverLetterGenerator:
    """Handles the generation of cover letters for job applications."""

    def __init__(self, ai_service: Optional[AIService] = None):
        """
        Initialize the cover letter generator.

        Args:
            ai_service: An instance of AIService. If None, a new instance will be created.
        """
        self.ai_service = ai_service or AIService()

    def generate_cover_letter(
        self,
        job_description: str,
        title: str,
        company_name: str,
        tech_stack: str,
        resume_text: str = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a cover letter for a job application.

        Args:
            job_description: The full job description text
            title: The job title
            company_name: The company name
            tech_stack: The tech stack for the job
            resume_text: Optional resume text to include. If None, will be loaded from appropriate files.

        Returns:
            Dictionary containing the generated cover letter or None if generation failed.
        """
        try:
            # Load example cover letter template
            with open("assets/cover_letter_example.txt", "r") as f:
                cover_letter_example = f.read()

            # If resume text not provided, load it
            if resume_text is None:
                resume_text = self._get_resume_text(tech_stack)

            system_prompt = f"""
You are a blunt, high-efficiency cover letter generator for a senior data engineering contractor named William Marzella. Your goal is to write short, punchy, technically literate cover letters that cut through noise and show immediate competence.

Context:
- William is not applying for junior roles, graduate programs, or career pivot positions.
- The letter is almost always for a *contracting* role, often via a *recruiter* but ultimately for a client.
- Assume the recruiter doesn't care about enthusiasm—they care about fit, availability, and rate justification.
- Your job is to signal readiness, alignment with stack/scope, and technical credibility in under 250 words.
- Show confidence. Avoid padding. If the stack is mentioned in the job ad, match it precisely.

Instructions:
- Address the recruiter by name if provided. Otherwise, use the agency name.
- If the agency name includes a long-form tagline (e.g. "Talent – Specialists in tech, transformation & beyond"), strip it down to the first word or primary brand name. Only use the part before symbols like "–", "-", or "|" (e.g. "Talent").
- Tailor the letter *to the client*, not the agency.
- Do not include generic phrases like "excited to apply" or "keen to contribute."
- Focus on relevant tech (Snowflake, dbt, Airflow, Databricks, AWS, Azure), project scope, and delivery track record.
- If job is legacy or BI-heavy (SSRS, Power BI), show realism but don’t overhype.

Use the example cover letter below to guide tone, brevity, and structure. The goal is credibility, not charm.

My name: William Marzella
My resume: {resume_text}
Example cover letter: {cover_letter_example}

-----

Your output must be valid JSON:
{{"response": "cover letter text"}}

-----
"""

            user_message = f"Write a cover letter for the job of {title} at {company_name}: {job_description}"

            return self.ai_service.chat_completion(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=0.7,
            )

        except Exception as e:
            logging.error(f"Failed to generate cover letter: {str(e)}")
            return None

    def _get_resume_text(self, tech_stack: str) -> str:
        """
        Get the resume text appropriate for the given tech stack.

        Args:
            tech_stack: The tech stack to get resume for

        Returns:
            Resume text as a string
        """
        tech_stack = tech_stack.lower() if tech_stack else "aws"
        resume_text = ""

        # Try to load tech stack-specific resume
        cv_file_path = f"assets/cv/{tech_stack}.txt"

        try:
            # First, try to find a tech stack-specific resume in assets/cv directory
            with open(cv_file_path, "r") as f:
                resume_text = f.read()
                logging.info(f"Using tech stack-specific resume from {cv_file_path}")
                return resume_text
        except FileNotFoundError:
            pass

        # Try to load from config if available
        try:
            from core.config import load_config

            config = load_config()

            if tech_stack in config["resume"]["text"]:
                if "file_path" in config["resume"]["text"][tech_stack]:
                    resume_file_path = config["resume"]["text"][tech_stack]["file_path"]
                    try:
                        with open(resume_file_path, "r") as f:
                            resume_text = f.read()
                            logging.info(
                                f"Using resume from config file_path: {resume_file_path}"
                            )
                            return resume_text
                    except Exception as e:
                        logging.error(
                            f"Failed to read resume file {resume_file_path}: {str(e)}"
                        )
                else:
                    # Use text directly from config if available
                    resume_text = config["resume"]["text"][tech_stack].get(
                        "content", ""
                    )
                    if resume_text:
                        logging.info(
                            f"Using resume content from config for {tech_stack}"
                        )
                        return resume_text
        except Exception as e:
            logging.warning(f"Error loading resume from config: {str(e)}")

        # If still no resume text, fall back to default "aws" tech stack
        if not resume_text and tech_stack != "aws":
            try:
                with open("assets/cv/aws.txt", "r") as f:
                    resume_text = f.read()
                    logging.info("Falling back to aws resume in assets/cv")
                    return resume_text
            except FileNotFoundError:
                logging.warning(
                    f"No resume found for tech stack {tech_stack} in assets/cv, using default"
                )

        # Last resort: fall back to default resume file
        if not resume_text:
            try:
                with open("assets/resume.txt", "r") as f:
                    resume_text = f.read()
                    logging.info("Using default resume.txt file")
                    return resume_text
            except FileNotFoundError:
                logging.error("Default resume.txt not found!")
                return "Resume information not available."

        return resume_text
