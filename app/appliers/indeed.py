"""Indeed.com job application automation."""

import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import Select
from typing import Dict, Optional, List
from selenium.webdriver.common.action_chains import ActionChains

from integrations.airtable import AirtableManager
from integrations.openai import OpenAIClient
from app.utils.config import load_config
from app.appliers.base import BaseApplier


class IndeedApplier(BaseApplier):
    """Handles job applications on Indeed.com."""

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.aws_resume_id = self.config["resume"]["preferences"]["aws_resume_id"]
        self.azure_resume_id = self.config["resume"]["preferences"]["azure_resume_id"]
        self.airtable = AirtableManager()
        self.openai_client = OpenAIClient()
        self.driver = None
        self.is_logged_in = False

    def _setup_driver(self):
        """Initialize Chrome WebDriver with local browser"""
        if self.driver:
            return

        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)
        options.add_argument("--user-data-dir=chrome-data")
        options.add_argument("--profile-directory=Default")

        try:
            service = Service()
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.implicitly_wait(10)
            self.driver.set_window_size(1920, 1080)
            logging.info("Chrome WebDriver initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize Chrome WebDriver: {str(e)}")
            raise

    def _login(self):
        """Handle Indeed.com login process."""
        if self.is_logged_in:
            return

        try:
            self.driver.get("https://au.indeed.com")
            print("\n=== Login Required ===")
            print("1. Please sign in with Google in the browser window")
            print("2. Make sure you're fully logged in")
            print("3. Press Enter when ready to continue...")
            input()
            self.is_logged_in = True
            logging.info("Successfully logged into Indeed")
        except Exception as e:
            raise Exception(f"Failed to login to Indeed: {str(e)}")

    def _navigate_to_job(self, job_id: str):
        """Navigate to the specific job application page."""
        try:
            # Indeed job URLs use the format: https://au.indeed.com/viewjob?jk=<job_id>
            # The job_id from Airtable is already in the correct format
            url = f"https://au.indeed.com/viewjob?jk={job_id}"
            self.driver.get(url)

            time.sleep(2)

            apply_button = self.driver.find_element(By.ID, "indeedApplyButton")

            time.sleep(2)

            # Try multiple click methods
            try:
                # Method 1: JavaScript click
                self.driver.execute_script("arguments[0].click();", apply_button)
            except Exception:
                try:
                    # Method 2: ActionChains click
                    ActionChains(self.driver).move_to_element(
                        apply_button
                    ).click().perform()
                except Exception:
                    # Method 3: Regular click as fallback
                    apply_button.click()

            print("Clicked apply button")

            time.sleep(2)

            if "https://smartapply.indeed.com/beta/" not in self.driver.current_url:
                # throw error
                raise Exception("Failed to navigate to job application page")

        except Exception as e:
            print(e)
            raise Exception(f"Failed to navigate to job {job_id}: {str(e)}")

   

    def _handle_resume(self, job_id: str, tech_stack: str):
        # url = https://smartapply.indeed.com/beta/indeedapply/form/resume click continue button
        if (
            self.driver.current_url
            == "https://smartapply.indeed.com/beta/indeedapply/form/resume"
        ):
            # click to select resume, div has id=ihl-useId-indeed-theme-provider-nujbyc-1-file-resume
            resume_div = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='FileResumeCard']"
            )
            resume_div.click()

            # click continue button by clicking the div containing the buttons
            footer_div = self.driver.find_element(
                By.CSS_SELECTOR, "div[class*='ia-BasePage-footer'] > div"
            )
            if footer_div:
                footer_div.click()
                return True
            else:
                raise Exception("Failed to click continue button")
        return False

    def _handle_cover_letter(self):
        return super()._handle_cover_letter()
      
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
          for selector in ["label", ".question-text", ".field-label", "legend"]:
              try:
                  label_elem = parent.find_element(By.CSS_SELECTOR, selector)
                  if label_elem:
                      return label_elem.text.strip()
              except NoSuchElementException:
                  continue

          return None
      except Exception:
          return None

    def _get_form_elements(self) -> List[Dict]:
        """Get all form elements that need to be filled."""
        elements = []
        try:
            # Find all form elements
            forms = self.driver.find_elements(By.TAG_NAME, "main")
            print(forms)
            for form in forms:
                # Find all input elements
                inputs = form.find_elements(By.CSS_SELECTOR, "input, select, textarea")
                print(inputs)
                for element in inputs:
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

                    # Get options for select elements
                    if element.tag_name == "select":
                        options = []
                        for option in element.find_elements(By.TAG_NAME, "option"):
                            if option.get_attribute("value"):
                                options.append(
                                    {
                                        "value": option.get_attribute("value"),
                                        "label": option.text.strip(),
                                    }
                                )
                        element_info["options"] = options

                    elements.append(element_info)

        except Exception as e:
            logging.error(f"Error getting form elements: {str(e)}")

        return elements

    def _handle_screening_questions(self) -> bool:
        """Handle any screening questions on the application."""
        try:
            elements = self._get_form_elements()
            if not elements:
                return True
            print(elements)

            for element_info in elements:
                try:
                    ai_response = self._get_ai_form_response(
                        element_info, self.current_tech_stack
                    )
                    if not ai_response:
                        logging.error(
                            f"Failed to get AI response for question: {element_info['question']}"
                        )
                        return False

                    self._apply_ai_response(element_info, ai_response)

                except Exception as e:
                    logging.error(
                        f"Failed to handle question {element_info['question']}: {str(e)}"
                    )
                    return False

            # Click continue/next button if present
            try:
                continue_button = self.driver.find_element(
                    By.CSS_SELECTOR, "[type='submit']"
                )
                continue_button.click()
                return True
            except:
                return True  # No continue button found, might be single page form

        except Exception as e:
            logging.error(f"Failed to handle screening questions: {str(e)}")
            return False

    def _submit_application(self) -> bool:
        """Submit the application after all questions are answered."""
        try:
            # Wait for and click the final submit button
            submit_button = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[type='submit']"))
            )
            submit_button.click()

            # Wait for success indicators
            time.sleep(2)
            success_indicators = [
                "application-success" in self.driver.page_source.lower(),
                "thank you" in self.driver.page_source.lower(),
                "successfully submitted" in self.driver.page_source.lower(),
            ]

            return any(success_indicators)

        except Exception as e:
            logging.error(f"Error during submission: {str(e)}")
            return False

    def apply_to_job(self, job_id: str, job_description: str, tech_stack: str) -> str:
        """Apply to a specific job on Indeed."""
        try:
            if not self.driver:
                self._setup_driver()

            self.current_tech_stack = tech_stack
            self.current_job_description = job_description

            if not self.is_logged_in:
                self._login()

            self._navigate_to_job(job_id)
            self._handle_resume(job_id, tech_stack)

            # Then if the URL is https://smartapply.indeed.com/beta/indeedapply/form/resume-module/relevant-experience OR https://smartapply.indeed.com/beta/indeedapply/form/questions
            if (
                self.driver.current_url
                == "https://smartapply.indeed.com/beta/indeedapply/form/resume-module/relevant-experience"
                or self.driver.current_url
                == "https://smartapply.indeed.com/beta/indeedapply/form/questions"
            ):
                if not self._handle_screening_questions():
                    logging.warning("Issue with screening questions")
                return "FAILED"

            # Submit the application
            if self._submit_application():
                logging.info(f"Successfully applied to job {job_id}")
                return "SUCCESS"
            else:
                logging.warning(f"Application may have failed for job {job_id}")
                return "FAILED"

        except Exception as e:
            logging.error(f"Exception during application for job {job_id}: {str(e)}")
            return "FAILED"

        finally:
            self.current_tech_stack = None
            self.current_job_description = None

    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.is_logged_in = False
