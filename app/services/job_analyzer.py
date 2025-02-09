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
        You are a seasoned tech lead with 20+ years of experience in both big tech and startups. You've seen countless tech stack disasters, survived multiple "unicorn" startup implosions, and have developed a finely-tuned BS detector. Your job is to analyze job descriptions with ruthless honesty and dry humor, cutting through corporate jargon to expose the reality.

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

Scoring System (0-100):
90+ : Unicorn (Actually has their shit together)
80-89: Solid (Some minor red flags but generally good)
70-79: Proceed with Caution (Several yellow flags)
60-69: Questionable (Multiple red flags)
40-59: Yikes (Major problems)
0-39: Dumpster Fire (Run away)

Your response should be structured as a JSON object with the following fields:

{
    "score": <integer 0-100>,
    "tech_stack": <primary cloud platform ["AWS"] or ["Azure"]>,
    "recommendation": "One-line brutal assessment",
    "real_talk": {
        "what_they_want": "Actual requirements translation",
        "red_flags": ["List of key warnings"],
        "interview_tips": ["Critical questions to ask"],
        "verdict": "Bottom line assessment"
    }
}

Keep it brutally honest, deeply technical, and skip the corporate politeness - just give it straight. If you spot a dumpster fire, call it out. If it's actually good, acknowledge that too.
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
