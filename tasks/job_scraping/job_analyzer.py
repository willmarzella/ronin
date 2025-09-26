"""Service for analyzing job postings using OpenAI."""

import json
from typing import Dict, Optional

from loguru import logger

from tasks.job_scraping.prompts import JOB_ANALYSIS_PROMPT


class JobAnalyzerService:
    """Service for analyzing job postings using OpenAI."""

    def __init__(self, config: Dict, client):
        self.config = config
        self.client = client  # Store the OpenAI client
        self._system_prompt = JOB_ANALYSIS_PROMPT

    def analyze_job(self, job_data: Dict) -> Optional[Dict]:
        """
        Analyze a job posting using OpenAI.

        Args:
            job_data: Dictionary containing job information with a description field

        Returns:
            Dictionary containing the enriched job data with OpenAI analysis,
            or None if analysis fails
        """
        job_id = job_data.get("job_id", "unknown")
        job_title = job_data.get("title", "unknown")

        logger.info(f"Starting job analysis for '{job_title}' (ID: {job_id})")

        if not job_data.get("description"):
            logger.error(
                f"Job {job_id} ({job_title}) has no description. Skipping analysis."
            )
            return None

        try:
            logger.debug(f"Making OpenAI API call for job {job_id} ({job_title})")
            # Get job analysis from OpenAI using the client directly
            model = self.config.get("analysis", {}).get("model", "gpt-4-turbo-preview")
            logger.debug(f"Using model: {model}")

            # Get job analysis from OpenAI using the client directly
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": f"Analyze this job description:\n\n{job_data['description']}",
                    },
                ],
                temperature=0.7,
            )

            if not response:
                logger.error(
                    f"Failed to get analysis from OpenAI for job {job_id} ({job_title})"
                )
                return None

            try:
                # Extract and clean the content from the response
                content = response.choices[0].message.content
                logger.debug(f"Received response from OpenAI for job {job_id}")

                # Try to parse the JSON directly from the content
                # Sometimes the AI returns with extra text around the JSON
                try:
                    # Try direct JSON parsing first
                    analysis = json.loads(content)
                except json.JSONDecodeError:
                    # If direct parsing fails, try to extract JSON from the text
                    logger.warning(
                        f"Direct JSON parse failed for job {job_id}, trying to extract JSON"
                    )
                    import re

                    json_match = re.search(
                        r"({.*})", content.replace("\n", " "), re.DOTALL
                    )
                    if json_match:
                        try:
                            analysis = json.loads(json_match.group(1))
                        except json.JSONDecodeError:
                            logger.error(
                                f"Failed to extract valid JSON for job {job_id}"
                            )
                            return None
                    else:
                        logger.error(
                            f"No JSON pattern found in response for job {job_id}"
                        )
                        return None

                # Create enriched job data with analysis
                enriched_job = job_data.copy()
                enriched_job["analysis"] = analysis

                # Apply minimum score filtering if configured
                min_score = self.config.get("analysis", {}).get("min_score", 0)
                job_score = analysis.get("score", 0)

                if job_score < min_score:
                    logger.info(
                        f"Job {job_id} ({job_title}) score {job_score} below minimum {min_score}"
                    )
                    return None

                return enriched_job

            except Exception as e:
                logger.exception(
                    f"Error parsing OpenAI response for job {job_id} ({job_title}): {str(e)}"
                )
                logger.debug(
                    f"Raw response content: {response.choices[0].message.content}"
                )
                return None

        except Exception as e:
            logger.exception(
                f"Error calling OpenAI API for job {job_id} ({job_title}): {str(e)}"
            )
            return None
