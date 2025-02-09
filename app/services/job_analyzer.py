"""Service for analyzing job postings using OpenAI."""

import json
from typing import Dict, List, Optional
from loguru import logger
from integrations.openai import OpenAIClient


class JobAnalyzerService:
    """Service for analyzing job postings using OpenAI."""

    def __init__(self, config: Dict):
        self.config = config
        self.openai = OpenAIClient()
        self._system_prompt = """
        You are a seasoned tech lead with 20+ years of experience in both big tech and startups. You've seen countless tech stack disasters, survived multiple "unicorn" startup implosions, and have developed a finely-tuned BS detector. Your job is to analyze job descriptions with ruthless honesty, cutting through corporate jargon to expose the reality.

Core Analysis Framework:

1. TECH STACK REALITY CHECK
- Is this a coherent stack or a "we use everything" mess?
- Are they actually building something or collecting buzzwords?
- Does their architecture make sense or is it overengineered?
- Are they cargo culting technologies?

2. RED FLAG DETECTOR
- "Startup DNA" translation
- Work-life balance hints
- Hidden expectations
- Multiple jobs disguised as one
- Signs of technical debt
- Management/process maturity
- Team size vs scope
- "Flexible" role warning signs

3. CORPORATE SPEAK TRANSLATOR
- What they say vs what they mean
- Actual day-to-day reality
- Hidden responsibilities
- Real expectations vs stated ones
- Culture code words decoded

4. INTERVIEW STRATEGY
- Key questions to ask
- Areas needing clarification
- Potential gotchas to probe
- Compensation discussion tips
- Work-life balance reality check

Your response should be structured as a JSON object with the following fields:

{
    "score": <integer 0-100 based on the analysis>,
    "tech_stack": <primary cloud platform ["AWS"] or ["Azure"]>,
    "recommendation": "One-line brutal assessment",
    "real_talk": {
        "what_they_want": "Actual requirements translation",
        "red_flags": ["List of key warnings"],
        "interview_tips": ["Critical questions to ask"],
        "verdict": "Bottom line assessment"
    }
}

Example:
{
    "score": 85,
    "tech_stack": ["AWS"],
    "recommendation": "This is a solid opportunity with a good tech stack.",
    "real_talk": {
        "what_they_want": "We need a data engineer who is proficient in AWS and has experience with data pipelines and ETL processes.",
        "red_flags": ["The company is known for its long hours and demanding work culture.", "The team is small and the workload is heavy."],
        "interview_tips": ["Ask about the company's work-life balance policy.", "Probe the compensation structure and benefits."],
        "verdict": "Overall, this is a good opportunity, but be prepared for a challenging work environment."
    }
}

IF THE TECH STACK IS NOT AWS OR AZURE, RETURN "AWS" ANYWAY.

REMEMBER: Keep it brutally honest, deeply technical, and skip the corporate politeness - just give it straight. If you spot a dumpster fire, call it out. If it's actually good, acknowledge that too.
"""

    def analyze_job(self, job_data: Dict) -> Optional[Dict]:
        """
        Analyze a job posting using OpenAI.

        Args:
            job_data: Dictionary containing job information with a description field

        Returns:
            Dictionary containing the enriched job data with OpenAI analysis,
            or None if analysis fails
        """
        try:
            # Log the job being analyzed
            logger.info(
                f"Analyzing job: {job_data.get('title')} (ID: {job_data.get('job_id')})"
            )

            # Get job analysis from OpenAI
            response = self.openai.chat_completion(
                system_prompt=self._system_prompt,
                user_message=f"Analyze this job description:\n\n{job_data['description']}",
                temperature=0.7,
            )

            if not response:
                logger.error(
                    f"Failed to get analysis from OpenAI for job {job_data.get('job_id')}"
                )
                return None

            try:
                # Handle the response based on its type
                if isinstance(response, dict):
                    analysis_data = response
                elif isinstance(response, str):
                    analysis_data = json.loads(response)
                else:
                    analysis_data = json.loads(response.get("content", "{}"))

                if not analysis_data:
                    logger.error(
                        f"No valid analysis data in OpenAI response for job {job_data.get('job_id')}"
                    )
                    return None

                # Map GCP to AWS (since we're focusing on AWS/Azure)
                if analysis_data.get("tech_stack") == ["GCP"]:
                    analysis_data["tech_stack"] = ["AWS"]

                # Validate required fields
                if not all(
                    k in analysis_data
                    for k in ["score", "tech_stack", "recommendation"]
                ):
                    logger.error("Missing required fields in analysis data")
                    return None

                # Log successful analysis
                logger.info(
                    f"Successfully analyzed job {job_data.get('job_id')} - Score: {analysis_data.get('score', 'N/A')}"
                )
                return {**job_data, "analysis": analysis_data}

            except Exception as e:
                logger.error(
                    f"Failed to process OpenAI response for job {job_data.get('job_id')}: {str(e)}"
                )
                logger.error(f"Raw response: {response}")
                return None

        except Exception as e:
            logger.error(
                f"Error analyzing job {job_data.get('title', 'Unknown')} (ID: {job_data.get('job_id', 'Unknown')}): {str(e)}"
            )
            logger.exception("Full traceback:")
            return None
