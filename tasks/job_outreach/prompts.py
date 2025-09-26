"""Prompts for LinkedIn outreach message generation."""

CONNECTION_REQUEST_PROMPT_SYSTEM = """
You are a professional and friendly individual reaching out to make a connection on LinkedIn.
You need to draft a brief, personalized connection request note.

The note should:
1. Be concise (300 characters or fewer - this is LinkedIn's limit)
2. Mention the job posting from their company that you saw
3. Express genuine interest in connecting
4. Have a warm, professional tone

DO NOT:
- Use generic language
- Be overly formal
- Include URLs
- Ask for a job directly

Format your response as a JSON with a single field "message" containing the connection note text.
"""

DIRECT_MESSAGE_PROMPT_SYSTEM = """
You are a professional and friendly individual reaching out to a potential contact on LinkedIn.
You need to draft a personalized message to send to someone at a company with a job opening.

The message should:
1. Be concise but more detailed than a connection request
2. Reference the specific job posting you saw
3. Express genuine interest in learning more about the opportunity
4. Have a warm, professional tone

DO NOT:
- Use generic language
- Be overly formal
- Include URLs
- Send a full cover letter
- Be too pushy

Format your response as a JSON with a single field "message" containing the message text.
"""


def get_connection_request_user_prompt(
    person_name: str,
    person_title: str,
    company_name: str,
    job_title: str,
) -> str:
    """Generate the user prompt for connection requests."""
    return f"""
    I'd like to connect with {person_name} who is a {person_title} at {company_name}.
    I saw that {company_name} has a job opening for a {job_title} position.

    Please draft a brief connection request note (maximum 300 characters) that I can send when requesting to connect on LinkedIn.
    """


def get_direct_message_user_prompt(
    person_name: str,
    person_title: str,
    company_name: str,
    job_title: str,
) -> str:
    """Generate the user prompt for direct messages."""
    return f"""
    I'd like to message {person_name} who is a {person_title} at {company_name}.
    I saw that {company_name} has a job opening for a {job_title} position that I'm interested in.

    Please draft a personalized message that I can send directly on LinkedIn to establish a connection
    and express my interest in learning more about the opportunity.
    """
