"""Seek.com.au job application automation."""

import os
import time
import json
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import Select
from typing import Dict, Optional, List

from integrations.airtable import AirtableManager
from integrations.openai import OpenAIClient
from app.utils.config import load_config
from app.appliers.base import BaseApplier


class SeekApplier(BaseApplier):
    """Handles job applications on Seek.com.au."""

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.aws_resume_id = self.config["resume"]["preferences"]["aws_resume_id"]
        self.azure_resume_id = self.config["resume"]["preferences"]["azure_resume_id"]
        self.airtable = AirtableManager()
        self.openai_client = OpenAIClient()
        self.driver = None
        self.is_logged_in = False

    def _get_element_label(self, element) -> Optional[str]:
        """Get the question/label text for a form element."""
        try:
            # Try to find label by for attribute
            element_id = element.get_attribute("id")
            if element_id:
                label = self.driver.find_element(
                    By.CSS_SELECTOR, f'label[for="{element_id}"]'
                )
                if label:
                    return label.text.strip()

            # Try various other methods to find the label
            parent = element.find_element(By.XPATH, "..")

            for selector in [
                "label",
                ".question-text",
                ".field-label",
                "legend strong",
                "legend",
            ]:
                try:
                    label_elem = parent.find_element(By.CSS_SELECTOR, selector)
                    if label_elem:
                        return label_elem.text.strip()
                except NoSuchElementException:
                    continue

            return None

        except Exception:
            return None

    def _get_ai_form_response(self, element_info, tech_stack):
        """Get AI response for a form element"""
        try:
            # Get the appropriate resume text based on tech stack
            tech_stack = tech_stack.lower()
            if tech_stack not in self.config["resume"]["text"]:
                logging.warning(
                    f"No resume found for tech stack {tech_stack}, using aws as default"
                )
                tech_stack = "aws"  # Default to aws if tech stack not found

            resume = self.config["resume"]["text"][tech_stack]

            # Using raw string and double curly braces to escape JSON examples
            system_prompt = f"""You are a professional job applicant assistant helping me apply to the following job(s) with keywords: {self.config["search"]["keywords"]}. I am an Australian citizen with full working rights. Based on my resume below, provide concise, relevant, and professional answers to job application questions.
You MUST return your response in valid JSON format with fields that match the input type:
- For textareas: {{"response": "your detailed answer"}}
- For radios: {{"selected_option": "id of the option to select"}}
- For checkboxes: {{"selected_options": ["id1", "id2", ...]}}
- For selects: {{"selected_option": "value of the option to select"}}

For radio and checkbox inputs, ONLY return the exact ID from the options provided, not the label.
For select inputs, ONLY return the exact value from the options provided, not the label.
For textareas, keep responses under 100 words and ensure it's properly escaped for JSON.
Always ensure your response is valid JSON and contains the expected fields."""

            system_prompt += f"\n\nMy resume: {resume}"

            # Construct the user message
            user_message = f"Question: {element_info['question']}\nInput type: {element_info['type']}\n"

            if element_info["type"] == "select":
                options_str = "\n".join(
                    [
                        f"- {opt['label']} (value: {opt['value']})"
                        for opt in element_info["options"]
                    ]
                )
                user_message += f"\nAvailable options:\n{options_str}"

            # For radio/checkbox, show the IDs
            elif element_info["type"] in ["radio", "checkbox"]:
                options_str = "\n".join(
                    [
                        f"- {opt['label']} (id: {opt['id']})"
                        for opt in element_info["options"]
                    ]
                )
                user_message += f"\nAvailable options:\n{options_str}"

            # Add specific instructions based on input type
            if element_info["type"] == "select":
                user_message += "\n\nIMPORTANT: Return ONLY the exact value from the options, not the label."
            elif element_info["type"] in ["radio", "checkbox"]:
                user_message += "\n\nIMPORTANT: Return ONLY the exact ID of the option you want to select."
            elif element_info["type"] == "textarea":
                user_message += "\n\nIMPORTANT: Keep your response under 100 words and ensure it's properly escaped for JSON."

            # Add context about the job if available
            if hasattr(self, "current_job_description"):
                user_message += f"\n\nJob Context: {self.current_job_description}"

            response = self.openai_client.chat_completion(
                system_prompt=system_prompt, user_message=user_message, temperature=0.7
            )

            if not response:
                logging.error("No response received from OpenAI")
                return None

            # Log the response for debugging
            logging.info(f"AI response for {element_info['type']}: {response}")

            # Validate response format based on element type
            if element_info["type"] == "textarea" and "response" not in response:
                logging.error("Missing 'response' field in textarea response")
                return None
            elif element_info["type"] == "radio" and "selected_option" not in response:
                logging.error("Missing 'selected_option' field in radio response")
                return None
            elif (
                element_info["type"] == "checkbox"
                and "selected_options" not in response
            ):
                logging.error("Missing 'selected_options' field in checkbox response")
                return None
            elif element_info["type"] == "select" and "selected_option" not in response:
                logging.error("Missing 'selected_option' field in select response")
                return None

            # For textarea responses, ensure the response is properly escaped
            if element_info["type"] == "textarea" and "response" in response:
                import json

                # Re-encode the response to ensure proper escaping
                response["response"] = json.loads(json.dumps(response["response"]))

            return response

        except Exception as e:
            logging.error(f"Error getting AI response: {str(e)}")
            return None

    def _setup_driver(self):
        """Initialize Chrome WebDriver with local browser"""
        if self.driver:
            return

        options = webdriver.ChromeOptions()

        # Add debugging info to help connect to existing Chrome
        options.add_argument("--remote-debugging-port=9222")

        # Disable automation flags to avoid detection
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Keep the browser open
        options.add_experimental_option("detach", True)

        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            # Start with a large window
            self.driver.set_window_size(1920, 1080)
            logging.info("Chrome WebDriver initialized successfully with local browser")
        except Exception as e:
            logging.error(f"Failed to initialize Chrome WebDriver: {str(e)}")
            raise

    def _login(self):
        """Handle Seek.com.au login process."""
        if self.is_logged_in:
            return

        try:
            # Navigate to Seek
            self.driver.get("https://www.seek.com.au")

            print("\n=== Login Required ===")
            print("1. Please sign in with Google in the browser window")
            print("2. Make sure you're fully logged in")
            print("3. Press Enter when ready to continue...")
            input()

            self.is_logged_in = True
            logging.info("Successfully logged into Seek")

        except Exception as e:
            raise Exception(f"Failed to login to Seek: {str(e)}")

    def _navigate_to_job(self, job_id: str):
        """Navigate to the specific job application page."""
        try:
            url = f"https://www.seek.com.au/job/{job_id}"
            self.driver.get(url)

            # Wait for the apply button
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-automation='job-detail-apply']")
                )
            )

            # Click the apply button
            apply_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-automation='job-detail-apply']"
            )
            apply_button.click()

        except Exception as e:
            raise Exception(f"Failed to navigate to job {job_id}: {str(e)}")

    def _handle_resume(self, job_id: str, tech_stack: str):
        """Handle resume selection for Seek applications."""
        try:
            # Wait for resume section to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-automation='resume-select']")
                )
            )

            # Select the appropriate resume based on tech stack
            resume_id = self.aws_resume_id
            if "azure" in tech_stack.lower():
                resume_id = self.azure_resume_id

            resume_select = Select(
                self.driver.find_element(
                    By.CSS_SELECTOR, "[data-automation='resume-select']"
                )
            )
            resume_select.select_by_value(resume_id)

            # Click continue
            continue_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-automation='continue-button']"
            )
            continue_button.click()

        except Exception as e:
            raise Exception(f"Failed to handle resume for job {job_id}: {str(e)}")

    def _handle_cover_letter(self):
        """Handle cover letter requirements for Seek applications."""
        try:
            # Wait for cover letter section
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-automation='cover-letter-select']")
                )
            )

            # Select "No cover letter"
            no_cover_select = self.driver.find_element(
                By.CSS_SELECTOR, "[data-automation='no-cover-letter']"
            )
            no_cover_select.click()

            # Click continue
            continue_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-automation='continue-button']"
            )
            continue_button.click()

        except Exception as e:
            raise Exception(f"Failed to handle cover letter: {str(e)}")

    def _get_form_elements(self) -> List[Dict]:
        """Get all form elements that need to be filled."""
        elements = []

        # Find all input elements
        for element in self.driver.find_elements(
            By.CSS_SELECTOR, "input, select, textarea"
        ):
            try:
                element_type = element.get_attribute("type")
                if element_type in ["hidden", "submit", "button"]:
                    continue

                label = self._get_element_label(element)
                if not label:
                    continue

                element_info = {
                    "element": element,
                    "type": element_type or element.tag_name,
                    "question": label,
                }

                # Get options for select/radio/checkbox
                if (
                    element_type in ["radio", "checkbox"]
                    or element.tag_name == "select"
                ):
                    options = []
                    if element.tag_name == "select":
                        for option in element.find_elements(By.TAG_NAME, "option"):
                            if option.get_attribute("value"):
                                options.append(
                                    {
                                        "value": option.get_attribute("value"),
                                        "label": option.text.strip(),
                                    }
                                )
                    else:
                        name = element.get_attribute("name")
                        for option in self.driver.find_elements(
                            By.CSS_SELECTOR, f'input[name="{name}"]'
                        ):
                            options.append(
                                {
                                    "id": option.get_attribute("id"),
                                    "label": self._get_element_label(option) or "",
                                }
                            )

                    element_info["options"] = options

                elements.append(element_info)

            except Exception as e:
                logging.warning(f"Error processing form element: {str(e)}")
                continue

        return elements

    def _apply_ai_response(self, element_info: Dict, ai_response: Dict):
        """Apply AI-generated response to a form element."""
        try:
            element = element_info["element"]

            if element_info["type"] == "textarea":
                element.clear()
                element.send_keys(ai_response["response"])

            elif element_info["type"] == "radio":
                option_id = ai_response["selected_option"]
                option = self.driver.find_element(By.ID, option_id)
                option.click()

            elif element_info["type"] == "checkbox":
                for option_id in ai_response["selected_options"]:
                    option = self.driver.find_element(By.ID, option_id)
                    option.click()

            elif element_info["type"] == "select":
                select = Select(element)
                select.select_by_value(ai_response["selected_option"])

            else:  # text, email, etc.
                element.clear()
                element.send_keys(ai_response["response"])

        except Exception as e:
            raise Exception(f"Failed to apply AI response: {str(e)}")

    def _handle_screening_questions(
        self, job_description: str, tech_stack: str
    ) -> bool:
        """Handle screening questions for Seek applications."""
        try:
            # Wait for questions section
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "form"))
                )
            except TimeoutException:
                # No questions to answer
                return True

            # Get all form elements
            elements = self._get_form_elements()
            if not elements:
                return True

            # Process each element
            for element_info in elements:
                try:
                    # Get AI response
                    ai_response = self._get_ai_form_response(element_info, tech_stack)
                    if not ai_response:
                        return False

                    # Apply the response
                    self._apply_ai_response(element_info, ai_response)

                except Exception as e:
                    logging.error(
                        f"Failed to handle question {element_info['question']}: {str(e)}"
                    )
                    return False

            # Click continue
            continue_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-automation='continue-button']"
            )
            continue_button.click()

            return True

        except Exception as e:
            logging.error(f"Failed to handle screening questions: {str(e)}")
            return False

    def _submit_application(self) -> bool:
        """Submit the application and verify success."""
        try:
            # Wait for submit button
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-automation='submit-button']")
                )
            )

            # Click submit
            submit_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-automation='submit-button']"
            )
            submit_button.click()

            # Wait for success message
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-automation='application-success']")
                    )
                )
                return True
            except TimeoutException:
                return False

        except Exception as e:
            logging.error(f"Failed to submit application: {str(e)}")
            return False

    def apply_to_job(self, job_id, job_description, tech_stack):
        """Apply to a specific job on Seek"""
        try:
            if not self.driver:
                self._setup_driver()

            # Store tech_stack and job_description for use in AI responses
            self.current_tech_stack = tech_stack
            self.current_job_description = job_description

            # Step 1: Login
            if not self.is_logged_in:
                self._login()

            # Step 2: Navigate to job and handle initial steps
            self._navigate_to_job(job_id)
            self._handle_resume(job_id, tech_stack)
            self._handle_cover_letter()

            # Check if role requirements exist - if so, return early with special status
            if "role-requirements" in self.driver.current_url:
                self._handle_screening_questions(job_description, tech_stack)
            # Step 4: Submit application
            else:
                self._submit_application()

            logging.info(f"Successfully applied to job {job_id}")
            return True

        except Exception as e:
            logging.error(f"Failed to apply to job {job_id}: {str(e)}")
            return False
        finally:
            # Clear the stored values
            self.current_tech_stack = None
            self.current_job_description = None

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.is_logged_in = False
