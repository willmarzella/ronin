"""Implements the logic to apply to jobs on Seek.com.au"""

from typing import Dict, Optional
import logging
import time
import os

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import Select

from services.airtable_service import AirtableManager
from services.ai_service import AIService
from core.config import load_config
from tasks.job_application.cover_letter import CoverLetterGenerator
from tasks.job_application.question_answer import QuestionAnswerHandler
from tasks.job_application.chrome import ChromeDriver


class SeekApplier:
    """Handles job applications on Seek.com.au."""

    COMMON_PATTERNS = {
        "START_POSITION": ["Start", "start date", "earliest"],
        "CURRENT_ROLE": ["current role", "current job", "employed", "role now"],
        "YEARS_EXPERIENCE": [
            "years of experience",
            "years experience",
            "how many years",
        ],
        "QUALIFICATIONS": ["qualifications", "degrees", "certifications"],
        "SKILLS": ["skills", "skillset", "proficient", "expertise"],
        "VISA": ["visa", "citizen", "permanent resident", "right to work"],
        "WORK_RIGHTS": [
            "work rights",
            "entitled to work",
            "legally work",
            "working rights",
        ],
        "NOTICE_PERIOD": ["notice period", "notice"],
        "CLEARANCE": ["security clearance", "clearance check", "clearance"],
        "CHECKS": ["background check", "police check", "criminal", "check"],
        "LICENSE": ["drivers licence", "driving license", "driver's license", "drive"],
        "SALARY": [
            "salary expectations",
            "expected salary",
            "remuneration",
            "pay expectations",
        ],
        "BENEFITS": ["benefit", "perks", "incentives"],
        "RELOCATE": ["relocate", "relocation", "moving", "move to"],
        "REMOTE": ["remote", "work from home", "wfh", "home based"],
        "TRAVEL": ["travel", "traveling", "trips"],
        "CONTACT": ["contact", "reach you", "phone number"],
    }

    def __init__(self):
        self.config = load_config()
        self.aws_resume_id = self.config["resume"]["preferences"]["aws_resume_id"]
        self.azure_resume_id = self.config["resume"]["preferences"]["azure_resume_id"]
        self.airtable = AirtableManager()
        self.ai_service = AIService()
        self.cover_letter_generator = CoverLetterGenerator(self.ai_service)
        self.question_handler = QuestionAnswerHandler(self.ai_service, self.config)
        self.chrome_driver = ChromeDriver()
        self.current_tech_stack = None
        self.current_job_description = None

    def _navigate_to_job(self, job_id: str):
        """Navigate to the specific job application page."""
        try:
            url = f"https://www.seek.com.au/job/{job_id}"
            self.chrome_driver.navigate_to(url)

            # Look for apply button with a short timeout
            try:
                apply_button = WebDriverWait(self.chrome_driver.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-automation='job-detail-apply']")
                    )
                )
                apply_button.click()
            except TimeoutException:
                logging.info(
                    f"No apply button found for job {job_id}, assuming already applied"
                )
                return "APPLIED"

        except Exception as e:
            raise Exception(f"Failed to navigate to job {job_id}: {str(e)}")

    def _handle_resume(self, job_id: str, tech_stack: str):
        """Handle resume selection for Seek applications."""
        try:
            WebDriverWait(self.chrome_driver.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='select-input']")
                )
            )

            resume_id = self.aws_resume_id
            if "azure" in tech_stack.lower():
                resume_id = self.azure_resume_id

            resume_select = Select(
                self.chrome_driver.driver.find_element(
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
            # Wait for cover letter options to be present - use the actual name attribute
            WebDriverWait(self.chrome_driver.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[name='coverLetter-method']")
                )
            )

            # Log company name to verify we're using the actual name not ID
            logging.info(f"Generating cover letter for company: {company_name}")

            if score and score > 60:
                # Find the "Write a cover letter" radio button using data-testid
                try:
                    write_cover_letter_input = self.chrome_driver.driver.find_element(
                        By.CSS_SELECTOR,
                        "input[data-testid='coverLetter-method-change']",
                    )
                    # Click the label associated with this input
                    write_cover_letter_label = self.chrome_driver.driver.find_element(
                        By.CSS_SELECTOR,
                        f"label[for='{write_cover_letter_input.get_attribute('id')}']",
                    )
                    write_cover_letter_label.click()
                except Exception as e:
                    logging.warning(
                        f"Failed to find 'Write a cover letter' option using data-testid: {e}"
                    )
                    # Fallback: try to find by text content
                    try:
                        write_cover_letter = self.chrome_driver.driver.find_element(
                            By.XPATH,
                            "//label[contains(text(), 'Write a cover letter')]",
                        )
                        write_cover_letter.click()
                    except Exception as e2:
                        logging.warning(f"Fallback also failed: {e2}")
                        # Last resort: try to find by value
                        change_input = self.chrome_driver.driver.find_element(
                            By.CSS_SELECTOR,
                            "input[name='coverLetter-method'][value='change']",
                        )
                        change_label = self.chrome_driver.driver.find_element(
                            By.CSS_SELECTOR,
                            f"label[for='{change_input.get_attribute('id')}']",
                        )
                        change_label.click()

                # Generate cover letter using the CoverLetterGenerator
                cover_letter = self.cover_letter_generator.generate_cover_letter(
                    job_description=job_description,
                    title=title,
                    company_name=company_name,
                    tech_stack=self.current_tech_stack or "aws",
                )

                if cover_letter:
                    # Wait for and find the cover letter textarea - use more flexible selector
                    cover_letter_input = WebDriverWait(
                        self.chrome_driver.driver, 10
                    ).until(
                        EC.presence_of_element_located(
                            (
                                By.CSS_SELECTOR,
                                "textarea[data-testid='coverLetterTextInput']",
                            )
                        )
                    )
                    cover_letter_input.clear()
                    cover_letter_input.send_keys(cover_letter["response"])
            else:
                # Find the "Don't include a cover letter" radio button
                try:
                    no_cover_input = self.chrome_driver.driver.find_element(
                        By.CSS_SELECTOR, "input[data-testid='coverLetter-method-none']"
                    )
                    # Click the label associated with this input
                    no_cover_label = self.chrome_driver.driver.find_element(
                        By.CSS_SELECTOR,
                        f"label[for='{no_cover_input.get_attribute('id')}']",
                    )
                    no_cover_label.click()
                except Exception as e:
                    logging.warning(
                        f"Failed to find 'Don't include a cover letter' option using data-testid: {e}"
                    )
                    # Fallback: try to find by text content
                    try:
                        no_cover_select = self.chrome_driver.driver.find_element(
                            By.XPATH,
                            '//label[contains(text(), "Don\'t include a cover letter")]',
                        )
                        no_cover_select.click()
                    except Exception as e2:
                        logging.warning(f"Fallback also failed: {e2}")
                        # Last resort: try to find by value
                        none_input = self.chrome_driver.driver.find_element(
                            By.CSS_SELECTOR,
                            "input[name='coverLetter-method'][value='none']",
                        )
                        none_label = self.chrome_driver.driver.find_element(
                            By.CSS_SELECTOR,
                            f"label[for='{none_input.get_attribute('id')}']",
                        )
                        none_label.click()

            # Wait a moment for the form to update
            time.sleep(1)

            continue_button = self.chrome_driver.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )
            continue_button.click()

        except Exception as e:
            raise Exception(f"Failed to handle cover letter: {str(e)}")

    def _get_element_label(self, element) -> Optional[str]:
        """Get the question/label text for a form element."""
        try:
            element_id = element.get_attribute("id")
            if element_id:
                label = self.chrome_driver.driver.find_element(
                    By.CSS_SELECTOR, f'label[for="{element_id}"]'
                )
                if label:
                    return label.text.strip()

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

    def _handle_screening_questions(self) -> bool:
        """Handle any screening questions on the application."""
        try:
            print("On screening questions page")
            try:
                WebDriverWait(self.chrome_driver.driver, 3).until(
                    lambda driver: len(self.question_handler.get_form_elements(driver))
                    > 0
                    or "review" in driver.current_url
                )
            except TimeoutException:
                logging.info(
                    "No screening questions found within timeout, moving to next step"
                )
                return True

            elements = self.question_handler.get_form_elements(
                self.chrome_driver.driver
            )
            print(f"Found {len(elements)} elements")
            if not elements:
                return True

            for element_info in elements:
                print(f"Processing question: {element_info}")
                try:
                    ai_response = self.question_handler.get_ai_form_response(
                        element_info,
                        self.current_tech_stack,
                        self.current_job_description,
                    )

                    print(f"AI response: {ai_response}")

                    if not ai_response:
                        logging.warning(
                            f"No response for question: {element_info['question']}"
                        )
                        continue

                    self.question_handler.apply_ai_response(
                        element_info, ai_response, self.chrome_driver.driver
                    )
                    print(f"Applied {element_info['question']} with {ai_response}")

                except Exception as e:
                    logging.error(
                        f"Failed to handle question {element_info['question']}: {str(e)}"
                    )
                    continue

            try:
                continue_button = WebDriverWait(self.chrome_driver.driver, 3).until(
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

    def _update_seek_profile(self) -> bool:
        """Update the Seek profile with the latest resume."""
        try:
            print("On update seek Profile page")

            WebDriverWait(self.chrome_driver.driver, 1.5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='continue-button']")
                )
            )

            continue_button = self.chrome_driver.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )

            continue_button.click()

            print("Clicked continue button")

            time.sleep(2)

            return True
        except Exception as e:
            logging.error(f"Failed to update Seek profile: {str(e)}")
            return False

    def _submit_application(self) -> bool:
        """Submit the application after all questions are answered."""
        try:
            print("On final review page")

            try:
                WebDriverWait(self.chrome_driver.driver, 1.5).until(
                    EC.presence_of_element_located((By.ID, "privacyPolicy"))
                )
                privacy_checkbox = self.chrome_driver.driver.find_element(
                    By.ID, "privacyPolicy"
                )
                if not privacy_checkbox.is_selected():
                    print("Clicking privacy checkbox")
                    privacy_checkbox.click()
                time.sleep(0.2)
            except TimeoutException:
                logging.info("No privacy checkbox found, moving to submission")

            WebDriverWait(self.chrome_driver.driver, 1.5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='review-submit-application']")
                )
            )

            submit_button = self.chrome_driver.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='review-submit-application']"
            )
            submit_button.click()

            print("Clicked final submit button")

            if "success" in self.chrome_driver.current_url:
                return True

            if "submitted" in self.chrome_driver.page_source.lower():
                return True

            success_elements = [
                bool(
                    self.chrome_driver.driver.find_elements(
                        By.CSS_SELECTOR, "[id='applicationSent']"
                    )
                ),
                bool(
                    self.chrome_driver.driver.find_elements(
                        By.CSS_SELECTOR, "[data-testid='application-success']"
                    )
                ),
            ]

            return any(success_elements)

        except Exception as e:
            logging.warning(f"Issue during submission process: {str(e)}")
            return "success" in self.chrome_driver.current_url

    def apply_to_job(
        self, job_id, job_description, score, tech_stack, company_name, title
    ):
        """Apply to a specific job on Seek"""
        try:
            # Initialize chrome driver if not already initialized
            self.chrome_driver.initialize()

            self.current_tech_stack = tech_stack
            self.current_job_description = job_description

            # Log to verify we're using the right company name
            logging.info(f"Applying to job at company: {company_name}")

            if not self.chrome_driver.is_logged_in:
                self.chrome_driver.login_seek()

            navigation_result = self._navigate_to_job(job_id)
            if navigation_result == "APPLIED":
                return "APPLIED"

            self._handle_resume(job_id, tech_stack)
            self._handle_cover_letter(
                score=score,
                job_description=job_description,
                title=title,
                company_name=company_name,
            )

            if "role-requirements" in self.chrome_driver.current_url:
                if not self._handle_screening_questions():
                    logging.warning("Issue with screening questions, but continuing...")

            self._update_seek_profile()
            submission_result = self._submit_application()

            if submission_result:
                logging.info(f"Successfully applied to job {job_id}")
                return "APPLIED"
            else:
                logging.warning(f"Application may have failed for job {job_id}")
                return "APP_ERROR"

        except Exception as e:
            logging.warning(f"Exception during application for job {job_id}: {str(e)}")
            if self.chrome_driver.driver and any(
                [
                    "success" in self.chrome_driver.current_url,
                    bool(
                        self.chrome_driver.driver.find_elements(
                            By.CSS_SELECTOR, "[id='applicationSent']"
                        )
                    ),
                    bool(
                        self.chrome_driver.driver.find_elements(
                            By.CSS_SELECTOR, "[data-testid='application-success']"
                        )
                    ),
                    "submitted" in self.chrome_driver.page_source.lower(),
                ]
            ):
                logging.info(f"Application successful despite errors for job {job_id}")
                return "APPLIED"
            return "APP_ERROR"

        finally:
            self.current_tech_stack = None
            self.current_job_description = None

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        self.chrome_driver.cleanup()
