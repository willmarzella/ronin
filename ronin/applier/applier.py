"""Implements the logic to apply to jobs on Seek.com.au"""

import time
from typing import Optional

from loguru import logger
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ronin.ai import AIService
from ronin.applier.base import BaseApplier
from ronin.applier.browser import ChromeDriver
from ronin.applier.cover_letter import CoverLetterGenerator
from ronin.applier.forms import QuestionAnswerHandler
from ronin.config import load_config

try:
    from ronin.profile import load_profile
except ImportError:
    load_profile = None


class SeekApplier(BaseApplier):
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
        self.profile = None
        if load_profile is not None:
            try:
                self.profile = load_profile()
            except Exception as e:
                logger.warning(f"Could not load profile: {e}")
        self.ai_service = AIService()
        self.cover_letter_generator = (
            CoverLetterGenerator()
        )  # Uses Anthropic internally
        self.question_handler = QuestionAnswerHandler(self.ai_service, self.config)
        self.chrome_driver = ChromeDriver()
        self.current_key_tools = None
        self.current_job_description = None
        self.current_resume_profile = None

    @property
    def board_name(self) -> str:
        return "seek"

    def login(self) -> bool:
        """Log in to Seek via the ChromeDriver."""
        self.chrome_driver.initialize()
        return self.chrome_driver.login_seek()

    def _navigate_to_job(self, job_id: str):
        """Navigate to the specific job application page."""
        try:
            url = f"https://www.seek.com.au/job/{job_id}"
            self.chrome_driver.navigate_to(url)

            # Wait a moment for page to load
            time.sleep(2)

            # Check if job is no longer advertised (expired/stale)
            try:
                page_source = self.chrome_driver.driver.page_source
                stale_indicators = [
                    "This job is no longer advertised",
                    "job is no longer advertised",
                    "Jobs remain on SEEK for 30 days",
                    "expiredJobPage",
                ]

                if any(indicator in page_source for indicator in stale_indicators):
                    logger.info(f"Job {job_id} is no longer advertised (STALE)")
                    return "STALE"
            except Exception as e:
                logger.warning(f"Error checking for stale job: {e}")

            # Look for apply button with a short timeout
            try:
                apply_button = WebDriverWait(self.chrome_driver.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-automation='job-detail-apply']")
                    )
                )
                apply_button.click()
            except TimeoutException:
                logger.info(
                    f"No apply button found for job {job_id}, assuming already applied"
                )
                return "APPLIED"

        except Exception as e:
            raise Exception(f"Failed to navigate to job {job_id}: {str(e)}")

    @staticmethod
    def _match_resume_radio(
        radios: list,
        resume_id: str,
        hints: list,
    ) -> Optional[dict]:
        """Pick the resume radio option to select on the apply form.

        Args:
            radios: Parsed options, each ``{"value": uuid, "label": filename,
                "checked": bool}`` (the "Don't include" option is excluded
                upstream).
            resume_id: The registered Seek resume UUID for the chosen profile.
                An exact value match always wins.
            hints: Ordered name fragments (profile name, filename stem) used
                when no UUID is registered or the UUID is not on the form.

        Returns:
            The matching radio dict, or None when nothing matches
            unambiguously — a hint matching several labels is ambiguous and
            never guessed.
        """
        want = str(resume_id or "").strip().lower()
        if want:
            for radio in radios:
                if str(radio.get("value") or "").strip().lower() == want:
                    return radio

        for hint in hints or []:
            token = str(hint or "").strip().lower()
            if not token:
                continue
            hits = [
                radio
                for radio in radios
                if token in str(radio.get("label") or "").lower()
            ]
            if len(hits) == 1:
                return hits[0]
        return None

    def _handle_resume(
        self,
        job_id: str,
        resume_profile: str = "default",
        title: str = "",
        work_type: str = "",
    ):
        """Handle resume selection for Seek applications based on resume profile name."""
        try:
            # Seek replaced the resume <select> dropdown with a radio group
            # (div[data-testid='resumeSelectInput'], inputs named
            # 'document-select'). Wait for the group, not the retired dropdown.
            container = WebDriverWait(self.chrome_driver.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='resumeSelectInput']")
                )
            )

            # Look up seek_resume_id from the profile
            resume_id = None
            selected_profile_name = resume_profile
            if self.profile and self.profile.resumes:
                try:
                    rp = self.profile.get_resume(resume_profile)
                    resume_id = rp.seek_resume_id
                    selected_profile_name = rp.name
                    logger.info(
                        f"Job {job_id}: using resume profile '{resume_profile}' "
                        f"(seek_resume_id={resume_id})"
                    )
                except KeyError:
                    # Profile name not found, use deterministic listing-based fallback.
                    try:
                        rp = self.profile.recommend_resume_for_listing(
                            job_title=title,
                            job_description=self.current_job_description or "",
                            work_type=work_type,
                        )
                    except Exception:
                        rp = self.profile.resumes[0]

                    resume_id = rp.seek_resume_id
                    selected_profile_name = rp.name
                    logger.warning(
                        f"Job {job_id}: resume profile '{resume_profile}' not found, "
                        f"falling back to '{rp.name}' (seek_resume_id={resume_id})"
                    )

            if not resume_id:
                raise ValueError(
                    f"No seek_resume_id resolved for profile '{resume_profile}'. "
                    "Check profile.yaml resumes configuration."
                )

            radios = []
            for inp in container.find_elements(
                By.CSS_SELECTOR, "input[name='document-select'][type='radio']"
            ):
                value = (inp.get_attribute("value") or "").strip()
                if not value or value.lower() == "dont-include":
                    continue
                input_id = inp.get_attribute("id") or ""
                label_text = ""
                if input_id:
                    try:
                        label_el = container.find_element(
                            By.CSS_SELECTOR, f"label[for='{input_id}']"
                        )
                        label_text = " ".join((label_el.text or "").split())
                    except Exception:
                        pass
                radios.append(
                    {
                        "value": value,
                        "label": label_text,
                        "checked": inp.is_selected(),
                        "element": inp,
                        "input_id": input_id,
                    }
                )

            if not radios:
                raise ValueError(
                    "No resume options found in the resumeSelectInput radio group"
                )

            hints = [
                h
                for h in dict.fromkeys([selected_profile_name, resume_profile])
                if h and h != "default"
            ]
            chosen = self._match_resume_radio(
                [{k: r[k] for k in ("value", "label", "checked")} for r in radios],
                resume_id or "",
                hints,
            )
            if chosen is None:
                raise ValueError(
                    f"No resume radio matched seek_resume_id={resume_id!r} or "
                    f"hints {hints!r}. Options: {[r['label'] for r in radios]}"
                )
            target = next(r for r in radios if r["value"] == chosen["value"])

            if not target["checked"]:
                # Inputs are visually hidden; click the label, fall back to a
                # JS click on the input itself.
                clicked = False
                if target["input_id"]:
                    try:
                        self.chrome_driver.driver.find_element(
                            By.CSS_SELECTOR, f"label[for='{target['input_id']}']"
                        ).click()
                        clicked = True
                    except Exception:
                        clicked = False
                if not clicked:
                    self.chrome_driver.driver.execute_script(
                        "arguments[0].click();", target["element"]
                    )
                WebDriverWait(self.chrome_driver.driver, 5).until(
                    lambda _driver: target["element"].is_selected()
                )

            self.current_resume_profile = selected_profile_name
            logger.info(
                f"Job {job_id}: selected resume '{target['label']}' "
                f"(value={target['value']})"
            )

        except Exception as e:
            raise Exception(f"Failed to handle resume for job {job_id}: {str(e)}")

    def _handle_cover_letter(
        self,
        score: int,
        job_description: str,
        title: str,
        company_name: str,
        work_type: str = None,
    ) -> bool:
        """Handle cover letter requirements for Seek applications.

        Returns:
            True if cover letter handled successfully, False if generation failed.
        """
        try:
            # Wait for cover letter options to be present - use the actual name attribute
            WebDriverWait(self.chrome_driver.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[name='coverLetter-method']")
                )
            )

            # Log company name to verify we're using the actual name not ID
            logger.info(f"Generating cover letter for company: {company_name}")

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
                    logger.warning(
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
                        logger.warning(f"Fallback also failed: {e2}")
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
                    key_tools=self.current_resume_profile or "default",
                    work_type=work_type,
                )

                if not cover_letter or "response" not in cover_letter:
                    logger.error(f"Cover letter generation failed for {company_name}")
                    return False

                # Wait for and find the cover letter textarea - use more flexible selector
                cover_letter_input = WebDriverWait(self.chrome_driver.driver, 10).until(
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
                    logger.warning(
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
                        logger.warning(f"Fallback also failed: {e2}")
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
            time.sleep(0.5)

            # Handle selection criteria if present (new Seek feature)
            self._handle_selection_criteria()

            continue_button = self.chrome_driver.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )
            continue_button.click()
            return True

        except Exception as e:
            logger.error(f"Failed to handle cover letter: {str(e)}")
            return False

    def _handle_selection_criteria(self):
        """Handle the selection criteria section if present on the application page."""
        try:
            # Check if selection criteria section exists
            criteria_inputs = self.chrome_driver.driver.find_elements(
                By.CSS_SELECTOR, "input[name='selectionCriteria-method']"
            )

            if not criteria_inputs:
                return  # No selection criteria section

            logger.info(
                "Found selection criteria section, selecting 'Already addressed' option"
            )

            # Select "Already addressed in resumé or cover letter" option
            try:
                none_input = self.chrome_driver.driver.find_element(
                    By.CSS_SELECTOR,
                    "input[data-testid='selectionCriteria-method-none']",
                )
                none_label = self.chrome_driver.driver.find_element(
                    By.CSS_SELECTOR, f"label[for='{none_input.get_attribute('id')}']"
                )
                none_label.click()
                logger.info("Selected 'Already addressed in resumé or cover letter'")
            except Exception as e:
                logger.warning(f"Failed to select 'Already addressed' option: {e}")
                # Fallback: try clicking the input directly
                try:
                    none_input = self.chrome_driver.driver.find_element(
                        By.CSS_SELECTOR,
                        "input[name='selectionCriteria-method'][value='none']",
                    )
                    self.chrome_driver.driver.execute_script(
                        "arguments[0].click();", none_input
                    )
                except Exception as e2:
                    logger.warning(
                        f"Fallback selection criteria click also failed: {e2}"
                    )

            time.sleep(0.3)

        except Exception as e:
            logger.debug(f"Selection criteria handling skipped: {e}")

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

    def _wait_for_form_elements(self) -> bool:
        """Wait for form elements to load on page."""
        assert hasattr(self, "chrome_driver"), "chrome_driver must be initialized"

        try:
            # Just check if we're on the right page, don't extract forms here
            WebDriverWait(self.chrome_driver.driver, 3).until(
                lambda driver: driver.find_elements(
                    By.CSS_SELECTOR, "form input, form select, form textarea"
                )
                or "review" in driver.current_url
            )
            return True
        except TimeoutException:
            logger.info("No screening questions found within timeout")
            return False

    def _check_validation_errors(self) -> bool:
        """Check if form has validation errors."""
        assert hasattr(self, "chrome_driver"), "chrome_driver must be initialized"

        try:
            has_errors = self.question_handler.has_validation_errors(
                self.chrome_driver.driver
            )
            if has_errors:
                logger.warning("Validation errors detected, will retry with context")
            return has_errors
        except Exception as e:
            logger.warning(f"Error checking validation errors: {e}")
            return False

    def _get_form_elements_with_retry(self) -> list:
        """Get form elements with retry logic."""
        assert hasattr(self, "chrome_driver"), "chrome_driver must be initialized"

        elements = self.question_handler.get_form_elements(self.chrome_driver.driver)

        if not elements:
            time.sleep(1)
            elements = self.question_handler.get_form_elements(
                self.chrome_driver.driver
            )

        return elements

    def _fetch_ai_responses_parallel(
        self, elements: list, has_validation_errors: bool
    ) -> dict:
        """Fetch AI responses for all questions in parallel."""
        assert isinstance(elements, list), "elements must be list"
        assert isinstance(
            has_validation_errors, bool
        ), "has_validation_errors must be bool"

        from concurrent.futures import ThreadPoolExecutor, as_completed

        ai_responses = {}
        max_workers = min(len(elements), 5)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {}
            for idx, element_info in enumerate(elements):
                if has_validation_errors:
                    future = executor.submit(
                        self.question_handler.get_ai_form_response_with_validation_context,
                        element_info,
                        self.current_resume_profile or "default",
                        self.current_job_description,
                        True,
                    )
                else:
                    future = executor.submit(
                        self.question_handler.get_ai_form_response,
                        element_info,
                        self.current_resume_profile or "default",
                        self.current_job_description,
                    )
                future_to_idx[future] = idx

            # Collect results
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    ai_responses[idx] = future.result()
                except Exception as e:
                    logger.error(f"Error getting AI response for Q{idx + 1}: {e}")
                    ai_responses[idx] = None

        return ai_responses

    def _apply_responses_to_form(self, elements: list, ai_responses: dict) -> None:
        """Apply AI responses to form elements sequentially."""
        assert isinstance(elements, list), "elements must be list"
        assert isinstance(ai_responses, dict), "ai_responses must be dict"

        max_elements = min(len(elements), 50)  # Limit iterations

        for idx in range(max_elements):
            element_info = elements[idx]

            try:
                ai_response = ai_responses.get(idx)
                if not ai_response:
                    logger.warning(f"No response for: {element_info['question']}")
                    continue

                self.question_handler.apply_ai_response(
                    element_info, ai_response, self.chrome_driver.driver
                )
                logger.debug(f"Applied response for: {element_info['question']}")
            except Exception as e:
                logger.error(f"Failed to handle question: {str(e)}")
                continue

    def _click_continue_button(self) -> bool:
        """Click the continue button to proceed."""
        assert hasattr(self, "chrome_driver"), "chrome_driver must be initialized"

        try:
            # Store current URL to detect page transition
            current_url = self.chrome_driver.current_url

            continue_button = WebDriverWait(self.chrome_driver.driver, 5).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[data-testid='continue-button']")
                )
            )
            continue_button.click()

            # Wait for page transition or URL change
            try:
                WebDriverWait(self.chrome_driver.driver, 10).until(
                    lambda d: d.current_url != current_url
                    or d.find_elements(
                        By.CSS_SELECTOR,
                        "[data-testid='review-submit-application'], [data-testid='submit-application']",
                    )
                )
            except TimeoutException:
                logger.warning("Page did not transition after clicking continue")

            time.sleep(0.5)  # Brief pause for page to settle
            return True
        except TimeoutException:
            logger.error("Timeout waiting for continue button")
            return False

    def _handle_screening_questions(self) -> bool:
        """Handle any screening questions on the application."""
        try:
            # Wait for form elements
            if not self._wait_for_form_elements():
                logger.info("No screening questions found, moving to next step")
                return True

            # Check for validation errors
            has_validation_errors = self._check_validation_errors()

            # Get form elements with retry
            elements = self._get_form_elements_with_retry()
            if not elements:
                logger.info("No form elements after retry, proceeding")
                return True

            logger.debug(f"Processing {len(elements)} screening questions")

            # Fetch AI responses in parallel
            ai_responses = self._fetch_ai_responses_parallel(
                elements, has_validation_errors
            )

            # Apply responses to form
            self._apply_responses_to_form(elements, ai_responses)

            # Wait for form updates
            time.sleep(1)

            # Click continue button
            return self._click_continue_button()

        except Exception as e:
            logger.error(f"Failed to handle screening questions: {str(e)}")
            return False

    def _update_seek_profile(self) -> bool:
        """Update the Seek profile with the latest resume."""
        try:
            WebDriverWait(self.chrome_driver.driver, 1.5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='continue-button']")
                )
            )

            continue_button = self.chrome_driver.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='continue-button']"
            )

            continue_button.click()

            # Reduced wait time - just enough for page transition
            time.sleep(0.5)

            return True
        except Exception as e:
            logger.error(f"Failed to update Seek profile: {str(e)}")
            return False

    def _submit_application(self) -> bool:
        """Submit the application after all questions are answered."""
        try:
            # Store current URL to detect page transition
            pre_submit_url = self.chrome_driver.current_url

            # Handle privacy checkbox if present
            try:
                WebDriverWait(self.chrome_driver.driver, 1.5).until(
                    EC.presence_of_element_located((By.ID, "privacyPolicy"))
                )
                privacy_checkbox = self.chrome_driver.driver.find_element(
                    By.ID, "privacyPolicy"
                )
                if not privacy_checkbox.is_selected():
                    privacy_checkbox.click()
                time.sleep(0.2)
            except TimeoutException:
                pass  # No privacy checkbox, that's fine

            # Try multiple submit button selectors
            submit_button = None
            submit_selectors = [
                "[data-testid='review-submit-application']",
                "[data-testid='submit-application']",
                "button[type='submit']",
            ]

            for selector in submit_selectors:
                try:
                    submit_button = WebDriverWait(self.chrome_driver.driver, 1).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    if submit_button:
                        break
                except Exception:
                    continue

            if not submit_button:
                logger.warning(
                    f"No submit button found. Current URL: {self.chrome_driver.current_url}"
                )
                # Check if we're already on success page
                if self._check_success():
                    return True
                return False

            submit_button.click()

            # Wait for page transition (URL change or success indicators)
            max_wait = 10
            wait_start = time.time()
            while time.time() - wait_start < max_wait:
                if self._check_success():
                    return True
                # Check if URL changed (page transitioned)
                if self.chrome_driver.current_url != pre_submit_url:
                    time.sleep(0.5)  # Brief pause after transition
                    if self._check_success():
                        return True
                time.sleep(0.5)

            # Final check
            return self._check_success()

        except Exception as e:
            logger.warning(f"Issue during submission process: {str(e)}")
            # Even if there was an error, check if we somehow succeeded
            return self._check_success()

    def _check_success(self) -> bool:
        """Check if application was successfully submitted."""
        try:
            current_url = self.chrome_driver.current_url.lower()
            page_source = self.chrome_driver.page_source.lower()

            # Check URL
            if "success" in current_url or "applied" in current_url:
                return True

            # Check page content
            success_phrases = [
                "submitted",
                "application sent",
                "applicationsent",
                "successfully applied",
                "your application has been sent",
            ]
            if any(phrase in page_source for phrase in success_phrases):
                return True

            # Quick DOM check
            self.chrome_driver.driver.implicitly_wait(0.3)
            success_elements = [
                "[id='applicationSent']",
                "[data-testid='application-success']",
                "[data-testid='success-message']",
            ]
            for selector in success_elements:
                if self.chrome_driver.driver.find_elements(By.CSS_SELECTOR, selector):
                    self.chrome_driver.driver.implicitly_wait(10)
                    return True
            self.chrome_driver.driver.implicitly_wait(10)

            return False
        except Exception:
            return False

    def apply_to_job(
        self,
        job_id,
        job_description,
        score,
        key_tools,
        company_name,
        title,
        resume_profile="default",
        work_type=None,
    ):
        """Apply to a specific job on Seek"""
        try:
            # Initialize chrome driver if not already initialized
            self.chrome_driver.initialize()

            self.current_key_tools = key_tools
            self.current_job_description = job_description
            self.current_resume_profile = resume_profile

            # Log to verify we're using the right company name
            logger.info(
                f"Applying to job at company: {company_name} (resume_profile: {resume_profile})"
            )

            if not self.chrome_driver.is_logged_in:
                if not self.chrome_driver.login_seek():
                    raise RuntimeError(
                        "Seek login required (no active session detected)"
                    )

            navigation_result = self._navigate_to_job(job_id)
            if navigation_result == "APPLIED":
                return "APPLIED"
            if navigation_result == "STALE":
                return "STALE"

            self._handle_resume(
                job_id=job_id,
                resume_profile=resume_profile,
                title=title,
                work_type=work_type or "",
            )
            cover_letter_success = self._handle_cover_letter(
                score=score,
                job_description=job_description,
                title=title,
                company_name=company_name,
                work_type=work_type,
            )

            if not cover_letter_success:
                logger.warning(f"Skipping job {job_id} due to cover letter failure")
                return "COVER_LETTER_FAILED"

            # Handle all intermediate pages (screening questions, profile updates)
            max_pages = 5
            for _ in range(max_pages):
                current_url = self.chrome_driver.current_url

                # Check if we're on the review/submit page
                if "review" in current_url:
                    break

                # Handle screening questions page
                if "role-requirements" in current_url:
                    if not self._handle_screening_questions():
                        logger.warning(
                            "Issue with screening questions, but continuing..."
                        )
                    continue

                # Handle profile update page
                if "profile" in current_url:
                    if not self._update_seek_profile():
                        logger.warning("Issue with profile update, but continuing...")
                    continue

                # Unknown page - try clicking continue anyway
                try:
                    continue_btn = self.chrome_driver.driver.find_elements(
                        By.CSS_SELECTOR, "[data-testid='continue-button']"
                    )
                    if continue_btn:
                        continue_btn[0].click()
                        time.sleep(1)
                        continue
                except Exception:
                    pass

                # If URL hasn't changed and no continue button, break
                break

            submission_result = self._submit_application()

            if submission_result:
                logger.info(f"Successfully applied to job {job_id}")
                return "APPLIED"
            else:
                logger.warning(f"Application may have failed for job {job_id}")
                return "APP_ERROR"

        except Exception as e:
            logger.warning(f"Exception during application for job {job_id}: {str(e)}")
            if self.chrome_driver.driver and self._check_success():
                logger.info(f"Application successful despite errors for job {job_id}")
                return "APPLIED"
            return "APP_ERROR"

        finally:
            self.current_key_tools = None
            self.current_job_description = None
            self.current_resume_profile = None

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        self.chrome_driver.cleanup()
