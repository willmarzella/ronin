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
from concurrent.futures import ThreadPoolExecutor

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
            system_prompt = f"""You are a professional job applicant assistant helping me apply to the following job(s) with keywords: {self.config["search"]["keywords"]}. I am an Australian citizen with full working rights. I have a drivers license. I do NOT have any security clearances (TSPV, NV1, NV2, Top Secret, etc). Based on my resume below, provide concise, relevant, and professional answers to job application questions. Note that some jobs might not exactly fit the keywords, but you should still apply if you think you're a good fit. This means using the options for answering questions correctly. DO NOT make up values or IDs that are not present in the options provided.
You MUST return your response in valid JSON format with fields that match the input type:
- For textareas: {{"response": "your detailed answer"}}
- For radios: {{"selected_option": "id of the option to select"}}
- For checkboxes: {{"selected_options": ["id1", "id2", ...]}}
- For selects: {{"selected_option": "value of the option to select"}}

For radio and checkbox inputs, ONLY return the exact ID from the options provided, not the label. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM.
For select inputs, ONLY return the exact value attribute from the options provided, not the label. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM.
For textareas, keep responses under 100 words and ensure it's properly escaped for JSON.
Always ensure your response is valid JSON and contains the expected fields. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED."""

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
                user_message += "\n\nIMPORTANT: Return ONLY the exact value from the options, not the label. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM."
            elif element_info["type"] in ["radio", "checkbox"]:
                user_message += "\n\nIMPORTANT: Return ONLY the exact ID of the option you want to select. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM."
            elif element_info["type"] == "textarea":
                user_message += "\n\nIMPORTANT: Keep your response under 100 words and ensure it's properly escaped for JSON."

            # Add context about the job if available
            if hasattr(self, "current_job_description"):
                user_message += f"\n\nJob Context: {self.current_job_description}"

            response = self.openai_client.chat_completion(
                system_prompt=system_prompt, user_message=user_message, temperature=0.3
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
                    (By.CSS_SELECTOR, "[data-testid='select-input']")
                )
            )

            # Select the appropriate resume based on tech stack
            resume_id = self.aws_resume_id
            if "azure" in tech_stack.lower():
                resume_id = self.azure_resume_id

            resume_select = Select(
                self.driver.find_element(
                    By.CSS_SELECTOR, "[data-testid='select-input']"
                )
            )
            resume_select.select_by_value(resume_id)

        except Exception as e:
            raise Exception(f"Failed to handle resume for job {job_id}: {str(e)}")

    def _handle_cover_letter(
        self, score: int, job_description: str, title: str, company_name: str
    ):
        """Handle cover letter requirements for Seek applications."""
        try:
            # Wait for cover letter section
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[for='coverLetter-method-:r4:_2']")
                )
            )

            if score and score > 70:
                # Select "Add a cover letter" option
                add_cover_letter = self.driver.find_element(
                    By.CSS_SELECTOR, "[for='coverLetter-method-:r4:_1']"
                )
                add_cover_letter.click()

                # Generate cover letter using OpenAI
                system_prompt = f"""You are a professional cover letter writer. Write a concise, compelling cover letter for the following job. 
                The letter should highlight relevant experience from my resume and demonstrate enthusiasm for the role. Use the example cover letter below to guide your writing. My name is William Marzella.
                Keep the tone professional but personable. Maximum 250 words.

                My resume: {open("assets/resume.txt").read()}
                
                Example cover letter: {open("assets/cover_letter_example.txt").read()}
                
                -----
                
                 Your response should be in valid JSON format:
                
                {{"response": "cover letter text"}}
                
                -----   
                
                """

                user_message = f"Write a cover letter for the job of {title} at {company_name}: {job_description}"

                cover_letter = self.openai_client.chat_completion(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    temperature=0.7,
                )

                if cover_letter:
                    # Wait for cover letter textarea
                    cover_letter_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.ID, "coverLetter-text-:r6:"))
                    )
                    cover_letter_input.clear()
                    cover_letter_input.send_keys(cover_letter["response"])
            else:
                # Select "No cover letter" option
                no_cover_select = self.driver.find_element(
                    By.CSS_SELECTOR, "[for='coverLetter-method-:r4:_2']"
                )
                no_cover_select.click()

            # Click continue
            continue_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )
            continue_button.click()

        except Exception as e:
            raise Exception(f"Failed to handle cover letter: {str(e)}")

    def _get_form_elements(self) -> List[Dict]:
        """Get all form elements that need to be filled."""
        elements = []

        # Find all form elements
        forms = self.driver.find_elements(By.TAG_NAME, "form")
        for form in forms:
            try:
                # Handle checkbox groups first
                checkbox_groups = {}

                # Find all checkbox group containers first
                checkbox_containers = form.find_elements(
                    By.XPATH,
                    ".//div[contains(@class, '_1wpnmph0') and .//strong and .//input[@type='checkbox']]",
                )

                for container in checkbox_containers:
                    # Get the question text from the strong element
                    question = container.find_element(
                        By.TAG_NAME, "strong"
                    ).text.strip()

                    # Get all checkboxes in this group
                    checkboxes = container.find_elements(
                        By.CSS_SELECTOR, 'input[type="checkbox"]'
                    )

                    if not checkboxes:
                        continue

                    # Use the first checkbox's name as the group identifier
                    name = checkboxes[0].get_attribute("name")
                    if not name:
                        continue

                    checkbox_groups[name] = {
                        "element": checkboxes[0],  # Store first checkbox as reference
                        "type": "checkbox",
                        "question": question,
                        "options": [],
                    }

                    # Add all checkboxes in this group as options
                    for checkbox in checkboxes:
                        checkbox_groups[name]["options"].append(
                            {
                                "id": checkbox.get_attribute("id"),
                                "label": self._get_element_label(checkbox) or "",
                            }
                        )

                # Add checkbox groups to elements list
                elements.extend(checkbox_groups.values())

                # Handle radio groups
                radio_groups = {}
                radios = form.find_elements(By.CSS_SELECTOR, 'input[type="radio"]')

                for radio in radios:
                    name = radio.get_attribute("name")
                    if not name:
                        continue

                    # Find the group question/label by looking at fieldset/legend
                    try:
                        fieldset = radio.find_element(
                            By.XPATH, "ancestor::fieldset[.//legend//strong]"
                        )
                        question = fieldset.find_element(
                            By.XPATH, ".//legend//strong"
                        ).text.strip()
                    except:
                        # Fallback to div with strong if not in fieldset
                        parent_div = radio.find_element(
                            By.XPATH,
                            "ancestor::div[contains(@class, '_1wpnmph0') and .//strong]",
                        )
                        question = parent_div.find_element(
                            By.TAG_NAME, "strong"
                        ).text.strip()

                    if name not in radio_groups:
                        radio_groups[name] = {
                            "element": radio,  # Store first radio as reference
                            "type": "radio",
                            "question": question,
                            "options": [],
                        }

                    # Add this radio's info to the options
                    radio_groups[name]["options"].append(
                        {
                            "id": radio.get_attribute("id"),
                            "label": self._get_element_label(radio) or "",
                        }
                    )

                # Add radio groups to elements list
                elements.extend(radio_groups.values())

                # Handle other input types (text, select, etc.)
                for element in form.find_elements(
                    By.CSS_SELECTOR,
                    "input:not([type='checkbox']):not([type='radio']), select, textarea",
                ):
                    element_type = element.get_attribute("type")
                    if element_type in ["hidden", "submit", "button"]:
                        continue

                    # Normalize select-one to select for consistency
                    if element_type == "select-one":
                        element_type = "select"

                    label = self._get_element_label(element)
                    if not label:
                        continue

                    element_info = {
                        "element": element,
                        "type": element_type or element.tag_name,
                        "question": label,
                    }

                    # Get options for select/radio
                    if element_type == "radio" or element.tag_name == "select":
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
                            for option in form.find_elements(
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
                logging.warning(f"Error processing form: {str(e)}")
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
                # Get all checkboxes in this group
                name = element.get_attribute("name")
                form = element.find_element(By.XPATH, "ancestor::form")
                checkboxes = form.find_elements(
                    By.CSS_SELECTOR, f'input[type="checkbox"][name="{name}"]'
                )

                # Get the IDs we want to select
                desired_ids = set(ai_response["selected_options"])

                # Click only the checkboxes that need to change state
                for checkbox in checkboxes:
                    checkbox_id = checkbox.get_attribute("id")
                    is_selected = checkbox.is_selected()
                    should_be_selected = checkbox_id in desired_ids

                    if is_selected != should_be_selected:
                        checkbox.click()

            elif element_info["type"] == "select":
                select = Select(element)
                select.select_by_value(ai_response["selected_option"])

            else:  # text, email, etc.
                element.clear()
                element.send_keys(ai_response["response"])

        except Exception as e:
            raise Exception(f"Failed to apply AI response: {str(e)}")

    def _handle_screening_questions(self) -> bool:
        """Handle any screening questions on the application."""
        try:
            # Wait for form elements with timeout
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda driver: len(self._get_form_elements()) > 0
                    or "review" in driver.current_url
                )
            except TimeoutException:
                logging.info(
                    "No screening questions found within timeout, moving to next step"
                )
                return True

            elements = self._get_form_elements()
            if not elements:
                return True

            # Process each form element sequentially
            for element_info in elements:
                print(f"Processing question: {element_info}")
                try:
                    # Get AI response for this element
                    ai_response = self._get_ai_form_response(
                        element_info, self.current_tech_stack
                    )

                    print(f"AI response: {ai_response}")

                    if not ai_response:
                        logging.warning(
                            f"No response for question: {element_info['question']}"
                        )
                        continue

                    # Apply the response
                    self._apply_ai_response(element_info, ai_response)
                    print(f"Applied {element_info['question']} with {ai_response}")

                except Exception as e:
                    logging.error(
                        f"Failed to handle question {element_info['question']}: {str(e)}"
                    )
                    continue

            # Click continue with timeout
            try:
                continue_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, "[data-testid='continue-button']")
                    )
                )
                continue_button.click()
                return True
            except TimeoutException:
                logging.error("Timeout waiting for continue button")
                return False

        except Exception as e:
            logging.error(f"Failed to handle screening questions: {str(e)}")
            return False

    def _submit_application(self) -> bool:
        """Submit the application after all questions are answered."""
        try:
            time.sleep(2)  # Give the page time to transition
            print("Waiting for review continue button")

            # Check for and handle privacy policy checkbox
            try:
                privacy_checkbox = self.driver.find_element(By.ID, "privacyPolicy")
                if not privacy_checkbox.is_selected():
                    privacy_checkbox.click()
                    time.sleep(0.5)  # Brief pause after clicking
            except NoSuchElementException:
                # Privacy checkbox not present, continue normally
                pass

            # Wait for the review continue button
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='continue-button']")
                )
            )

            continue_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )
            continue_button.click()

            print("Clicked continue button")

            time.sleep(2)  # Give the page time to transition

            print("Waiting for submit button")

            # Wait for the submit button
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='review-submit-application']")
                )
            )

            # Click submit
            submit_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='review-submit-application']"
            )
            submit_button.click()

            print("Clicked submit button")

            time.sleep(2)  # Give the submission time to complete

            # Check for success indicators
            success_indicators = [
                "success" in self.driver.current_url,
                bool(
                    self.driver.find_elements(By.CSS_SELECTOR, "[id='applicationSent']")
                ),
                bool(
                    self.driver.find_elements(
                        By.CSS_SELECTOR, "[data-testid='application-success']"
                    )
                ),
                "submitted" in self.driver.page_source.lower(),
            ]

            return any(success_indicators)

        except Exception as e:
            logging.warning(f"Issue during submission process: {str(e)}")
            # Don't return False here - check the URL as a fallback
            success_url_check = "success" in self.driver.current_url
            if success_url_check:
                return True
            return False

    def apply_to_job(
        self, job_id, job_description, score, tech_stack, company_name, title
    ):
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
            self._handle_cover_letter(
                score=score,
                job_description=job_description,
                title=title,
                company_name=company_name,
            )

            # Step 3: Handle screening questions if they exist
            if "role-requirements" in self.driver.current_url:
                if not self._handle_screening_questions():
                    logging.warning("Issue with screening questions, but continuing...")

            # Step 4: Submit application
            submission_result = self._submit_application()

            # Check for success indicators even if submission reported failure
            success_indicators = [
                "success" in self.driver.current_url,
                bool(
                    self.driver.find_elements(By.CSS_SELECTOR, "[id='applicationSent']")
                ),
                bool(
                    self.driver.find_elements(
                        By.CSS_SELECTOR, "[data-testid='application-success']"
                    )
                ),
                "submitted" in self.driver.page_source.lower(),
            ]

            if any(success_indicators):
                logging.info(f"Successfully applied to job {job_id}")
                return "SUCCESS"

            if not submission_result:
                logging.warning(f"Application may have failed for job {job_id}")
                return "FAILED"

            return "SUCCESS"

        except Exception as e:
            logging.warning(f"Exception during application for job {job_id}: {str(e)}")
            # Check for success indicators even after exception
            if self.driver and any(
                [
                    "success" in self.driver.current_url,
                    bool(
                        self.driver.find_elements(
                            By.CSS_SELECTOR, "[id='applicationSent']"
                        )
                    ),
                    bool(
                        self.driver.find_elements(
                            By.CSS_SELECTOR, "[data-testid='application-success']"
                        )
                    ),
                    "submitted" in self.driver.page_source.lower(),
                ]
            ):
                logging.info(f"Application successful despite errors for job {job_id}")
                return "SUCCESS"
            return "FAILED"

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
