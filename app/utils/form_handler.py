"""Utility class for advanced form handling and anti-detection."""

import time
import random
from typing import Any, Dict, List, Optional
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.action_chains import ActionChains


class FormHandler:
    """Advanced form handling with human-like interaction."""

    def __init__(self, driver: WebDriver):
        """Initialize the form handler."""
        self.driver = driver
        self.action_chains = ActionChains(driver)

    def _human_type(self, element: WebElement, text: str):
        """Simulate human-like typing with variable speed and occasional mistakes."""
        # Clear the field naturally
        element.click()
        time.sleep(random.uniform(0.1, 0.3))

        # Sometimes use select all + delete instead of clear()
        if random.random() < 0.3:
            if random.random() < 0.5:
                element.send_keys(Keys.COMMAND + "a")  # macOS
            else:
                element.send_keys(Keys.CONTROL + "a")  # Windows/Linux
            time.sleep(random.uniform(0.1, 0.2))
            element.send_keys(Keys.BACKSPACE)
        else:
            element.clear()

        # Type with variable speed and occasional mistakes
        for char in text:
            # Randomly make a typo
            if random.random() < 0.05:
                typo = random.choice("qwertyuiopasdfghjklzxcvbnm")
                element.send_keys(typo)
                time.sleep(random.uniform(0.1, 0.3))
                element.send_keys(Keys.BACKSPACE)
                time.sleep(random.uniform(0.1, 0.2))

            # Type the correct character
            element.send_keys(char)

            # Variable typing speed
            time.sleep(random.uniform(0.05, 0.2))

            # Occasionally pause like a human thinking
            if random.random() < 0.02:
                time.sleep(random.uniform(0.5, 1.5))

    def _human_click(self, element: WebElement):
        """Simulate human-like clicking behavior."""
        # Move mouse naturally with variable speed
        self.action_chains.move_to_element_with_offset(
            element,
            random.randint(-3, 3),  # Slight x offset
            random.randint(-3, 3),  # Slight y offset
        )

        # Sometimes move past and come back
        if random.random() < 0.2:
            self.action_chains.move_by_offset(
                random.randint(5, 10), random.randint(5, 10)
            )
            time.sleep(random.uniform(0.1, 0.3))
            self.action_chains.move_to_element(element)

        self.action_chains.pause(random.uniform(0.1, 0.3))
        self.action_chains.click()
        self.action_chains.perform()

        # Sometimes double-check the click
        if random.random() < 0.1:
            time.sleep(random.uniform(0.2, 0.4))
            element.click()

    def _human_scroll(self, element: WebElement):
        """Simulate human-like scrolling behavior."""
        # Get element location
        location = element.location_once_scrolled_into_view

        # Scroll a bit past, then back
        self.driver.execute_script(
            f"window.scrollTo({location['x']}, {location['y'] + random.randint(50, 100)});"
        )
        time.sleep(random.uniform(0.1, 0.3))

        self.driver.execute_script(
            f"window.scrollTo({location['x']}, {location['y'] - random.randint(10, 30)});"
        )
        time.sleep(random.uniform(0.1, 0.2))

        # Final accurate scroll
        element.location_once_scrolled_into_view

    def fill_text_field(self, element: WebElement, text: str):
        """Fill a text field with human-like behavior."""
        self._human_scroll(element)
        time.sleep(random.uniform(0.2, 0.5))
        self._human_click(element)
        time.sleep(random.uniform(0.1, 0.3))
        self._human_type(element, text)

    def select_dropdown_option(self, select_element: WebElement, value: str):
        """Select a dropdown option with human-like behavior."""
        self._human_scroll(select_element)
        time.sleep(random.uniform(0.2, 0.5))
        self._human_click(select_element)
        time.sleep(random.uniform(0.3, 0.7))

        # Find and click the option
        option = select_element.find_element(
            By.CSS_SELECTOR, f"option[value='{value}']"
        )
        self._human_click(option)

        # Sometimes move mouse away after selection
        if random.random() < 0.3:
            self.action_chains.move_by_offset(
                random.randint(50, 100), random.randint(50, 100)
            ).perform()

    def click_radio_checkbox(self, element: WebElement):
        """Click a radio button or checkbox with human-like behavior."""
        self._human_scroll(element)
        time.sleep(random.uniform(0.2, 0.5))

        # Sometimes hover before clicking
        if random.random() < 0.4:
            self.action_chains.move_to_element(element).perform()
            time.sleep(random.uniform(0.2, 0.5))

        self._human_click(element)

        # Occasionally double-check the selection
        if random.random() < 0.2:
            time.sleep(random.uniform(0.5, 1.0))
            if not element.is_selected():
                self._human_click(element)

    def submit_form(self, submit_button: WebElement):
        """Submit a form with human-like behavior."""
        # Scroll to button with variable speed
        self._human_scroll(submit_button)
        time.sleep(random.uniform(0.5, 1.0))

        # Sometimes move mouse around before clicking
        if random.random() < 0.3:
            self.action_chains.move_by_offset(
                random.randint(-50, 50), random.randint(-50, 50)
            ).perform()
            time.sleep(random.uniform(0.2, 0.5))

        # Hover over button
        self.action_chains.move_to_element(submit_button).perform()
        time.sleep(random.uniform(0.3, 0.7))

        # Click with slight pause
        self._human_click(submit_button)

        # Sometimes move mouse away after clicking
        if random.random() < 0.4:
            self.action_chains.move_by_offset(
                random.randint(50, 100), random.randint(50, 100)
            ).perform()

    def add_random_noise(self):
        """Add random mouse movements and scrolls to appear more human-like."""
        # Random mouse movements
        for _ in range(random.randint(1, 3)):
            self.action_chains.move_by_offset(
                random.randint(-100, 100), random.randint(-100, 100)
            ).perform()
            time.sleep(random.uniform(0.1, 0.3))

        # Random scrolls
        if random.random() < 0.3:
            current_scroll = self.driver.execute_script("return window.pageYOffset;")
            self.driver.execute_script(
                f"window.scrollTo(0, {current_scroll + random.randint(-100, 100)});"
            )
            time.sleep(random.uniform(0.2, 0.5))

    def handle_dynamic_content(self, base_element: WebElement):
        """Handle dynamically loaded content and overlays."""
        # Wait for any loading indicators to disappear
        loading_selectors = [
            ".loading",
            ".spinner",
            "[aria-busy='true']",
            "[role='progressbar']",
            ".overlay",
            ".modal",
        ]

        for selector in loading_selectors:
            elements = base_element.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                time.sleep(random.uniform(0.5, 1.0))

        # Handle common overlay patterns
        overlay_selectors = [
            ".modal",
            ".dialog",
            ".popup",
            ".overlay",
            "[role='dialog']",
            "[aria-modal='true']",
        ]

        for selector in overlay_selectors:
            overlays = base_element.find_elements(By.CSS_SELECTOR, selector)
            for overlay in overlays:
                if overlay.is_displayed():
                    # Look for close buttons
                    close_buttons = overlay.find_elements(
                        By.CSS_SELECTOR,
                        "button[aria-label='Close'], .close, .dismiss, .modal-close",
                    )
                    if close_buttons:
                        self._human_click(close_buttons[0])
                        time.sleep(random.uniform(0.3, 0.7))

    def verify_field_value(self, element: WebElement, expected_value: str) -> bool:
        """Verify that a field contains the expected value."""
        actual_value = element.get_attribute("value")

        if actual_value != expected_value:
            # Try to fix the value
            self.fill_text_field(element, expected_value)
            time.sleep(random.uniform(0.2, 0.5))

            # Verify again
            actual_value = element.get_attribute("value")

        return actual_value == expected_value
