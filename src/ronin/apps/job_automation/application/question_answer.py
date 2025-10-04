"""Question answering functionality for job application forms."""

from typing import Dict, List, Optional

from ronin.services.ai_service import AIService

from .ai_response_handler import AIResponseHandler
from .form_applier import FormApplier
from .html_formatter import HTMLFormatter
from .validation_checker import ValidationChecker


class QuestionAnswerHandler:
    """Handles the answering of questions in job application forms using AI."""

    def __init__(
        self, ai_service: Optional[AIService] = None, config: Optional[Dict] = None
    ):
        """
        Initialize the question answer handler.

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

        # Initialize modular components
        self.ai_handler = AIResponseHandler(
            ai_service=self.ai_service, config=self.config
        )
        self.form_applier = FormApplier()
        self.html_formatter = HTMLFormatter()
        self.validation_checker = ValidationChecker()

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
        return self.ai_handler.get_ai_form_response(
            element_info, tech_stack, job_description
        )

    def apply_ai_response(self, element_info: Dict, ai_response: Dict, driver):
        """
        Apply AI-generated response to a form element.

        Args:
            element_info: Dictionary containing information about the form element
            ai_response: Dictionary containing the AI-generated response
            driver: Selenium WebDriver instance

        Raises:
            Exception: If applying the response fails
        """
        return self.form_applier.apply_ai_response(element_info, ai_response, driver)

    def get_form_elements(self, driver) -> List[Dict]:
        """
        Get all form elements from the current page that need to be filled.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            List of dictionaries containing information about form elements
        """
        return self.html_formatter.get_form_elements(driver)

    def has_validation_errors(self, driver) -> bool:
        """
        Check if the current form has validation errors.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            True if validation errors are present, False otherwise
        """
        return self.validation_checker.has_validation_errors(driver)

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
        return self.ai_handler.get_ai_form_response_with_validation_context(
            element_info, tech_stack, job_description, has_validation_error
        )
