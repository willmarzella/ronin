"""AI-powered recruiter detection and outreach service."""

import logging
import re
from typing import Dict, List, Optional, Tuple
from services.ai_service import AIService
from services.airtable_service import AirtableManager


class RecruiterDetectionService:
    """Service for detecting recruiters in job descriptions using AI."""
    
    RECRUITER_DETECTION_PROMPT = """
    You are an expert at identifying recruiter and hiring manager information from job descriptions.
    
    Analyze the job description and extract any recruiter or hiring manager names mentioned.
    Look for patterns like:
    - "Contact Sarah Johnson for more information"
    - "Please reach out to Michael Chen"
    - "For questions, contact Lisa Wong at..."
    - "Hiring Manager: David Smith"
    - "Recruiter: Amanda Taylor"
    - "Apply via Jane Doe"
    - Names mentioned in contact sections
    - Names in email signatures or contact details
    
    IMPORTANT: Only extract names that are clearly identified as recruiters, hiring managers, or contact persons.
    Do NOT extract:
    - Company names
    - Job titles without associated names
    - Generic references like "hiring team" or "recruiter"
    - Names mentioned as examples or in other contexts
    
    Return your response as a JSON object:
    {
        "recruiters_found": [
            {
                "name": "Full Name",
                "context": "Brief context of how they were mentioned",
                "confidence": 0.95
            }
        ],
        "has_recruiters": true/false
    }
    
    If no recruiters are found, return:
    {
        "recruiters_found": [],
        "has_recruiters": false
    }
    """

    def __init__(self, ai_service: AIService, airtable: AirtableManager):
        """Initialize the recruiter detection service."""
        self.ai_service = ai_service
        self.airtable = airtable
        self.logger = logging.getLogger(__name__)

    def detect_recruiters_in_description(self, job_description: str) -> List[Dict]:
        """
        Use AI to detect recruiter names in job descriptions.
        
        Args:
            job_description: The job description text
            
        Returns:
            List of detected recruiters with their details
        """
        try:
            # Use AI to detect recruiters
            response = self.ai_service.get_completion(
                prompt=self.RECRUITER_DETECTION_PROMPT,
                user_message=f"Job Description:\n\n{job_description}",
                response_format="json_object"
            )
            
            if not response or "recruiters_found" not in response:
                self.logger.warning("Invalid response from AI recruiter detection")
                return []
                
            recruiters = response.get("recruiters_found", [])
            self.logger.info(f"AI detected {len(recruiters)} potential recruiters")
            
            return recruiters
            
        except Exception as e:
            self.logger.error(f"Error detecting recruiters with AI: {str(e)}")
            return []

    def find_matching_recruiters(self, detected_names: List[str]) -> List[Dict]:
        """
        Find matching recruiters in Airtable People table.
        
        Args:
            detected_names: List of names detected in job description
            
        Returns:
            List of matching recruiter records from Airtable
        """
        matching_recruiters = []
        
        for name in detected_names:
            if not name or len(name.strip()) < 2:
                continue
                
            try:
                # Search for people with matching names
                people = self.airtable.get_people_by_name(name)
                
                if people:
                    self.logger.info(f"Found {len(people)} matches for name '{name}'")
                    matching_recruiters.extend(people)
                else:
                    self.logger.info(f"No matches found for name '{name}'")
                    
            except Exception as e:
                self.logger.error(f"Error searching for recruiter '{name}': {str(e)}")
                continue
                
        return matching_recruiters

    def process_job_for_recruiters(self, job_data: Dict) -> Optional[str]:
        """
        Process a job to detect and link recruiters.
        
        Args:
            job_data: Job data dictionary
            
        Returns:
            Recruiter record ID if found and linked, None otherwise
        """
        try:
            job_description = job_data.get("description", "")
            if not job_description:
                self.logger.warning("No job description provided")
                return None
                
            # Step 1: Use AI to detect potential recruiter names
            detected_recruiters = self.detect_recruiters_in_description(job_description)
            
            if not detected_recruiters:
                self.logger.info("No recruiters detected in job description")
                return None
                
            # Step 2: Extract names and search in Airtable
            detected_names = [r.get("name") for r in detected_recruiters if r.get("name")]
            
            if not detected_names:
                self.logger.info("No valid recruiter names extracted")
                return None
                
            matching_recruiters = self.find_matching_recruiters(detected_names)
            
            if not matching_recruiters:
                self.logger.info("No matching recruiters found in Airtable")
                return None
                
            # Step 3: Return the best match (first one for now)
            best_match = matching_recruiters[0]
            self.logger.info(
                f"Linked job to recruiter: {best_match['name']} (ID: {best_match['id']})"
            )
            
            return best_match["id"]
            
        except Exception as e:
            self.logger.error(f"Error processing job for recruiters: {str(e)}")
            return None


class RecruiterOutreachService:
    """Service for generating outreach content for recruiters."""
    
    EMAIL_TEMPLATE_PROMPT = """
    You are an expert at writing professional, personalized outreach emails to recruiters.
    
    Write a compelling email to the recruiter about the job opportunity. The email should be:
    - Professional but personable
    - Concise (under 150 words)
    - Show genuine interest in the role
    - Highlight relevant experience briefly
    - Include a clear call to action
    
    Context:
    - Recruiter Name: {recruiter_name}
    - Job Title: {job_title}
    - Company: {company_name}
    - Job Score: {job_score}/100
    - Tech Stack: {tech_stack}
    
    Return a JSON object with:
    {
        "subject": "Email subject line",
        "body": "Email body content"
    }
    """
    
    TEXT_MESSAGE_PROMPT = """
    Write a professional but brief text message to a recruiter about a job opportunity.
    The message should be:
    - Under 160 characters if possible
    - Professional but friendly
    - Include your name and the job title
    - Request a brief conversation
    
    Context:
    - Recruiter Name: {recruiter_name}
    - Job Title: {job_title}
    - Company: {company_name}
    
    Return just the text message content, no JSON formatting.
    """

    def __init__(self, ai_service: AIService):
        """Initialize the outreach service."""
        self.ai_service = ai_service
        self.logger = logging.getLogger(__name__)

    def generate_email_content(self, recruiter: Dict, job: Dict) -> Dict:
        """
        Generate personalized email content for a recruiter.
        
        Args:
            recruiter: Recruiter data from Airtable
            job: Job data
            
        Returns:
            Dict with subject and body
        """
        try:
            prompt = self.EMAIL_TEMPLATE_PROMPT.format(
                recruiter_name=recruiter.get("name", ""),
                job_title=job.get("title", ""),
                company_name=job.get("company", ""),
                job_score=job.get("score", "N/A"),
                tech_stack=job.get("tech_stack", "")
            )
            
            response = self.ai_service.get_completion(
                prompt=prompt,
                user_message="Generate the email content.",
                response_format="json_object"
            )
            
            if response and "subject" in response and "body" in response:
                return response
            else:
                self.logger.warning("Invalid email generation response")
                return self._get_fallback_email(recruiter, job)
                
        except Exception as e:
            self.logger.error(f"Error generating email content: {str(e)}")
            return self._get_fallback_email(recruiter, job)

    def generate_text_content(self, recruiter: Dict, job: Dict) -> str:
        """
        Generate personalized text message for a recruiter.
        
        Args:
            recruiter: Recruiter data from Airtable
            job: Job data
            
        Returns:
            Text message content
        """
        try:
            prompt = self.TEXT_MESSAGE_PROMPT.format(
                recruiter_name=recruiter.get("name", ""),
                job_title=job.get("title", ""),
                company_name=job.get("company", "")
            )
            
            response = self.ai_service.get_completion(
                prompt=prompt,
                user_message="Generate the text message."
            )
            
            if response:
                return response.strip()
            else:
                return self._get_fallback_text(recruiter, job)
                
        except Exception as e:
            self.logger.error(f"Error generating text content: {str(e)}")
            return self._get_fallback_text(recruiter, job)

    def _get_fallback_email(self, recruiter: Dict, job: Dict) -> Dict:
        """Generate fallback email content."""
        return {
            "subject": f"Interest in {job.get('title', 'Position')} at {job.get('company', 'Your Company')}",
            "body": f"""Hi {recruiter.get('name', '')},

I hope this email finds you well. I came across the {job.get('title', 'position')} role at {job.get('company', 'your company')} and I'm very interested in learning more about this opportunity.

My background in data engineering and cloud technologies aligns well with what you're looking for. I'd love to discuss how I can contribute to your team.

Would you be available for a brief conversation this week?

Best regards,
[Your Name]"""
        }

    def _get_fallback_text(self, recruiter: Dict, job: Dict) -> str:
        """Generate fallback text message."""
        return f"Hi {recruiter.get('name', '')}, I'm interested in the {job.get('title', 'position')} at {job.get('company', 'your company')}. Could we chat briefly? Thanks!"
