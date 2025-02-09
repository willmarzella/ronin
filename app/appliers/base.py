"""Base class for job application automation."""

from abc import ABC, abstractmethod
from typing import Dict, Optional, List, Any
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
import re
import time
import logging

from integrations.openai import OpenAIClient
from app.utils.config import load_config


class BaseApplier(ABC):
    """Base class for all job board application automation."""

    # Common form patterns across job boards
    COMMON_PATTERNS = {
        "years_experience": r"(?i)(how many )?years.*(experience|worked)",
        "salary_expectation": r"(?i)salary.*(expectation|requirement)",
        "start_date": r"(?i)(when|earliest).*(start|commence|begin)",
        "visa_status": r"(?i)(visa|work).*(status|right|permit)",
        "relocation": r"(?i)(willing|able).*(relocate|move)",
    }

    def __init__(self):
        """Initialize the base applier with common functionality."""
        self.config = load_config()
        self.openai_client = OpenAIClient()
        self.driver = None
        self.is_logged_in = False
        self.current_job_data = {}

    def _setup_driver(self):
        """Initialize Chrome WebDriver with common settings."""
        if self.driver:
            return

        options = webdriver.ChromeOptions()
        options.add_argument("--remote-debugging-port=9222")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)

        # Add additional preferences for better automation
        prefs = {
            "profile.default_content_setting_values.notifications": 2,  # Block notifications
            "credentials_enable_service": False,  # Disable save password prompt
            "profile.password_manager_enabled": False,
        }
        options.add_experimental_option("prefs", prefs)

        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            self.driver.set_window_size(1920, 1080)

            # Add CDP commands for better stealth
            self.driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {
                    "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
            )

            # Disable webdriver flags
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

        except Exception as e:
            raise Exception(f"Failed to initialize Chrome WebDriver: {str(e)}")

    def _analyze_form_context(self, form_element: Any) -> Dict[str, Any]:
        """Analyze the context and requirements of a form section."""
        context = {
            "required_fields": [],
            "optional_fields": [],
            "field_patterns": {},
            "validation_rules": {},
            "error_messages": {},
        }

        try:
            # Find required field indicators
            required_markers = form_element.find_elements(
                By.CSS_SELECTOR, "[required], [aria-required='true']"
            )
            for marker in required_markers:
                field_id = marker.get_attribute("id")
                if field_id:
                    context["required_fields"].append(field_id)

            # Look for validation patterns
            input_elements = form_element.find_elements(
                By.CSS_SELECTOR, "input[pattern]"
            )
            for input_elem in input_elements:
                pattern = input_elem.get_attribute("pattern")
                if pattern:
                    context["field_patterns"][input_elem.get_attribute("id")] = pattern

            # Check for character limits
            text_elements = form_element.find_elements(By.CSS_SELECTOR, "[maxlength]")
            for elem in text_elements:
                max_length = elem.get_attribute("maxlength")
                if max_length:
                    context["validation_rules"][elem.get_attribute("id")] = {
                        "max_length": int(max_length)
                    }

            # Look for error message containers
            error_elements = form_element.find_elements(
                By.CSS_SELECTOR, ".error, .invalid-feedback, [role='alert']"
            )
            for error_elem in error_elements:
                related_input = error_elem.find_element(
                    By.XPATH, "./preceding::input[1]"
                )
                if related_input:
                    context["error_messages"][
                        related_input.get_attribute("id")
                    ] = error_elem.text

        except Exception as e:
            logging.warning(f"Error analyzing form context: {str(e)}")

        return context

    def _detect_form_type(self, question: str) -> str:
        """Detect the type of question being asked."""
        question_lower = question.lower()

        # Check against common patterns
        for q_type, pattern in self.COMMON_PATTERNS.items():
            if re.search(pattern, question_lower):
                return q_type

        # Use AI to categorize unknown question types
        try:
            response = self.openai_client.chat_completion(
                system_prompt="You are a job application form analyzer. Categorize the following question into one of these types: personal_info, work_experience, education, skills, availability, legal, preferences, or other.",
                user_message=f"Categorize this job application question: {question}",
                temperature=0.3,
            )
            return response.get("category", "other")
        except:
            return "other"

    def _smart_wait_for_element(self, by: By, selector: str, timeout: int = 10) -> Any:
        """Smart wait for element with retry logic and dynamic waits."""
        start_time = time.time()
        last_exception = None

        while time.time() - start_time < timeout:
            try:
                # Check if element is in viewport
                element = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((by, selector))
                )

                # Scroll element into view if needed
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                    element,
                )
                time.sleep(0.5)  # Allow smooth scroll to complete

                # Wait for element to be clickable
                element = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((by, selector))
                )

                # Check if element is hidden by another element
                if not element.is_displayed():
                    overlapping = self.driver.execute_script(
                        """
                        var elem = arguments[0];
                        var rect = elem.getBoundingClientRect();
                        return document.elementFromPoint(rect.left + rect.width/2, rect.top + rect.height/2);
                    """,
                        element,
                    )

                    if overlapping and overlapping != element:
                        # Try to remove or handle overlapping element
                        self.driver.execute_script(
                            "arguments[0].remove();", overlapping
                        )
                        time.sleep(0.5)

                return element

            except Exception as e:
                last_exception = e
                time.sleep(0.5)

        raise (
            last_exception
            if last_exception
            else TimeoutException(f"Element {selector} not found")
        )

    def _handle_captcha(self):
        """Handle potential CAPTCHA challenges."""
        try:
            # Check for common CAPTCHA elements
            captcha_selectors = [
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                "iframe[src*='turnstile']",
            ]

            for selector in captcha_selectors:
                if self.driver.find_elements(By.CSS_SELECTOR, selector):
                    logging.warning(
                        "CAPTCHA detected! Waiting for manual intervention..."
                    )
                    print("\n=== CAPTCHA Detected ===")
                    print("1. Please solve the CAPTCHA in the browser window")
                    print("2. Press Enter once completed...")
                    input()
                    return True

            return False

        except Exception as e:
            logging.error(f"Error handling CAPTCHA: {str(e)}")
            return False

    def _validate_form_submission(self, form_element: Any) -> bool:
        """Validate form before submission and handle any errors."""
        try:
            # Check for visible error messages
            error_messages = form_element.find_elements(
                By.CSS_SELECTOR, ".error, .invalid-feedback, [role='alert']"
            )
            if error_messages:
                for error in error_messages:
                    if error.is_displayed():
                        logging.error(f"Form validation error: {error.text}")
                        return False

            # Check required fields
            required_fields = form_element.find_elements(
                By.CSS_SELECTOR, "[required], [aria-required='true']"
            )
            for field in required_fields:
                if not field.get_attribute("value").strip():
                    logging.error(
                        f"Required field not filled: {field.get_attribute('name')}"
                    )
                    return False

            return True

        except Exception as e:
            logging.error(f"Error validating form: {str(e)}")
            return False

    @abstractmethod
    def _login(self):
        """Handle login process for the specific job board."""
        pass

    @abstractmethod
    def _navigate_to_job(self, job_id: str):
        """Navigate to the specific job application page."""
        pass

    @abstractmethod
    def _handle_resume(self, job_id: str, tech_stack: str):
        """Handle resume selection/upload."""
        pass

    @abstractmethod
    def _handle_cover_letter(self):
        """Handle cover letter requirements."""
        pass

    @abstractmethod
    def _handle_screening_questions(self, job_description: str, tech_stack: str):
        """Handle any screening questions or requirements."""
        pass

    @abstractmethod
    def _submit_application(self) -> bool:
        """Submit the application and verify success."""
        pass

    def _get_ai_form_response(
        self, element_info: Dict, tech_stack: str, job_description: str
    ) -> Optional[Dict]:
        """Get AI-generated response for form elements."""
        try:
            tech_stack = tech_stack.lower()
            if tech_stack not in self.config["resume"]["text"]:
                tech_stack = "aws"  # Default fallback

            resume = self.config["resume"]["text"][tech_stack]

            # Detect question type for better context
            question_type = self._detect_form_type(element_info["question"])

            system_prompt = f"""You are a professional job applicant assistant. Based on my resume and the job context below, provide concise, relevant, and professional answers to job application questions.
You MUST return your response in valid JSON format with fields that match the input type:
- For textareas: {{"response": "your detailed answer"}}
- For radios: {{"selected_option": "id of the option to select"}}
- For checkboxes: {{"selected_options": ["id1", "id2", ...]}}
- For selects: {{"selected_option": "value of the option to select"}}

Question Type: {question_type}
Resume: {resume}
Job Description: {job_description}

Additional Context:
- Keep responses professional and aligned with the job requirements
- For experience questions, reference relevant projects from resume
- For technical questions, focus on demonstrated expertise
- For salary questions, research market rates for the role
- For availability questions, indicate immediate availability
- For visa/work rights questions, confirm eligibility
"""

            user_message = f"Question: {element_info['question']}\nInput type: {element_info['type']}\n"

            if "options" in element_info:
                options_str = "\n".join(
                    [
                        f"- {opt['label']} ({opt['id' if element_info['type'] in ['radio', 'checkbox'] else 'value']}: {opt['id' if element_info['type'] in ['radio', 'checkbox'] else 'value']})"
                        for opt in element_info["options"]
                    ]
                )
                user_message += f"\nAvailable options:\n{options_str}"

            response = self.openai_client.chat_completion(
                system_prompt=system_prompt, user_message=user_message, temperature=0.7
            )

            return response

        except Exception as e:
            raise Exception(f"Error getting AI response: {str(e)}")

    def apply_to_job(self, job_id: str, job_description: str, tech_stack: str) -> str:
        """
        Main method to apply to a job.

        Returns:
            str: One of "SUCCESS", "FAILED", or "NEEDS_MANUAL_APPLICATION"
        """
        try:
            self._setup_driver()

            # Store job data for context
            self.current_job_data = {
                "id": job_id,
                "description": job_description,
                "tech_stack": tech_stack,
            }

            if not self.is_logged_in:
                self._login()

            self._navigate_to_job(job_id)

            # Handle CAPTCHA if present
            if self._handle_captcha():
                logging.info("CAPTCHA handled successfully")

            self._handle_resume(job_id, tech_stack)
            self._handle_cover_letter()

            if not self._handle_screening_questions(job_description, tech_stack):
                return "NEEDS_MANUAL_APPLICATION"

            if self._submit_application():
                return "SUCCESS"
            return "FAILED"

        except Exception as e:
            raise Exception(f"Error applying to job {job_id}: {str(e)}")
        finally:
            self.current_job_data = {}

    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            finally:
                self.driver = None
                self.is_logged_in = False
