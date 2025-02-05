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

from integrations.airtable import AirtableManager
from integrations.openai import OpenAIClient
from app.utils.config import load_config


class SeekApplier:
    def __init__(self):
        self.qa_file = os.path.join(
            os.path.dirname(__file__), "../data/question_answers.json"
        )
        self.config = load_config()
        self.aws_resume_id = self.config["resume"]["preferences"]["aws_resume_id"]
        self.azure_resume_id = self.config["resume"]["preferences"]["azure_resume_id"]
        self.airtable = AirtableManager()
        self.openai_client = OpenAIClient()
        self.driver = None
        self.is_logged_in = False
        self.qa_data = self._load_qa_data()

    def _load_qa_data(self):
        """Load the question-answer mappings from JSON file"""
        try:
            if os.path.exists(self.qa_file):
                with open(self.qa_file, "r") as f:
                    return json.load(f)
            return {"selects": {}, "radios": {}, "checkboxes": {}, "textareas": {}}
        except Exception as e:
            logging.error(f"Failed to load Q&A data: {str(e)}")
            return {"selects": {}, "radios": {}, "checkboxes": {}, "textareas": {}}

    def _save_qa_data(self):
        """Save the updated question-answer mappings to JSON file"""
        try:
            os.makedirs(os.path.dirname(self.qa_file), exist_ok=True)
            with open(self.qa_file, "w") as f:
                json.dump(self.qa_data, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save Q&A data: {str(e)}")

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
            label = parent.find_element(By.TAG_NAME, "label")
            if label:
                return label.text.strip()

            # Try to find question text in nearby elements
            question = parent.find_element(
                By.CSS_SELECTOR, ".question-text, .field-label"
            )
            if question:
                return question.text.strip()

        except NoSuchElementException:
            pass

        return None

    def _get_ai_answer(self, question, element_type, options=None):
        """Get answer from OpenAI for a new question"""
        try:
            system_prompt = """You are a professional job applicant assistant. Provide concise, relevant, and professional answers to job application questions. 
Focus on highlighting skills and experience in a positive way. Return your response in JSON format with an 'answer' field."""

            prompt = f"Please provide an appropriate answer for the following question: '{question}'\n"

            if element_type == "select" and options:
                prompt += f"The available options are: {', '.join(options)}\n"
            elif element_type == "radio":
                prompt += "This is a yes/no question.\n"
            elif element_type == "checkbox":
                prompt += "Select all applicable options from the given choices. Return them as a comma-separated string.\n"
            elif element_type == "textarea":
                prompt += (
                    "Provide a professional and concise response (2-3 sentences).\n"
                )

            prompt += "\nRespond with a JSON object containing an 'answer' field with your response."

            response = self.openai_client.chat_completion(
                system_prompt=system_prompt,
                user_message=prompt,
                max_tokens=150,  # Keeping responses concise for job applications
            )

            if response and isinstance(response, dict):
                return response.get("content", {}).get("answer", "").strip()

            return None

        except Exception as e:
            logging.error(f"Failed to get AI answer: {str(e)}")
            return None

    def _handle_new_question(self, element, element_type):
        """Handle a new question not found in the JSON file"""
        question = self._get_element_label(element)
        if not question:
            return None

        element_id = element.get_attribute("name")
        options = None

        if element_type == "select":
            options = [opt.text for opt in element.find_elements(By.TAG_NAME, "option")]
            options = [opt for opt in options if opt.strip()]  # Remove empty options

        answer = self._get_ai_answer(question, element_type, options)
        if not answer:
            return None

        # Store the new Q&A pair
        qa_entry = {"question": question, "answer": answer}

        if element_type == "select":
            qa_entry["value"] = element.get_attribute("value")
        elif element_type == "radio":
            qa_entry["value"] = "yes" if answer.lower() == "yes" else "no"
        elif element_type == "checkbox":
            qa_entry["values"] = answer.split(", ")
        elif element_type == "textarea":
            qa_entry["value"] = answer

        self.qa_data[f"{element_type}s"][element_id] = qa_entry
        self._save_qa_data()

        return answer

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

            # Logic to select resume based on tech stack
            resume_id = (
                self.aws_resume_id if "AWS" in tech_stack else self.azure_resume_id
            )
            resume_option = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, f"option[value='{resume_id}']")
                )
            )
            resume_option.click()
            logging.info("Resume selected successfully")

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
            print("Clicked cover letter option")
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

            # Wait for navigation or loading to complete
            WebDriverWait(self.driver, 5).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            logging.error("Continue button not found or not clickable")
            raise

    def _handle_role_requirements(self):
        """Handle the role requirements page if it exists"""
        if "role-requirements" not in self.driver.current_url:
            return

        # Wait for the page to be fully loaded
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "form"))
        )

        print("Navigated to role-requirements page")
        print("Clicking through answers")

        # Have a JSON file that contains all the ids and values: selects, radios, checkboxes, text areas
        # When the HTML parser finds a question that's not in that list...feed it into OpenAI to get the correct answer, then store that answer back in the JSON file

        self._handle_select_questions()
        self._handle_radio_questions()
        self._handle_checkbox_questions()
        self._handle_text_questions()
        self._click_continue()

    def _handle_select_questions(self):
        """Handle dropdown select questions"""
        selects = self.driver.find_elements(By.CSS_SELECTOR, "select")
        if not selects:
            print("No selects found on the page")
            return

        print("Found selects on the page")
        for select_element in selects:
            try:
                element_id = select_element.get_attribute("name")
                if element_id in self.qa_data["selects"]:
                    # Use stored answer
                    value = self.qa_data["selects"][element_id]["value"]
                else:
                    # Get new answer from OpenAI
                    answer = self._handle_new_question(select_element, "select")
                    if not answer:
                        continue
                    value = select_element.get_attribute("value")

                option = select_element.find_element(
                    By.CSS_SELECTOR, f"option[value='{value}']"
                )
                option.click()
                print(f"Selected option with value '{value}' for {element_id}")
            except Exception as e:
                logging.error(f"Failed to handle select question: {str(e)}")
                continue

    def _handle_radio_questions(self):
        """Handle radio button questions"""
        radio_groups = {}
        radio_buttons = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio']"
        )

        if not radio_buttons:
            return

        print("Found radio buttons on the page")

        # Group radio buttons by name
        for radio in radio_buttons:
            name = radio.get_attribute("name")
            if name not in radio_groups:
                radio_groups[name] = []
            radio_groups[name].append(radio)

        # Handle each radio group
        for name, radios in radio_groups.items():
            try:
                if name in self.qa_data["radios"]:
                    # Use stored answer
                    value = self.qa_data["radios"][name]["value"]
                else:
                    # Get new answer from OpenAI
                    answer = self._handle_new_question(radios[0], "radio")
                    if not answer:
                        continue
                    value = "yes" if answer.lower() == "yes" else "no"

                # Find and click the appropriate radio button
                for radio in radios:
                    if radio.get_attribute("value").lower() == value.lower():
                        if radio.is_displayed() and radio.is_enabled():
                            self.driver.execute_script("arguments[0].click();", radio)
                            break

            except Exception as e:
                logging.error(f"Failed to handle radio question: {str(e)}")
                continue

    def _handle_checkbox_questions(self):
        """Handle checkbox questions"""
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='checkbox']"
        )
        if not checkboxes:
            return

        print("Found checkboxes on the page")

        # Group checkboxes by name/group
        checkbox_groups = {}
        for checkbox in checkboxes:
            name = checkbox.get_attribute("name")
            if name not in checkbox_groups:
                checkbox_groups[name] = []
            checkbox_groups[name].append(checkbox)

        # Handle each checkbox group
        for name, boxes in checkbox_groups.items():
            try:
                if name in self.qa_data["checkboxes"]:
                    # Use stored answers
                    values = self.qa_data["checkboxes"][name]["values"]
                else:
                    # Get new answer from OpenAI
                    answer = self._handle_new_question(boxes[0], "checkbox")
                    if not answer:
                        continue
                    values = answer.split(", ")

                # Click appropriate checkboxes
                for box in boxes:
                    value = box.get_attribute("value").lower()
                    if any(v.lower() in value for v in values):
                        if box.is_displayed() and box.is_enabled():
                            self.driver.execute_script("arguments[0].click();", box)

            except Exception as e:
                logging.error(f"Failed to handle checkbox question: {str(e)}")
                continue

    def _handle_text_questions(self):
        """Handle text area questions"""
        textareas = self.driver.find_elements(By.CSS_SELECTOR, "textarea")
        if not textareas:
            return

        print("Found textareas on the page")
        for textarea in textareas:
            try:
                element_id = textarea.get_attribute("name")
                if element_id in self.qa_data["textareas"]:
                    # Use stored answer
                    answer = self.qa_data["textareas"][element_id]["value"]
                else:
                    # Get new answer from OpenAI
                    answer = self._handle_new_question(textarea, "textarea")
                    if not answer:
                        continue

                if textarea.is_displayed() and textarea.is_enabled():
                    textarea.send_keys(answer)

            except Exception as e:
                logging.error(f"Failed to handle textarea question: {str(e)}")
                continue

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

            # Step 1: Login
            if not self.is_logged_in:
                self._login()

            # Step 2: Navigate to job and handle initial steps
            self._navigate_to_job(job_id)
            self._select_resume(job_id, tech_stack)
            self._handle_cover_letter()
            self._click_continue()

            # Step 3: Handle role requirements if they exist
            self._handle_role_requirements()

            # Step 4: Submit application
            self._submit_application()

            logging.info(f"Successfully applied to job {job_id}")
            return True

        except Exception as e:
            logging.error(f"Failed to apply to job {job_id}: {str(e)}")
            return False

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.is_logged_in = False
