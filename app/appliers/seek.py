# Applier for Seek (should be able to apply to any quick apply job)

# TODO: Implement the applier for Seek

# Link to apply for job is https://www.seek.com.au/job/{job_id}/apply

# Need to login to apply for job, need to add username and password to the .env file

# Job id will be passed as a parameter to the applier

# 1. Select resume based on the tech stack: AWS or Azure
# 2. Select "Don't include a cover letter"
# 3. Click "Continue" which effectively is just going to https://www.seek.com.au/job/{job_id}/apply/profile
# 4. On review page, no need to update anything,
# 5. Go to submission page which is https://www.seek.com.au/job/{job_id}/apply/review
# 6. Click "Submit application" which is button with data-testid="review-submit-application"
# 7. Verify navigation to https://www.seek.com.au/job/{job_id}/apply/success
# 8. Mark job as applied in Airtable

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
from app.utils.config import load_config


class SeekApplier:
    def __init__(self):
        self.cookies_file = os.getenv("SEEK_COOKIES_FILE", "seek_cookies.json")
        if not os.path.exists(self.cookies_file):
            raise ValueError(
                f"Cookies file not found at {self.cookies_file}. Please export your browser cookies first."
            )

        self.config = load_config()
        self.aws_resume_id = self.config["resume"]["preferences"]["aws_resume_id"]
        self.azure_resume_id = self.config["resume"]["preferences"]["azure_resume_id"]
        self.airtable = AirtableManager()
        self.driver = None
        self.is_logged_in = False

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

    def _select_resume(self, job_id, tech_stack):
        """Select appropriate resume based on tech stack"""
        try:
            # Wait for resume selection element
            print("Waiting for resume selection element")
            resume_dropdown = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "select[id=':r3:'][data-testid='select-input']")
                )
            )
            if resume_dropdown:
                resume_dropdown.click()
                logging.info("Resume dropdown clicked")
            else:
                print("Resume dropdown not found")

            # Logic to select resume based on the airtable record "Tech Stack" field
            if "AWS" in tech_stack:
                resume_option = self.driver.find_element(
                    By.CSS_SELECTOR,
                    f"option[value='{self.aws_resume_id}']",
                )
            else:
                resume_option = self.driver.find_element(
                    By.CSS_SELECTOR,
                    f"option[value='{self.azure_resume_id}']",
                )

            resume_option.click()
            logging.info("Resume selected successfully")
            time.sleep(5)

        except Exception as e:
            logging.error(f"Failed to select resume: {str(e)}")
            raise

    def apply_to_job(self, job_id, job_description, tech_stack):
        """Apply to a specific job on Seek"""
        try:
            if not self.driver:
                self._setup_driver()

            # Ensure logged in
            if not self.is_logged_in:
                self._login()

            # Navigate to job application page
            apply_url = f"https://www.seek.com.au/job/{job_id}/apply"
            self.driver.get(apply_url)

            print(f"Navigated to {apply_url}")

            # Select appropriate resume
            self._select_resume(job_id, tech_stack)

            # Don't include cover letter - find and click the radio button using data-testid - it's not clicking the input so we need to click the label
            # for="coverLetter-method-:r4:_2"
            print("Waiting for cover letter option")
            try:
                no_cover_letter = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, '[for="coverLetter-method-:r4:_2"]')
                    )
                )
                no_cover_letter.click()
                print("Clicked cover letter option")
                # It's not clicking the input so we need to click the label
            except TimeoutException:
                logging.info("No cover letter option not found, continuing...")

            # Click Continue to next page
            print("Waiting for continue button")
            time.sleep(5)
            continue_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )
            continue_button.click()
            print("Clicked continue button")

            # if the page navigates to /apply/role-requirements we need to handle this case
            if "role-requirements" in self.driver.current_url:
                print("Navigated to role-requirements page")
                print("Clicking through answers")

                # Dictionary mapping questionnaire fields to their desired values
                questionnaire_selects = {
                    "questionnaire.AU_Q_6_V_9": "AU_Q_6_V_9_A_14970",  # Work rights
                    "questionnaire.AU_Q_8_V_2": "AU_Q_8_V_2_A_14945",  # Expected salary
                    "questionnaire.AU_Q_13_V_2": "AU_Q_13_V_2_A_14998",
                    "questionnaire.AU_Q_363CE9F0B380053C96CC40CDD7C67116_V_1": "AU_Q_363CE9F0B380053C96CC40CDD7C67116_V_1_A_363CE9F0B380053C96CC40CDD7C67116_8",
                    "questionnaire.AU_Q_D42CC7B4A9AADD29BF02DD1B1319103A_V_2": "AU_Q_D42CC7B4A9AADD29BF02DD1B1319103A_V_2_A_D42CC7B4A9AADD29BF02DD1B1319103A_8",
                }

                # first find if there are any selects on the page
                selects = self.driver.find_elements(By.CSS_SELECTOR, "select")
                if selects:
                    print("Found selects on the page")
                    # Replace the existing selects list and click logic with:
                    for field_name, value in questionnaire_selects.items():
                        try:
                            select_element = self.driver.find_element(
                                By.CSS_SELECTOR, f"[name='{field_name}']"
                            )
                            option = select_element.find_element(
                                By.CSS_SELECTOR, f"option[value='{value}']"
                            )
                            option.click()
                            print(
                                f"Selected option with value '{value}' for {field_name}"
                            )
                        except NoSuchElementException:
                            print(f"Field {field_name} not found, skipping...")
                            continue
                else:
                    print("No selects found on the page")

                # Check if there are any radio buttons on the page
                radio_buttons = self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='radio']"
                )
                if radio_buttons:
                    print("Found radio buttons on the page")
                    # Find and click all radio inputs for "Yes" answers
                    yes_inputs = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "input[type='radio'][tabindex='0'][data-testid]",
                    )
                    for input_elem in yes_inputs:
                        try:
                            # Use JavaScript to click the radio input since it might be hidden
                            self.driver.execute_script(
                                "arguments[0].click();", input_elem
                            )
                            print("Clicked radio input option")
                        except Exception as e:
                            print(f"Failed to click radio input: {str(e)}")
                    time.sleep(2)  # Give a moment for any UI updates
                else:
                    print("No radio buttons found on the page")

                # Check for any checkboxes on the page
                checkboxes = self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='checkbox']"
                )
                if checkboxes:
                    print("Found checkboxes on the page")
                    # find all the checkboxes that don't have the attribute tabindex present
                    multiple_choice_checkboxes = self.driver.find_elements(
                        By.CSS_SELECTOR, "input[type='checkbox'][name*='questionnaire']"
                    )
                    # check ALL of the checkboxes that match this selector

                    # TO DO: check the checkboxes
                    for checkbox in multiple_choice_checkboxes:
                        checkbox.click()
                        print(f"Clicked checkbox {checkbox.get_attribute('name')}")

                    # Find the yes or no checkboxes

                    yes_checkboxes = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "input[type='checkbox'][tabindex='0'][data-testid]",
                    )

                    for i, checkbox in enumerate(yes_checkboxes):
                        checkbox.click()
                        print(f"Clicked checkbox {i}")

                    time.sleep(2)
                else:
                    print("No checkboxes found on the page")

                # if there are any textareas just fill them with Lorum ipsum
                textareas = self.driver.find_elements(By.CSS_SELECTOR, "textarea")
                if textareas:
                    print("Found textareas on the page")
                    for textarea in textareas:
                        textarea.send_keys("Lorum ipsum")
                    time.sleep(2)
                else:
                    print("No textareas found on the page")

                continue_button = self.driver.find_element(
                    By.CSS_SELECTOR, "[data-testid='continue-button']"
                )
                continue_button.click()
                print("Clicked continue button")

            # Wait for review page need to click continue button
            continue_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[data-testid='continue-button']")
                )
            )
            continue_button.click()

            # Wait for and click submit button
            submit_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[data-testid='review-submit-application']")
                )
            )
            submit_button.click()

            # Verify successful submission
            WebDriverWait(self.driver, 10).until(
                lambda driver: "success" in driver.current_url
            )

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
