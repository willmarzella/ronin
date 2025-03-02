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


class SeekApplier:
    """Handles job applications on Seek.com.au."""

    COMMON_PATTERNS = {
        "years_experience": r"(?i)(how many )?years.*(experience|worked)",
        "salary_expectation": r"(?i)salary.*(expectation|requirement)",
        "start_date": r"(?i)(when|earliest).*(start|commence|begin)",
        "visa_status": r"(?i)(visa|work).*(status|right|permit)",
        "relocation": r"(?i)(willing|able).*(relocate|move)",
    }

    def __init__(self):
        self.config = load_config()
        self.aws_resume_id = self.config["resume"]["preferences"]["aws_resume_id"]
        self.azure_resume_id = self.config["resume"]["preferences"]["azure_resume_id"]
        self.airtable = AirtableManager()
        self.ai_service = AIService()
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

                with open("assets/cover_letter_example.txt", "r") as f:
                    cover_letter_example = f.read()

                # Load tech stack-specific resume text
                tech_stack = (
                    self.current_tech_stack.lower()
                    if self.current_tech_stack
                    else "aws"
                )

                # Get resume text from tech stack-specific file in assets/cv directory
                resume_text = ""
                cv_file_path = f"assets/cv/{tech_stack}.txt"

                try:
                    # First, try to find a tech stack-specific resume in assets/cv directory
                    with open(cv_file_path, "r") as f:
                        resume_text = f.read()
                        logging.info(
                            f"Using tech stack-specific resume from {cv_file_path}"
                        )
                except FileNotFoundError:
                    # If not found in assets/cv, check config
                    if tech_stack in self.config["resume"]["text"]:
                        if "file_path" in self.config["resume"]["text"][tech_stack]:
                            resume_file_path = self.config["resume"]["text"][
                                tech_stack
                            ]["file_path"]
                            try:
                                with open(resume_file_path, "r") as f:
                                    resume_text = f.read()
                                    logging.info(
                                        f"Using resume from config file_path: {resume_file_path}"
                                    )
                            except Exception as e:
                                logging.error(
                                    f"Failed to read resume file {resume_file_path}: {str(e)}"
                                )
                        else:
                            # Use text directly from config if available
                            resume_text = self.config["resume"]["text"][tech_stack].get(
                                "content", ""
                            )
                            if resume_text:
                                logging.info(
                                    f"Using resume content from config for {tech_stack}"
                                )

                    # If still no resume text, fall back to default "aws" tech stack or default file
                    if not resume_text and tech_stack != "aws":
                        try:
                            with open("assets/cv/aws.txt", "r") as f:
                                resume_text = f.read()
                                logging.info("Falling back to aws resume in assets/cv")
                        except FileNotFoundError:
                            logging.warning(
                                f"No resume found for tech stack {tech_stack} in assets/cv, using default"
                            )

                    # Last resort: fall back to default resume file
                    if not resume_text:
                        try:
                            with open("assets/resume.txt", "r") as f:
                                resume_text = f.read()
                                logging.info("Using default resume.txt file")
                        except FileNotFoundError:
                            logging.error("Default resume.txt not found!")
                            resume_text = "Resume information not available."

                system_prompt = f"""You are a professional cover letter writer. Write a concise, compelling cover letter for the following job. 
                    The letter should highlight relevant experience from my resume and demonstrate enthusiasm for the role. Use the example cover letter below to guide your writing. My name is William Marzella. Also a lot of the time the job description will be from a recruiting agency recruiting on behalf of a client. In this case, you should tailor the letter to the client, not the recruiting agency. Obviosly address the recruiting agency in the letter. And usually at the end of the job description there'll be the recruiters name or email address (in which you can usually find their name). You should address the letter to them.
                    Keep the tone professional but conversational and personable. Maximum 250 words.

                    My resume: {resume_text}
                    
                    Example cover letter: {cover_letter_example}
                    
                    -----
                    
                     Your response should be in valid JSON format:
                    
                    {{"response": "cover letter text"}}
                    
                    -----   
                    
                    """

                user_message = f"Write a cover letter for the job of {title} at {company_name}: {job_description}"

                cover_letter = self.ai_service.chat_completion(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    temperature=0.7,
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

    def _get_ai_form_response(self, element_info, tech_stack):
        """Get AI response for a form element"""
        try:
            tech_stack = tech_stack.lower()

            system_prompt = f"""You are a professional job applicant assistant helping me apply to the following job(s) with keywords: {self.config["search"]["keywords"]}. I am an Australian citizen with full working rights. I have a drivers license. I am willing to undergo police checks if necessary. I do NOT have any security clearances (TSPV, NV1, NV2, Top Secret, etc) but am willing to undergo them if necessary. My salary expectations are $150,000 - $200,000, based on the job description you can choose to apply for a higher or lower salary. Based on my resume below, provide concise, relevant, and professional answers to job application questions. Note that some jobs might not exactly fit the keywords, but you should still apply if you think you're a good fit. This means using the options for answering questions correctly. DO NOT make up values or IDs that are not present in the options provided.
You MUST return your response in valid JSON format with fields that match the input type:
- For textareas: {{"response": "your detailed answer"}}
- For radios: {{"selected_option": "id of the option to select"}}
- For checkboxes: {{"selected_options": ["id1", "id2", ...]}}
- For selects: {{"selected_option": "value of the option to select"}}

For radio and checkbox inputs, ONLY return the exact ID from the options provided, not the label. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM.
For select inputs, ONLY return the exact value attribute from the options provided, not the label. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM.
For textareas, keep responses under 100 words and ensure it's properly escaped for JSON. IF YOU CANNOT FIND THE ANSWER OR ARE NOT SURE, RETURN "N/A".
Always ensure your response is valid JSON and contains the expected fields. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED."""

            # Get resume text from tech stack-specific file in assets/cv directory
            resume_text = ""
            cv_file_path = f"assets/cv/{tech_stack}_resume.txt"

            try:
                # First, try to find a tech stack-specific resume in assets/cv directory
                with open(cv_file_path, "r") as f:
                    resume_text = f.read()
                    logging.info(
                        f"Using tech stack-specific resume from {cv_file_path}"
                    )
            except FileNotFoundError:
                # If not found in assets/cv, check config
                if tech_stack in self.config["resume"]["text"]:
                    if "file_path" in self.config["resume"]["text"][tech_stack]:
                        resume_file_path = self.config["resume"]["text"][tech_stack][
                            "file_path"
                        ]
                        try:
                            with open(resume_file_path, "r") as f:
                                resume_text = f.read()
                                logging.info(
                                    f"Using resume from config file_path: {resume_file_path}"
                                )
                        except Exception as e:
                            logging.error(
                                f"Failed to read resume file {resume_file_path}: {str(e)}"
                            )
                    else:
                        # Use text directly from config if available
                        resume_text = self.config["resume"]["text"][tech_stack].get(
                            "content", ""
                        )
                        if resume_text:
                            logging.info(
                                f"Using resume content from config for {tech_stack}"
                            )

                # If still no resume text, fall back to default "aws" tech stack or default file
                if not resume_text and tech_stack != "aws":
                    try:
                        with open("assets/cv/aws_resume.txt", "r") as f:
                            resume_text = f.read()
                            logging.info("Falling back to aws resume in assets/cv")
                    except FileNotFoundError:
                        logging.warning(
                            f"No resume found for tech stack {tech_stack} in assets/cv, using default"
                        )

                # Last resort: fall back to default resume file
                if not resume_text:
                    try:
                        with open("assets/resume.txt", "r") as f:
                            resume_text = f.read()
                            logging.info("Using default resume.txt file")
                    except FileNotFoundError:
                        logging.error("Default resume.txt not found!")
                        resume_text = "Resume information not available."

            system_prompt += f"\n\nMy resume: {resume_text}"

            user_message = f"Question: {element_info['question']}\nInput type: {element_info['type']}\n"

            if element_info["type"] == "select":
                options_str = "\n".join(
                    [
                        f"- {opt['label']} (value: {opt['value']})"
                        for opt in element_info["options"]
                    ]
                )
                user_message += f"\nAvailable options:\n{options_str}"

            elif element_info["type"] in ["radio", "checkbox"]:
                options_str = "\n".join(
                    [
                        f"- {opt['label']} (id: {opt['id']})"
                        for opt in element_info["options"]
                    ]
                )
                user_message += f"\nAvailable options:\n{options_str}"

            if element_info["type"] == "select":
                user_message += "\n\nIMPORTANT: Return ONLY the exact value from the options, not the label. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM."
            elif element_info["type"] in ["radio", "checkbox"]:
                user_message += "\n\nIMPORTANT: Return ONLY the exact ID of the option you want to select. DO NOT MAKE UP VALUES OR IDs THAT ARE NOT PRESENT IN THE OPTIONS PROVIDED. SOME OF THE OPTIONS MIGHT NOT HAVE A VALUE ATTRIBUTE DO NOT MAKE UP VALUES FOR THEM."
            elif element_info["type"] == "textarea":
                user_message += "\n\nIMPORTANT: Keep your response under 100 words and ensure it's properly escaped for JSON."

            if hasattr(self, "current_job_description"):
                user_message += f"\n\nJob Context: {self.current_job_description}"

            response = self.ai_service.chat_completion(
                system_prompt=system_prompt, user_message=user_message, temperature=0.3
            )

            if not response:
                logging.error("No response received from OpenAI")
                return None

            logging.info(f"AI response for {element_info['type']}: {response}")

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

            if element_info["type"] == "textarea" and "response" in response:
                import json

                response["response"] = json.loads(json.dumps(response["response"]))

            return response

        except Exception as e:
            logging.error(f"Error getting AI response: {str(e)}")
            return None

    def _get_form_elements(self):
        """Get all form elements that need to be filled."""
        elements = []

        forms = self.driver.find_elements(By.TAG_NAME, "form")
        for form in forms:
            try:
                checkbox_groups = {}

                checkbox_containers = form.find_elements(
                    By.XPATH,
                    ".//fieldset[.//input[@type='checkbox']] | .//div[.//strong and .//input[@type='checkbox']]",
                )

                for container in checkbox_containers:
                    question = None
                    try:
                        question = container.find_element(
                            By.XPATH, ".//legend//strong | .//strong"
                        ).text.strip()
                    except:
                        headings = container.find_elements(
                            By.XPATH,
                            "./preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6][1]",
                        )
                        if headings:
                            question = headings[0].text.strip()

                    if not question:
                        continue

                    checkboxes = container.find_elements(
                        By.CSS_SELECTOR, 'input[type="checkbox"]'
                    )
                    if not checkboxes:
                        continue

                    name = checkboxes[0].get_attribute("name")
                    if not name:
                        continue

                    checkbox_groups[name] = {
                        "element": checkboxes[0],
                        "type": "checkbox",
                        "question": question,
                        "options": [],
                    }

                    for checkbox in checkboxes:
                        label_text = ""
                        try:
                            checkbox_id = checkbox.get_attribute("id")
                            if checkbox_id:
                                label = container.find_element(
                                    By.CSS_SELECTOR, f'label[for="{checkbox_id}"]'
                                )
                                label_text = label.text.strip()
                        except:
                            try:
                                label = checkbox.find_element(
                                    By.XPATH,
                                    "ancestor::label | following-sibling::label",
                                )
                                label_text = label.text.strip()
                            except:
                                label_text = checkbox.find_element(
                                    By.XPATH, "following::text()[1]"
                                ).strip()

                        checkbox_groups[name]["options"].append(
                            {
                                "id": checkbox.get_attribute("id"),
                                "label": label_text,
                            }
                        )

                elements.extend(checkbox_groups.values())

                radio_groups = {}
                radios = form.find_elements(By.CSS_SELECTOR, 'input[type="radio"]')

                for radio in radios:
                    name = radio.get_attribute("name")
                    if not name:
                        continue

                    question = None
                    try:
                        fieldset = radio.find_element(By.XPATH, "ancestor::fieldset")
                        question = fieldset.find_element(
                            By.XPATH, ".//legend//strong | .//strong"
                        ).text.strip()
                    except:
                        try:
                            parent_div = radio.find_element(
                                By.XPATH, "ancestor::div[.//strong][1]"
                            )
                            question = parent_div.find_element(
                                By.TAG_NAME, "strong"
                            ).text.strip()
                        except:
                            continue

                    if name not in radio_groups:
                        radio_groups[name] = {
                            "element": radio,
                            "type": "radio",
                            "question": question,
                            "options": [],
                        }

                    label_text = ""
                    try:
                        radio_id = radio.get_attribute("id")
                        if radio_id:
                            label = form.find_element(
                                By.CSS_SELECTOR, f'label[for="{radio_id}"]'
                            )
                            label_text = label.text.strip()
                    except:
                        try:
                            label = radio.find_element(
                                By.XPATH, "ancestor::label | following-sibling::label"
                            )
                            label_text = label.text.strip()
                        except:
                            label_text = radio.find_element(
                                By.XPATH, "following::text()[1]"
                            ).strip()

                    radio_groups[name]["options"].append(
                        {
                            "id": radio.get_attribute("id"),
                            "label": label_text,
                        }
                    )

                elements.extend(radio_groups.values())

                for element in form.find_elements(
                    By.CSS_SELECTOR,
                    "input:not([type='checkbox']):not([type='radio']):not([type='hidden']):not([type='submit']):not([type='button']), select, textarea",
                ):
                    element_type = element.get_attribute("type")
                    if element_type == "select-one":
                        element_type = "select"

                    label = None
                    try:
                        element_id = element.get_attribute("id")
                        if element_id:
                            label = form.find_element(
                                By.CSS_SELECTOR, f'label[for="{element_id}"]'
                            )
                    except:
                        try:
                            label = element.find_element(
                                By.XPATH,
                                "ancestor::label | preceding-sibling::label[1]",
                            )
                        except:
                            try:
                                label = element.find_element(
                                    By.XPATH,
                                    "./preceding::*[self::strong or self::label or contains(@class, 'label')][1]",
                                )
                            except:
                                continue

                    if not label:
                        continue

                    element_info = {
                        "element": element,
                        "type": element_type or element.tag_name,
                        "question": label.text.strip(),
                    }

                    if element.tag_name == "select":
                        options = []
                        for option in element.find_elements(By.TAG_NAME, "option"):
                            value = option.get_attribute("value")
                            if value:
                                options.append(
                                    {
                                        "value": value,
                                        "label": option.text.strip(),
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
                name = element.get_attribute("name")
                form = element.find_element(By.XPATH, "ancestor::form")
                checkboxes = form.find_elements(
                    By.CSS_SELECTOR, f'input[type="checkbox"][name="{name}"]'
                )

                desired_ids = set(ai_response["selected_options"])

                for checkbox in checkboxes:
                    checkbox_id = checkbox.get_attribute("id")
                    is_selected = checkbox.is_selected()
                    should_be_selected = checkbox_id in desired_ids

                    if is_selected != should_be_selected:
                        checkbox.click()

            elif element_info["type"] == "select":
                select = Select(element)
                select.select_by_value(ai_response["selected_option"])

            else:
                element.clear()
                element.send_keys(ai_response["response"])

        except Exception as e:
            raise Exception(f"Failed to apply AI response: {str(e)}")

    def _handle_screening_questions(self) -> bool:
        """Handle any screening questions on the application."""
        try:
            print("On screening questions page")
            try:
                WebDriverWait(self.driver, 3).until(
                    lambda driver: len(self._get_form_elements()) > 0
                    or "review" in driver.current_url
                )
            except TimeoutException:
                logging.info(
                    "No screening questions found within timeout, moving to next step"
                )
                return True

            elements = self._get_form_elements()
            print(f"Found {len(elements)} elements")
            if not elements:
                return True

            for element_info in elements:
                print(f"Processing question: {element_info}")
                try:
                    ai_response = self._get_ai_form_response(
                        element_info, self.current_tech_stack
                    )

                    print(f"AI response: {ai_response}")

                    if not ai_response:
                        logging.warning(
                            f"No response for question: {element_info['question']}"
                        )
                        continue

                    self._apply_ai_response(element_info, ai_response)
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
