"""Form response application functionality."""

from typing import Dict

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select


class FormApplier:
    """Handles applying AI-generated responses to form elements."""

    def __init__(self):
        """Initialize the form applier."""
        pass

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
            element_type = element_info["type"]

            if element_type == "textarea":
                self._apply_textarea_response(element, ai_response)
            elif element_type == "radio":
                self._apply_radio_response(element, ai_response, driver)
            elif element_type == "checkbox":
                self._apply_checkbox_response(element, ai_response, driver)
            elif element_type == "select":
                self._apply_select_response(element, ai_response)
            else:
                # Default to text input
                self._apply_text_input_response(element, ai_response)

        except Exception as e:
            raise Exception(f"Failed to apply AI response: {str(e)}")

    def _apply_textarea_response(self, element, ai_response: Dict):
        """Apply response to a textarea element."""
        element.clear()
        element.send_keys(ai_response["response"])

    def _apply_radio_response(self, element, ai_response: Dict, driver):
        """Apply response to a radio button element."""
        option_id = ai_response["selected_option"]
        option = driver.find_element(By.ID, option_id)
        option.click()

    def _apply_checkbox_response(self, element, ai_response: Dict, driver):
        """Apply response to checkbox elements."""
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

    def _apply_select_response(self, element, ai_response: Dict):
        """Apply response to a select element."""
        select = Select(element)
        select.select_by_value(ai_response["selected_option"])

    def _apply_text_input_response(self, element, ai_response: Dict):
        """Apply response to a text input element."""
        element.clear()
        element.send_keys(ai_response["response"])
