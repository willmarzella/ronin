# TODO: break this into multiple functions that represent each step in the application process
# 1. Login
# 2. Go to application page for specific job and select resume and no cover letter
# 3. If there are employer questions, answer them
# 4. If not, go to the Update SEEK profile (just need to click continue button)
# 4. The review page will have a submit button, click it and verify successful submission


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

from integrations.airtable import AirtableManager
from integrations.openai import OpenAIClient
from app.utils.config import load_config


class SeekApplier:
    def __init__(self):
        self.config = load_config()
        self.aws_resume_id = self.config["resume"]["preferences"]["aws_resume_id"]
        self.azure_resume_id = self.config["resume"]["preferences"]["azure_resume_id"]
        self.airtable = AirtableManager()
        self.openai_client = OpenAIClient()
        self.driver = None
        self.is_logged_in = False

    def _get_element_label(self, element):
        """Get the question/label text for a form element"""
        try:
            # Try to find label by for attribute
            element_id = element.get_attribute("id")
            if element_id:
                label = self.driver.find_element(
                    By.CSS_SELECTOR, f'label[for="{element_id}"]'
                )
                if label:
                    return label.text.strip()

            # Try to find label in parent elements
            parent = element.find_element(By.XPATH, "..")

            # First try to find a direct label
            try:
                label = parent.find_element(By.TAG_NAME, "label")
                if label:
                    return label.text.strip()
            except NoSuchElementException:
                pass

            # Try to find question text in nearby elements
            try:
                question = parent.find_element(
                    By.CSS_SELECTOR, ".question-text, .field-label"
                )
                if question:
                    return question.text.strip()
            except NoSuchElementException:
                pass

            # For radio buttons, try to find the question in a legend element
            try:
                # Go up to the fieldset
                fieldset = element.find_element(By.XPATH, "ancestor::fieldset")
                if fieldset:
                    # Try to find the legend
                    legend = fieldset.find_element(By.TAG_NAME, "legend")
                    if legend:
                        # Try to find the strong text within the legend
                        try:
                            strong = legend.find_element(By.TAG_NAME, "strong")
                            return strong.text.strip()
                        except NoSuchElementException:
                            return legend.text.strip()
            except NoSuchElementException:
                pass

            # If we still haven't found the label, try going up the DOM tree
            try:
                parent = element.find_element(By.XPATH, "..")
                while parent:
                    try:
                        strong = parent.find_element(By.TAG_NAME, "strong")
                        if strong:
                            return strong.text.strip()
                    except NoSuchElementException:
                        pass
                    try:
                        parent = parent.find_element(By.XPATH, "..")
                    except NoSuchElementException:
                        break
            except NoSuchElementException:
                pass

        except NoSuchElementException:
            pass

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
        """Wait for manual login if needed"""
        if self.is_logged_in:
            return

        try:
            # Navigate to Seek
            self.driver.get("https://www.seek.com.au")

            print("\n=== Login Required ===")
            print("1. Please sign in with Google in the browser window")
            print("2. Make sure you're fully logged in")
            print(
                "3. Once you're logged in and can see your profile, press Enter to continue..."
            )

            input("\nPress Enter when you're logged in...")

            # After user confirms they're logged in, verify it
            try:
                # Try multiple selectors that indicate successful login
                login_selectors = [
                    "[data-automation='profile-menu']",
                    "[data-automation='account name']",
                    ".user-menu-button",
                    "[data-automation='signed-in-header']",
                ]

                for selector in login_selectors:
                    try:
                        WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        self.is_logged_in = True
                        logging.info("Successfully verified login")
                        return
                    except TimeoutException:
                        continue

                if not self.is_logged_in:
                    print(
                        "\nCouldn't verify login automatically. Are you sure you're logged in?"
                    )
                    print("1. Check that you can see your profile/account menu")
                    print("2. Press Enter to continue if you're sure you're logged in")
                    print("3. Or press Ctrl+C to exit and try again")
                    input("\nPress Enter to continue...")
                    self.is_logged_in = True

            except TimeoutException:
                logging.error("Could not verify login state")
                raise Exception("Login verification failed")

        except Exception as e:
            logging.error(f"Failed to verify login: {str(e)}")
            raise

    def _navigate_to_job(self, job_id):
        """Navigate to the job application page"""
        apply_url = f"https://www.seek.com.au/job/{job_id}/apply"
        self.driver.get(apply_url)
        print(f"Navigated to {apply_url}")
        # Wait for the page to be interactive instead of arbitrary sleep
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

    def _select_resume(self, job_id, tech_stack):
        """Select appropriate resume based on tech stack"""
        try:
            print("Waiting for resume selection element")
            # Use WebDriverWait instead of find_element for better reliability
            resume_dropdown = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "select[data-testid='select-input']")
                )
            )
            resume_dropdown.click()
            logging.info("Resume dropdown clicked")

            # Normalize tech stack handling
            tech_stack = tech_stack.lower()
            if "aws" in tech_stack:
                resume_id = self.aws_resume_id
            else:
                resume_id = self.azure_resume_id

            resume_option = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, f"option[value='{resume_id}']")
                )
            )
            resume_option.click()
            logging.info(f"Resume selected successfully for {tech_stack} tech stack")

            # Wait for the selection to be processed
            WebDriverWait(self.driver, 5).until(
                EC.invisibility_of_element_located(
                    (By.CSS_SELECTOR, ".loading-spinner")
                )
            )

        except Exception as e:
            logging.error(f"Failed to select resume: {str(e)}")
            raise

    def _handle_cover_letter(self):
        """Handle the cover letter selection step"""
        try:
            # Wait for the cover letter section to be present
            no_cover_letter = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, '[for="coverLetter-method-:r4:_2"]')
                )
            )
            no_cover_letter.click()
            print("Clicked the NO cover letter option")
        except TimeoutException:
            logging.info("No cover letter option found, continuing...")

    def _click_continue(self):
        """Click the continue button and wait for it"""
        try:
            continue_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[data-testid='continue-button']")
                )
            )
            continue_button.click()
            print("Clicked continue button")

        except TimeoutException:
            logging.error("Continue button not found or not clickable")
            raise

    def _handle_role_requirements(self):
        """Handle role requirements form with AI assistance"""
        if not "role-requirements" in self.driver.current_url:
            return

        # Wait for the form to be fully loaded
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "form"))
        )

        print("Navigating through role requirements form...")

        try:
            # Find all form elements that need handling
            form_elements = self._get_form_elements()

            for element_info in form_elements:
                try:
                    # Get AI response for the element
                    print(
                        "Getting AI response for",
                        f"{element_info['type']} {element_info['question']}",
                    )
                    ai_response = self._get_ai_form_response(
                        element_info, self.current_tech_stack
                    )
                    print(
                        "AI response for",
                        f"{element_info['type']} {element_info['question']}",
                        ai_response,
                    )
                    if not ai_response:
                        continue

                    # Apply the AI response to the form element
                    self._apply_ai_response(element_info, ai_response)

                except Exception as e:
                    logging.error(f"Error handling form element: {str(e)}")
                    continue

            # Click continue after filling out the form
            self._click_continue()

        except Exception as e:
            logging.error(f"Error in handling role requirements: {str(e)}")
            raise

    def _get_form_elements(self):
        """Get all form elements that need AI responses"""
        form_elements = []

        try:
            # Handle text areas
            textareas = self.driver.find_elements(By.CSS_SELECTOR, "textarea")
            for textarea in textareas:
                question = self._get_element_label(textarea)
                if question:
                    form_elements.append(
                        {
                            "type": "textarea",
                            "element": textarea,
                            "question": question,
                            "element_id": textarea.get_attribute("id"),
                            "name": textarea.get_attribute("name"),
                        }
                    )

            # Handle radio buttons (grouped by name)
            radio_groups = {}
            radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            for radio in radios:
                name = radio.get_attribute("name")
                if name not in radio_groups:
                    radio_groups[name] = []
                radio_groups[name].append(radio)

            for name, radios in radio_groups.items():
                # Get question from the first radio in group
                question = self._get_element_label(radios[0])
                if question:
                    options = []
                    for radio in radios:
                        label = self._get_element_label(radio)
                        if label:
                            options.append(
                                {
                                    "value": radio.get_attribute("value"),
                                    "label": label,
                                    "id": radio.get_attribute("id"),
                                }
                            )

                    form_elements.append(
                        {
                            "type": "radio",
                            "element": radios[0],  # Reference to first radio
                            "question": question,
                            "options": options,
                            "name": name,
                        }
                    )

            # Handle checkboxes (grouped by name)
            checkbox_groups = {}
            checkboxes = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='checkbox']"
            )
            for checkbox in checkboxes:
                name = checkbox.get_attribute("name")
                if name not in checkbox_groups:
                    checkbox_groups[name] = []
                checkbox_groups[name].append(checkbox)

            for name, boxes in checkbox_groups.items():
                question = self._get_element_label(boxes[0])
                if question:
                    options = []
                    for box in boxes:
                        label = self._get_element_label(box)
                        if label:
                            options.append(
                                {
                                    "value": box.get_attribute("value"),
                                    "label": label,
                                    "id": box.get_attribute("id"),
                                }
                            )

                    form_elements.append(
                        {
                            "type": "checkbox",
                            "element": boxes[0],  # Reference to first checkbox
                            "question": question,
                            "options": options,
                            "name": name,
                        }
                    )

            # Handle select dropdowns
            selects = self.driver.find_elements(By.CSS_SELECTOR, "select")
            for select in selects:
                question = self._get_element_label(select)
                if question:
                    options = []
                    for option in select.find_elements(By.TAG_NAME, "option"):
                        if option.text.strip():  # Only include non-empty options
                            options.append(
                                {
                                    "value": option.get_attribute("value"),
                                    "label": option.text.strip(),
                                    "id": option.get_attribute("id"),
                                }
                            )

                    form_elements.append(
                        {
                            "type": "select",
                            "element": select,
                            "question": question,
                            "options": options,
                            "element_id": select.get_attribute("id"),
                            "name": select.get_attribute("name"),
                        }
                    )

            return form_elements

        except Exception as e:
            logging.error(f"Error getting form elements: {str(e)}")
            return []

    def _apply_ai_response(self, element_info, ai_response):
        """Apply the AI response to the form element"""
        print(
            "Applying AI response of",
            ai_response,
            "for: ",
            f"{element_info['type']} {element_info['question']}",
        )
        try:
            element_type = element_info["type"]

            if element_type == "textarea":
                response_text = ai_response.get("response", "")
                if response_text:
                    element_info["element"].clear()
                    element_info["element"].send_keys(response_text)
                    logging.info(
                        f"Filled textarea with response: {response_text[:100]}..."
                    )

            elif element_type == "radio":
                selected_id = ai_response.get("selected_option", "")
                if selected_id:
                    try:
                        # Find and click the radio button by ID
                        radio = self.driver.find_element(By.ID, selected_id)
                        self.driver.execute_script("arguments[0].click();", radio)
                        logging.info(f"Selected radio option with ID: {selected_id}")
                    except Exception as e:
                        logging.error(
                            f"Failed to select radio with ID {selected_id}: {str(e)}"
                        )

            elif element_type == "checkbox":
                selected_ids = ai_response.get("selected_options", [])
                if selected_ids:
                    # Iterate over the selected ids and click the checkbox
                    for checkbox_id in selected_ids:
                        try:
                            checkbox = self.driver.find_element(By.ID, checkbox_id)
                            self.driver.execute_script(
                                "arguments[0].click();", checkbox
                            )
                            logging.info(f"Selected checkbox with ID: {checkbox_id}")
                        except Exception as e:
                            logging.error(
                                f"Failed to select checkbox with ID {checkbox_id}: {str(e)}"
                            )

            elif element_type == "select":
                selected_value = ai_response.get("selected_option", "")
                if selected_value:
                    try:
                        # First try using the Select class
                        select = Select(element_info["element"])
                        select.select_by_value(selected_value)
                        logging.info(
                            f"Selected dropdown option with value: {selected_value}"
                        )
                    except Exception as e:
                        logging.error(f"Failed to select using Select class: {str(e)}")
                        try:
                            # Fallback: Try clicking the option directly
                            option = self.driver.find_element(
                                By.CSS_SELECTOR,
                                f'select[id="{element_info["element_id"]}"] option[value="{selected_value}"]',
                            )
                            option.click()
                            logging.info(
                                f"Selected dropdown option by clicking: {selected_value}"
                            )
                        except Exception as e2:
                            logging.error(
                                f"Failed to select option by clicking: {str(e2)}"
                            )
                            raise

        except Exception as e:
            logging.error(f"Error applying AI response: {str(e)}")
            raise

    def _submit_application(self):
        """Submit the application and verify success"""
        # Click continue on review page
        self._click_continue()

        # Wait for and click submit button
        submit_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "[data-testid='review-submit-application']")
            )
        )
        submit_button.click()

        # Verify successful submission with longer timeout
        WebDriverWait(self.driver, 15).until(
            lambda driver: "success" in driver.current_url
        )

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
            self._select_resume(job_id, tech_stack)
            self._handle_cover_letter()
            self._click_continue()

            # Check if role requirements exist - if so, return early with special status
            if "role-requirements" in self.driver.current_url:
                self._handle_role_requirements()
                self._submit_application()
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
