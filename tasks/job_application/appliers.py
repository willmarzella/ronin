"""Implements the logic to apply to jobs on Seek.com.au"""

from typing import Dict, Optional
import logging
import time

from selenium import webdriver
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
        self.driver = None
        self.is_logged_in = False
        self.current_tech_stack = None
        self.current_job_description = None

    def _setup_driver(self):
        """Initialize Chrome WebDriver with local browser"""
        if self.driver:
            return

        options = webdriver.ChromeOptions()
        options.add_argument("--remote-debugging-port=9222")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)

        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
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

            # Look for apply button with a short timeout
            try:
                apply_button = WebDriverWait(self.driver, 5).until(
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
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='select-input']")
                )
            )

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
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[for='coverLetter-method-:r4:_2']")
                )
            )

            if score and score > 60:
                add_cover_letter = self.driver.find_element(
                    By.CSS_SELECTOR, "[for='coverLetter-method-:r4:_1']"
                )
                add_cover_letter.click()

                # Generate cover letter using the CoverLetterGenerator
                cover_letter = self.cover_letter_generator.generate_cover_letter(
                    job_description=job_description,
                    title=title,
                    company_name=company_name,
                    tech_stack=self.current_tech_stack or "aws",
                )

                if cover_letter:
                    cover_letter_input = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.ID, "coverLetter-text-:r6:"))
                    )
                    cover_letter_input.clear()
                    cover_letter_input.send_keys(cover_letter["response"])
            else:
                no_cover_select = self.driver.find_element(
                    By.CSS_SELECTOR, "[for='coverLetter-method-:r4:_2']"
                )
                no_cover_select.click()

            continue_button = self.driver.find_element(
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
                label = self.driver.find_element(
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
                WebDriverWait(self.driver, 3).until(
                    lambda driver: len(self.question_handler.get_form_elements(driver))
                    > 0
                    or "review" in driver.current_url
                )
            except TimeoutException:
                logging.info(
                    "No screening questions found within timeout, moving to next step"
                )
                return True

            elements = self.question_handler.get_form_elements(self.driver)
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
                        element_info, ai_response, self.driver
                    )
                    print(f"Applied {element_info['question']} with {ai_response}")

                except Exception as e:
                    logging.error(
                        f"Failed to handle question {element_info['question']}: {str(e)}"
                    )
                    continue

            try:
                continue_button = WebDriverWait(self.driver, 3).until(
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
            time.sleep(2)
            print("On update seek Profile page")

            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='continue-button']")
                )
            )

            continue_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )
            continue_button.click()

            print("Clicked continue button")

            time.sleep(2)

            print("On final review page")

            try:
                WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.ID, "privacyPolicy"))
                )
                privacy_checkbox = self.driver.find_element(By.ID, "privacyPolicy")
                if not privacy_checkbox.is_selected():
                    print("Clicking privacy checkbox")
                    privacy_checkbox.click()
                time.sleep(0.5)
            except TimeoutException:
                logging.info("No privacy checkbox found, moving to submission")

            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='review-submit-application']")
                )
            )

            submit_button = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='review-submit-application']"
            )
            submit_button.click()

            print("Clicked final submit button")

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

            self.current_tech_stack = tech_stack
            self.current_job_description = job_description

            if not self.is_logged_in:
                self._login()

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

            if "role-requirements" in self.driver.current_url:
                if not self._handle_screening_questions():
                    logging.warning("Issue with screening questions, but continuing...")

            submission_result = self._submit_application()

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
                return "APPLIED"

            if not submission_result:
                logging.warning(f"Application may have failed for job {job_id}")
                return "APP_ERROR"

            return "APPLIED"

        except Exception as e:
            logging.warning(f"Exception during application for job {job_id}: {str(e)}")
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
                return "APPLIED"
            return "APP_ERROR"

        finally:
            self.current_tech_stack = None
            self.current_job_description = None

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.is_logged_in = False
