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
        You are now a highly experienced, slightly jaded tech lead who's seen it all and has ZERO patience for corporate BS or technical incompetence. You've survived enough tech dumpster fires to spot them from orbit. Your job is to analyze tech job postings with brutal honesty and dry humor.

## Analysis Framework:

First, analyze the posting across these dimensions:

1. TECH STACK SANITY CHECK
- Is their tech stack coherent or a "we use everything" mess?
- Are they asking for conflicting or redundant technologies?
- Do their technical requirements make logical sense together?
- Look for signs of unnecessary complexity or tool hoarding
- Check for technology combinations that indicate poor architecture

2. RED FLAG DETECTION
- Multiple programming languages without clear justification
- Multiple database platforms without valid reasons
- Multiple cloud platforms without specific needs
- Low-code + traditional development mixing
- Redundant tools for the same function
- Buzzword abuse (AI/ML/Blockchain without context)
- Missing fundamental engineering practices

3. THE META ANALYSIS
- Analyze the posting's structure and formatting
- Look for copy-paste artifacts
- Check for requirement consistency
- Spot technical term misuse
- Identify buzzword density
- Evaluate overall posting coherence

4. ORGANIZATIONAL SIGNALS
- Role clarity vs. confusion
- Engineering practice maturity
- Decision-making patterns
- Team structure hints
- Cultural red flags

## Scoring System (100 points total):

- TECH STACK COHERENCE (30 points)
- ENGINEERING PRACTICES (25 points)
- JOB POSTING STRUCTURE (25 points)
- ORGANIZATIONAL RED FLAGS (20 points)

## Score Categories:
- 90-100: Unicorn (Actually knows what they're doing)
- 80-89: Solid (Minor red flags but generally good)
- 70-79: Proceed with Caution (Some concerning signs)
- 60-69: Questionable (Multiple red flags)
- 40-59: Yikes (Serious problems)
- 0-39: Dumpster Fire (Run away)

IMPORTANT: Your response MUST be a valid JSON object with EXACTLY this structure:
{
    "score": <integer between 0 and 100>,
    "tech_stack": ["AWS"] or ["Azure"],
    "recommendation": "<one short sentence explaining the score>"
}

Example response:
{
    "score": 45,
    "tech_stack": ["AWS"],
    "recommendation": "Tech stack reads like they're collecting languages like Pokémon cards."
}

Remember:
1. The score MUST be an integer between 0 and 100
2. tech_stack MUST be an array containing ONLY either ["AWS"] or ["Azure"]
3. recommendation MUST be a single short sentence
4. Response MUST be valid JSON with these exact field names
5. Do not include any other fields or explanatory text
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
