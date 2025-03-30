"""Question answering functionality for job application forms."""

import logging
import json
from typing import Dict, List, Optional, Any

from blocks.ai_service import AIService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select


class QuestionAnswerHandler:
    """Handles the answering of questions in job application forms using AI."""

    def __init__(
        self, ai_service: Optional[AIService] = None, config: Optional[Dict] = None
    ):
        """
        Initialize the question answer handler.

        Args:
            ai_service: An instance of AIService. If None, a new instance will be created.
            config: Configuration dictionary. If None, will be loaded from config.
        """
        self.ai_service = ai_service or AIService()

        if config is None:
            from utils.config import load_config

            self.config = load_config()
        else:
            self.config = config

    def get_ai_form_response(
        self, element_info: Dict, tech_stack: str, job_description: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get AI-generated response for a form element.

        Args:
            element_info: Dictionary containing information about the form element
            tech_stack: The tech stack for the job
            job_description: The job description text (optional)

        Returns:
            Dictionary containing the AI-generated response for the form element or None if generation failed.
        """
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

            # Get resume text based on tech stack
            resume_text = self._get_resume_text(tech_stack)

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

            if job_description:
                user_message += f"\n\nJob Context: {job_description}"

            response = self.ai_service.chat_completion(
                system_prompt=system_prompt, user_message=user_message, temperature=0.3
            )

            print(response);

            if not response:
                logging.error("No response received from OpenAI")
                return None

            logging.info(f"AI response for {element_info['type']}: {response}")

            # Check if response is a string and try to parse it as JSON
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                    logging.info(
                        f"Successfully parsed string response into JSON: {response}"
                    )
                except json.JSONDecodeError as e:
                    logging.error(f"Failed to parse string response as JSON: {str(e)}")
                    # For select types, create a simple response with the string as the selected option
                    if element_info["type"] == "select":
                        response = {"selected_option": response}
                    # For textarea types, create a simple response with the string as the response
                    elif element_info["type"] == "textarea":
                        response = {"response": response}
                    # For radio types, create a simple response with the string as the selected option
                    elif element_info["type"] == "radio":
                        response = {"selected_option": response}
                    # For checkbox types, create a simple response with the string in a list as selected options
                    elif element_info["type"] == "checkbox":
                        response = {"selected_options": [response]}
                    logging.info(f"Created fallback response: {response}")

            # Now verify the response has the expected fields based on element type
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
                response["response"] = json.loads(json.dumps(response["response"]))

            return response

        except Exception as e:
            logging.error(f"Error getting AI response: {str(e)}")
            return None

    def apply_ai_response(self, element_info: Dict, ai_response: Dict, driver):
        """
        Apply AI-generated response to a form element.

        Args:
            element_info: Dictionary containing information about the form element
            ai_response: Dictionary containing the AI-generated response
            driver: Selenium WebDriver instance

        Raises:
            Exception: If applying the response fails
        """
        try:
            element = element_info["element"]

            if element_info["type"] == "textarea":
                element.clear()
                element.send_keys(ai_response["response"])

            elif element_info["type"] == "radio":
                option_id = ai_response["selected_option"]
                option = driver.find_element(By.ID, option_id)
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

    def get_form_elements(self, driver) -> List[Dict]:
        """
        Get all form elements from the current page that need to be filled.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            List of dictionaries containing information about form elements
        """
        elements = []

        forms = driver.find_elements(By.TAG_NAME, "form")
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

    def _get_resume_text(self, tech_stack: str) -> str:
        """
        Get the resume text appropriate for the given tech stack.

        Args:
            tech_stack: The tech stack to get resume for

        Returns:
            Resume text as a string
        """
        tech_stack = tech_stack.lower() if tech_stack else "aws"
        resume_text = ""

        # Try to load tech stack-specific resume
        cv_file_path = f"assets/cv/{tech_stack}.txt"

        try:
            # First, try to find a tech stack-specific resume in assets/cv directory
            with open(cv_file_path, "r") as f:
                resume_text = f.read()
                logging.info(f"Using tech stack-specific resume from {cv_file_path}")
                return resume_text
        except FileNotFoundError:
            pass

        # Try to load from config if available
        try:
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
                            return resume_text
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
                        return resume_text
        except Exception as e:
            logging.warning(f"Error loading resume from config: {str(e)}")

        # If still no resume text, fall back to default "aws" tech stack
        if not resume_text and tech_stack != "aws":
            try:
                with open("assets/cv/aws.txt", "r") as f:
                    resume_text = f.read()
                    logging.info("Falling back to aws resume in assets/cv")
                    return resume_text
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
                    return resume_text
            except FileNotFoundError:
                logging.error("Default resume.txt not found!")
                return "Resume information not available."

        return resume_text
