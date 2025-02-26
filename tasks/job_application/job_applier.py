"""Service for applying to jobs."""

import logging
from typing import List, Dict, Any, Optional, Type
from urllib.parse import urlparse
from abc import ABC, abstractmethod
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import re
import time

from services.airtable_service import AirtableManager
from core.config import load_config
from services.ai_service import AIService


class BaseApplier(ABC):
    """Base class for all job board application automation."""

    COMMON_PATTERNS = {
        "years_experience": r"(?i)(how many )?years.*(experience|worked)",
        "salary_expectation": r"(?i)salary.*(expectation|requirement)",
        "start_date": r"(?i)(when|earliest).*(start|commence|begin)",
        "visa_status": r"(?i)(visa|work).*(status|right|permit)",
        "relocation": r"(?i)(willing|able).*(relocate|move)",
    }

    def __init__(self):
        self.config = load_config()
        self.openai_client = OpenAIClient()
        self.driver = None
        self.is_logged_in = False
        self.current_job_data = {}

    def _setup_driver(self):
        if self.driver:
            return

        options = webdriver.ChromeOptions()
        options.add_argument("--remote-debugging-port=9222")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)

        prefs = {
            "profile.default_content_setting_values.notifications": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        options.add_experimental_option("prefs", prefs)

        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            self.driver.set_window_size(1920, 1080)

            self.driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {
                    "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
            )

            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

        except Exception as e:
            raise Exception(f"Failed to initialize Chrome WebDriver: {str(e)}")

    def _analyze_form_context(self, form_element: Any) -> Dict[str, Any]:
        context = {
            "required_fields": [],
            "optional_fields": [],
            "field_patterns": {},
            "validation_rules": {},
            "error_messages": {},
        }

        try:
            required_markers = form_element.find_elements(
                By.CSS_SELECTOR, "[required], [aria-required='true']"
            )
            for marker in required_markers:
                field_id = marker.get_attribute("id")
                if field_id:
                    context["required_fields"].append(field_id)

            input_elements = form_element.find_elements(
                By.CSS_SELECTOR, "input[pattern]"
            )
            for input_elem in input_elements:
                pattern = input_elem.get_attribute("pattern")
                if pattern:
                    context["field_patterns"][input_elem.get_attribute("id")] = pattern

            text_elements = form_element.find_elements(By.CSS_SELECTOR, "[maxlength]")
            for elem in text_elements:
                max_length = elem.get_attribute("maxlength")
                if max_length:
                    context["validation_rules"][elem.get_attribute("id")] = {
                        "max_length": int(max_length)
                    }

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
        question_lower = question.lower()

        for q_type, pattern in self.COMMON_PATTERNS.items():
            if re.search(pattern, question_lower):
                return q_type

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
        start_time = time.time()
        last_exception = None

        while time.time() - start_time < timeout:
            try:
                element = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((by, selector))
                )

                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                    element,
                )
                time.sleep(0.5)

                element = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((by, selector))
                )

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
        try:
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
        try:
            error_messages = form_element.find_elements(
                By.CSS_SELECTOR, ".error, .invalid-feedback, [role='alert']"
            )
            if error_messages:
                for error in error_messages:
                    if error.is_displayed():
                        logging.error(f"Form validation error: {error.text}")
                        return False

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
        pass

    @abstractmethod
    def _navigate_to_job(self, job_id: str):
        pass

    @abstractmethod
    def _handle_resume(self, job_id: str, tech_stack: str):
        pass

    @abstractmethod
    def _handle_cover_letter(
        self,
        score: str = None,
        job_description: str = None,
        title: str = None,
        company_name: str = None,
    ):
        pass

    @abstractmethod
    def _handle_screening_questions(self) -> bool:
        pass

    @abstractmethod
    def _submit_application(self) -> bool:
        pass

    def _get_ai_form_response(
        self, element_info: Dict, tech_stack: str, job_description: str
    ) -> Optional[Dict]:
        try:
            tech_stack = tech_stack.lower()
            if tech_stack not in self.config["resume"]["text"]:
                tech_stack = "aws"

            resume = self.config["resume"]["text"][tech_stack]

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

    def apply_to_job(
        self,
        job_id: str,
        job_description: str,
        score: str = None,
        tech_stack: str = None,
        company_name: str = None,
        title: str = None,
    ) -> str:
        try:
            self._setup_driver()

            self.current_job_data = {
                "id": job_id,
                "description": job_description,
                "tech_stack": tech_stack,
                "score": score,
                "company_name": company_name,
                "title": title,
            }

            if not self.is_logged_in:
                self._login()

            self._navigate_to_job(job_id)

            if self._handle_captcha():
                logging.info("CAPTCHA handled successfully")

            self._handle_resume(job_id, tech_stack)
            self._handle_cover_letter(score, job_description, title, company_name)

            if not self._handle_screening_questions():
                return "NEEDS_MANUAL_APPLICATION"

            if self._submit_application():
                return "SUCCESS"
            return "FAILED"

        except Exception as e:
            raise Exception(f"Error applying to job {job_id}: {str(e)}")
        finally:
            self.current_job_data = {}

    def cleanup(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            finally:
                self.driver = None
                self.is_logged_in = False


class JobApplierService:
    """Service for applying to jobs."""

    def __init__(self, config=None, openai_client=None):
        """Initialize the job applier service.

        Args:
            config: Configuration settings, loaded from config if not provided
            openai_client: OpenAI client instance, created if not provided
        """
        self.config = config or load_config()
        self.openai_client = openai_client or OpenAIClient()
        self.airtable = AirtableManager()

    def _get_job_board_from_url(self, url: str) -> str:
        """Extract job board name from URL."""
        domain = urlparse(url).netloc.lower()

        # Map domains to job board names
        domain_mapping = {
            "seek.com.au": "seek",
            # "boards.greenhouse.io": "greenhouse",
            # "jobs.lever.co": "lever",
            # Add more mappings as needed
        }

        for domain_part, board in domain_mapping.items():
            if domain_part in domain:
                return board

        return "unknown"

    def _get_job_id_from_url(self, url: str, job_board: str) -> str:
        """Extract job ID from URL based on job board."""
        try:
            if job_board == "seek":
                return url.split("/")[-1]
            elif job_board == "indeed":
                # Extract jk parameter from Indeed URL
                # Example URLs:
                # https://au.indeed.com/viewjob?jk=123456789
                # https://au.indeed.com/jobs?q=...&vjk=123456789
                if "jk=" in url:
                    return url.split("jk=")[1].split("&")[0]
                elif "vjk=" in url:
                    return url.split("vjk=")[1].split("&")[0]
                else:
                    logging.warning(f"Could not find job ID in Indeed URL: {url}")
                    return url
            elif job_board == "greenhouse":
                # Example: https://boards.greenhouse.io/company/jobs/123456
                return url.split("/")[-1]
            elif job_board == "lever":
                # Example: https://jobs.lever.co/company/123456
                return url.split("/")[-1]
            else:
                return url  # Return full URL if unknown format
        except Exception as e:
            logging.error(f"Failed to parse job URL {url}: {str(e)}")
            return url

    def process_pending_jobs(self):
        """Process all pending job applications."""
        try:
            # Get jobs that are ready to apply to
            jobs = self.airtable.get_pending_jobs()
            if not jobs:
                logging.info("No jobs to process")
                return

            logging.info(f"Found {len(jobs)} jobs to process")

            # Import here to avoid circular imports
            from tasks.job_application.appliers import JobApplierFactory

            # Group jobs by source to minimize browser sessions
            jobs_by_source = {}
            for job in jobs:
                jobs_by_source.setdefault(job["source"], []).append(job)

            # Process each source's jobs
            for source, source_jobs in jobs_by_source.items():
                applier = None
                try:
                    applier = JobApplierFactory.create_applier(source)
                    if not applier:
                        logging.warning(f"No applier available for source: {source}")
                        continue

                    # Process each job for this source
                    for job in source_jobs:
                        try:
                            logging.info(f"Processing job: {job['title']}")

                            # Apply to the job
                            result = applier.apply_to_job(
                                job_id=job["job_id"],
                                job_description=job["description"],
                                score=job["score"],
                                tech_stack=job["tech_stack"],
                                company_name=job["company"],
                                title=job["title"],
                            )

                            # Update status in Airtable based on result
                            if result == "NEEDS_MANUAL_APPLICATION":
                                self.airtable.update_record(
                                    job["record_id"],
                                    {
                                        "Status": "NEEDS_MANUAL_APPLICATION",
                                        "APP_ERROR": "Job requires manual application due to role requirements",
                                    },
                                )
                                logging.info(
                                    f"Job marked for manual application: {job['title']}"
                                )
                            elif result == "SUCCESS":
                                self.airtable.update_record(
                                    job["record_id"], {"Status": "APPLIED"}
                                )
                                logging.info(
                                    f"Successfully applied to job: {job['title']}"
                                )
                            else:  # FAILED
                                self.airtable.update_record(
                                    job["record_id"], {"Status": "APPLICATION_FAILED"}
                                )
                                logging.error(f"Failed to apply to job: {job['title']}")

                        except Exception as e:
                            logging.error(
                                f"Error processing job {job['title']}: {str(e)}"
                            )
                            self.airtable.update_record(
                                job["record_id"], {"Status": "APPLICATION_FAILED"}
                            )
                            continue

                finally:
                    # Clean up the applier for this source
                    if applier:
                        applier.cleanup()

        except Exception as e:
            logging.error(f"Error in process_pending_jobs: {str(e)}")
            raise

        logging.info("Finished processing all pending jobs")
