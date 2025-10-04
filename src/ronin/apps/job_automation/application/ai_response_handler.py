"""AI response generation and processing functionality."""

import json
import logging
from typing import Dict, Optional

from ronin.services.ai_service import AIService


class AIResponseHandler:
    """Handles AI response generation and processing for form elements."""

    def __init__(
        self, ai_service: Optional[AIService] = None, config: Optional[Dict] = None
    ):
        """
        Initialize the AI response handler.

        Args:
            ai_service: An instance of AIService. If None, a new instance will be created.
            config: Configuration dictionary. If None, will be loaded from config.
        """
        self.ai_service = ai_service or AIService()

        if config is None:
            from ronin.core.config import load_config

            self.config = load_config()
        else:
            self.config = config

    def get_ai_form_response(
        self, element_info: Dict, tech_stack: str, job_description: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get AI-generated response for a form element.

        Args:
            element_info: Dictionary containing information about the form element
            tech_stack: The tech stack for the job
            job_description: The job description text (optional)

        Returns:
            Dictionary containing the AI-generated response for the form element or None if generation failed.
        """
        try:
            tech_stack = tech_stack.lower()

            system_prompt = self._build_system_prompt()
            resume_text = self._get_resume_text(tech_stack)
            system_prompt += f"\n\nMy resume: {resume_text}"

            user_message = self._build_user_message(element_info, job_description)

            response = self.ai_service.chat_completion(
                system_prompt=system_prompt, user_message=user_message, temperature=0.3
            )

            print(response)

            if not response:
                logging.error("No response received from OpenAI")
                return None

            logging.info(f"AI response for {element_info['type']}: {response}")

            processed_response = self._process_ai_response(response, element_info)
            return processed_response

        except Exception as e:
            logging.error(f"Error getting AI response: {str(e)}")
            return None

    def get_ai_form_response_with_validation_context(
        self,
        element_info: Dict,
        tech_stack: str,
        job_description: Optional[str] = None,
        has_validation_error: bool = False,
    ) -> Optional[Dict]:
        """
        Get AI-generated response for a form element with validation context.

        Args:
            element_info: Dictionary containing information about the form element
            tech_stack: The tech stack for the job
            job_description: The job description text (optional)
            has_validation_error: Whether this field has a validation error

        Returns:
            Dictionary containing the AI-generated response for the form element or None if generation failed.
        """
        try:
            tech_stack = tech_stack.lower()

            system_prompt = self._build_system_prompt()
            resume_text = self._get_resume_text(tech_stack)
            system_prompt += f"\n\nMy resume: {resume_text}"

            user_message = self._build_user_message(
                element_info, job_description, has_validation_error
            )

            response = self.ai_service.chat_completion(
                system_prompt=system_prompt, user_message=user_message, temperature=0.3
            )

            print(response)

            if not response:
                logging.error("No response received from OpenAI")
                return None

            logging.info(f"AI response for {element_info['type']}: {response}")

            processed_response = self._process_ai_response(
                response, element_info, has_validation_error
            )
            return processed_response

        except Exception as e:
            logging.error(f"Error getting AI response: {str(e)}")
            return None

    def _build_system_prompt(self) -> str:
        """Build the system prompt for AI responses."""
        keywords = self.config["search"]["keywords"]
        base_prompt = (
            f"You are a professional job applicant assistant helping me apply to the following job(s) with keywords: {keywords}. "
            "I am an Australian citizen with full working rights. I have a drivers license. I am willing to undergo police checks if necessary. "
            "I do NOT have any security clearances (TSPV, NV1, NV2, Top Secret, etc) but am willing to undergo them if necessary. "
            "My salary expectations are $150, 000 - $200, 000, based on the job description you can choose to apply for a higher or lower salary. "
            "Based on my resume below, provide concise, relevant, and professional answers to job application questions. "
            "Note that some jobs might not exactly fit the keywords, but you should still apply if you think you're a good fit. "
            "This means using the options for answering questions correctly. DO NOT make up values or IDs that are not present in the options provided.\n\n"
            "IMPORTANT SECURITY CLEARANCE HANDLING:\n"
            '- If asked about current security clearance status, answer "No"\n'
            "- If asked about security clearance levels I hold, even though I don't have any, I must still select something if the form requires it. "
            'In such cases, select the lowest/baseline option available or "None" if available\n'
            "- If the form shows validation errors for required fields, I must select an appropriate option rather than leaving it blank\n\n"
            "You MUST return your response in valid JSON format with fields that match the input type:\n"
            '- For textareas: {"response": "your detailed answer"}\n'
            '- For radios: {"selected_option": "id of the option to select"}\n'
            '- For checkboxes: {"selected_options": ["id1", "id2", ...]}\n'
            '- For selects: {"selected_option": "value of the option to select"}\n\n'
            "For radio and checkbox inputs, ONLY return the exact ID from the options provided, not the label. "
            "DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. "
            "SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM.\n"
            "For select inputs, ONLY return the exact value attribute from the options provided, not the label. "
            "DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. "
            "SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM.\n"
            "For textareas, keep responses under 100 words and ensure it's properly escaped for JSON. "
            'IF YOU CANNOT FIND THE ANSWER OR ARE NOT SURE, RETURN "N/A".\n'
            "Always ensure your response is valid JSON and contains the expected fields. "
            "DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED.\n\n"
            "SPECIAL HANDLING FOR REQUIRED FIELDS:\n"
            "- If a checkbox question appears to be required (form validation), select the most appropriate option even if it's not ideal\n"
            "- For security clearance level questions, if I must select something, choose the baseline/lowest option available\n"
            "- Never return empty selections for required fields that show validation errors"
        )
        return base_prompt

    def _build_user_message(
        self,
        element_info: Dict,
        job_description: Optional[str] = None,
        has_validation_error: bool = False,
    ) -> str:
        """Build the user message for AI responses."""
        user_message = f"Question: {element_info['question']}\nInput type: {element_info['type']}\n"

        if has_validation_error:
            user_message += "\n⚠️ IMPORTANT: This field has a validation error ('Please make a selection'). You MUST select at least one option. Do not return empty selections.\n"

        if element_info["type"] == "select":
            options_str = "\n".join(
                [
                    f"- {opt['label']} (value: {opt['value']})"
                    for opt in element_info["options"]
                ]
            )
            user_message += "\nAvailable options:\n" + options_str

        elif element_info["type"] in ["radio", "checkbox"]:
            options_str = "\n".join(
                [
                    f"- {opt['label']} (id: {opt['id']})"
                    for opt in element_info["options"]
                ]
            )
            user_message += "\nAvailable options:\n" + options_str

            if has_validation_error and element_info["type"] == "checkbox":
                user_message += "\n⚠️ VALIDATION ERROR: You must select at least one option from the list above. For security clearance questions, select the baseline/lowest option if you don't have clearances."

        # Add type-specific instructions
        if element_info["type"] == "select":
            user_message += "\n\nIMPORTANT: Return ONLY the exact value from the options, not the label. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM."
        elif element_info["type"] in ["radio", "checkbox"]:
            user_message += "\n\nIMPORTANT: Return ONLY the exact ID of the option you want to select. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM."
        elif element_info["type"] == "textarea":
            user_message += "\n\nIMPORTANT: Keep your response under 100 words and ensure it's properly escaped for JSON."

        if job_description:
            user_message += f"\n\nJob Context: {job_description}"

        return user_message

    def _process_ai_response(
        self, response: str, element_info: Dict, has_validation_error: bool = False
    ) -> Optional[Dict]:
        """Process and validate the AI response."""
        # Check if response is a string and try to parse it as JSON
        if isinstance(response, str):
            try:
                response = json.loads(response)
                logging.info(
                    f"Successfully parsed string response into JSON: {response}"
                )
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse string response as JSON: {str(e)}")
                # Create fallback response based on element type
                response = self._create_fallback_response(response, element_info)
                logging.info(f"Created fallback response: {response}")

        # Fix case where AI returns 'selected_option' for checkbox types instead of 'selected_options'
        if (
            element_info["type"] == "checkbox"
            and "selected_option" in response
            and "selected_options" not in response
        ):
            response["selected_options"] = [response["selected_option"]]
            del response["selected_option"]
            logging.info(
                f"Converted selected_option to selected_options for checkbox: {response}"
            )

        # Special handling for validation errors - ensure we don't return empty selections
        if has_validation_error and element_info["type"] == "checkbox":
            if "selected_options" in response and not response["selected_options"]:
                # If we have a validation error and empty selection, select the first option as fallback
                if element_info.get("options") and len(element_info["options"]) > 0:
                    first_option_id = element_info["options"][0]["id"]
                    response["selected_options"] = [first_option_id]
                    logging.warning(
                        f"Validation error detected: forcing selection of first option {first_option_id}"
                    )

        # Validate response has expected fields
        if not self._validate_response_fields(response, element_info):
            return None

        # Process textarea response
        if element_info["type"] == "textarea" and "response" in response:
            response["response"] = json.loads(json.dumps(response["response"]))

        return response

    def _create_fallback_response(self, response_str: str, element_info: Dict) -> Dict:
        """Create a fallback response when JSON parsing fails."""
        if element_info["type"] == "select":
            return {"selected_option": response_str}
        elif element_info["type"] == "textarea":
            return {"response": response_str}
        elif element_info["type"] == "radio":
            return {"selected_option": response_str}
        elif element_info["type"] == "checkbox":
            return {"selected_options": [response_str]}
        else:
            return {"response": response_str}

    def _validate_response_fields(self, response: Dict, element_info: Dict) -> bool:
        """Validate that the response has the expected fields based on element type."""
        if element_info["type"] == "textarea" and "response" not in response:
            logging.error("Missing 'response' field in textarea response")
            return False
        elif element_info["type"] == "radio" and "selected_option" not in response:
            logging.error("Missing 'selected_option' field in radio response")
            return False
        elif element_info["type"] == "checkbox" and "selected_options" not in response:
            logging.error("Missing 'selected_options' field in checkbox response")
            return False
        elif element_info["type"] == "select" and "selected_option" not in response:
            logging.error("Missing 'selected_option' field in select response")
            return False

        return True

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
            if tech_stack in self.config["resume"]["text"]:
                if "file_path" in self.config["resume"]["text"][tech_stack]:
                    resume_file_path = self.config["resume"]["text"][tech_stack][
                        "file_path"
                    ]
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
                    resume_text = self.config["resume"]["text"][tech_stack].get(
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
