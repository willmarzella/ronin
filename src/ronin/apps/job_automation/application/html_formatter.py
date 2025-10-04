"""HTML form element extraction and formatting functionality."""

import logging
from typing import Dict, List

from selenium.webdriver.common.by import By


class HTMLFormatter:
    """Handles extraction and formatting of HTML form elements."""

    def __init__(self):
        """Initialize the HTML formatter."""
        pass

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
        logging.info(f"Found {len(forms)} forms on the page")

        for form in forms:
            try:
                # Process checkbox groups
                checkbox_elements = self._extract_checkbox_groups(form)
                elements.extend(checkbox_elements)

                # Process radio groups
                radio_elements = self._extract_radio_groups(form)
                elements.extend(radio_elements)

                # Process other form elements (inputs, selects, textareas)
                other_elements = self._extract_other_elements(form)
                elements.extend(other_elements)

            except Exception as e:
                logging.warning(f"Error processing form: {str(e)}")
                continue

        logging.info(f"Total form elements found: {len(elements)}")
        return elements

    def _extract_checkbox_groups(self, form) -> List[Dict]:
        """Extract checkbox groups from a form."""
        checkbox_groups = {}

        checkbox_containers = form.find_elements(
            By.XPATH,
            ".//fieldset[.//input[@type='checkbox']] | .//div[.//strong and .//input[@type='checkbox']]",
        )

        for container in checkbox_containers:
            question = self._extract_question_from_container(container)
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
                label_text = self._extract_label_for_checkbox(container, checkbox)
                checkbox_groups[name]["options"].append(
                    {
                        "id": checkbox.get_attribute("id"),
                        "label": label_text,
                    }
                )

        return list(checkbox_groups.values())

    def _extract_radio_groups(self, form) -> List[Dict]:
        """Extract radio groups from a form."""
        radio_groups = {}
        radios = form.find_elements(By.CSS_SELECTOR, 'input[type="radio"]')
        logging.debug(f"Found {len(radios)} radio buttons in form")

        for radio in radios:
            name = radio.get_attribute("name")
            if not name:
                continue

            question = self._extract_question_from_radio(radio)
            if not question:
                continue

            if name not in radio_groups:
                radio_groups[name] = {
                    "element": radio,
                    "type": "radio",
                    "question": question,
                    "options": [],
                }

            label_text = self._extract_label_for_radio(form, radio)
            radio_groups[name]["options"].append(
                {
                    "id": radio.get_attribute("id"),
                    "label": label_text,
                }
            )
            logging.debug(
                f"Added radio option: {label_text} (ID: {radio.get_attribute('id')})"
            )

        return list(radio_groups.values())

    def _extract_other_elements(self, form) -> List[Dict]:
        """Extract other form elements (inputs, selects, textareas) from a form."""
        elements = []

        for element in form.find_elements(
            By.CSS_SELECTOR,
            "input:not([type='checkbox']):not([type='radio']):not([type='hidden']):not([type='submit']):not([type='button']), select, textarea",
        ):
            element_type = element.get_attribute("type")
            if element_type == "select-one":
                element_type = "select"

            label = self._find_element_label(form, element)
            if not label:
                continue

            question_text = self._extract_question_text_from_label(label)
            if not question_text:
                continue

            element_info = {
                "element": element,
                "type": element_type or element.tag_name,
                "question": question_text,
            }

            if element.tag_name == "select":
                options = self._extract_select_options(element)
                element_info["options"] = options

            elements.append(element_info)
            logging.debug(
                f"Added form element: {element_info['type']} - {element_info['question'][:50]}..."
            )

        return elements

    def _extract_question_from_container(self, container) -> str:
        """Extract question text from a container element."""
        try:
            question = container.find_element(
                By.XPATH, ".//legend//strong | .//strong"
            ).text.strip()
            return question
        except Exception:
            headings = container.find_elements(
                By.XPATH,
                "./preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6][1]",
            )
            if headings:
                return headings[0].text.strip()
        return ""

    def _extract_question_from_radio(self, radio) -> str:
        """Extract question text from a radio button element."""
        try:
            fieldset = radio.find_element(By.XPATH, "ancestor::fieldset")
            # Try multiple ways to find the question text
            try:
                question = fieldset.find_element(
                    By.XPATH, ".//legend//strong"
                ).text.strip()
                return question
            except Exception:
                try:
                    question = fieldset.find_element(By.XPATH, ".//legend").text.strip()
                    return question
                except Exception:
                    question = fieldset.find_element(By.XPATH, ".//strong").text.strip()
                    return question
        except Exception:
            try:
                parent_div = radio.find_element(By.XPATH, "ancestor::div[.//strong][1]")
                question = parent_div.find_element(By.TAG_NAME, "strong").text.strip()
                return question
            except Exception:
                pass
        return ""

    def _extract_label_for_checkbox(self, container, checkbox) -> str:
        """Extract label text for a checkbox element."""
        label_text = ""
        try:
            checkbox_id = checkbox.get_attribute("id")
            if checkbox_id:
                label = container.find_element(
                    By.CSS_SELECTOR, f'label[for="{checkbox_id}"]'
                )
                label_text = label.text.strip()
        except Exception:
            try:
                label = checkbox.find_element(
                    By.XPATH,
                    "ancestor::label | following-sibling::label",
                )
                label_text = label.text.strip()
            except Exception:
                try:
                    label_text = checkbox.find_element(
                        By.XPATH, "following::text()[1]"
                    ).strip()
                except Exception:
                    label_text = ""
        return label_text

    def _extract_label_for_radio(self, form, radio) -> str:
        """Extract label text for a radio button element."""
        label_text = ""
        try:
            radio_id = radio.get_attribute("id")
            if radio_id:
                label = form.find_element(By.CSS_SELECTOR, f'label[for="{radio_id}"]')
                label_text = label.text.strip()
        except Exception:
            try:
                # Try to find label by following sibling or parent structure
                label = radio.find_element(
                    By.XPATH,
                    "ancestor::div//label | following-sibling::*//label",
                )
                label_text = label.text.strip()
            except Exception:
                try:
                    # Look for nearby text content
                    parent = radio.find_element(By.XPATH, "parent::*")
                    label_text = parent.text.strip()
                    # Remove any text that's not the label
                    if label_text and len(label_text) > 100:
                        label_text = ""
                except Exception:
                    label_text = ""
        return label_text

    def _find_element_label(self, form, element) -> object:
        """Find the label element for a form element."""
        try:
            element_id = element.get_attribute("id")
            if element_id:
                label = form.find_element(By.CSS_SELECTOR, f'label[for="{element_id}"]')
                return label
        except Exception:
            try:
                label = element.find_element(
                    By.XPATH,
                    "ancestor::label | preceding-sibling::label[1]",
                )
                return label
            except Exception:
                try:
                    label = element.find_element(
                        By.XPATH,
                        "./preceding::*[self::strong or self::label or contains(@class, 'label')][1]",
                    )
                    return label
                except Exception:
                    pass
        return None

    def _extract_question_text_from_label(self, label) -> str:
        """Extract question text from a label element."""
        try:
            # First try to find strong elements within the label
            strong_elements = label.find_elements(By.TAG_NAME, "strong")
            if strong_elements:
                return strong_elements[0].text.strip()
            else:
                # Fall back to the full label text
                return label.text.strip()
        except Exception:
            return label.text.strip() if label else ""

    def _extract_select_options(self, select_element) -> List[Dict]:
        """Extract options from a select element."""
        options = []
        for option in select_element.find_elements(By.TAG_NAME, "option"):
            value = option.get_attribute("value")
            if value:
                options.append(
                    {
                        "value": value,
                        "label": option.text.strip(),
                    }
                )
        return options
