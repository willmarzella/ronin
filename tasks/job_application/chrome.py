"""Chrome WebDriver manager for browser automation tasks."""

import logging
import os
import time
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


class ChromeDriver:
    """Manages Chrome WebDriver sessions for browser automation."""

    def __init__(self):
        """Initialize the ChromeDriver."""
        self.driver = None
        self.is_logged_in = False

    def initialize(self) -> webdriver.Chrome:
        """Initialize Chrome WebDriver with local browser."""
        if self.driver:
            return self.driver

        options = webdriver.ChromeOptions()

        # First check if CHROME_BINARY_PATH environment variable is set
        chrome_env_path = os.environ.get("CHROME_BINARY_PATH")
        if chrome_env_path and os.path.exists(chrome_env_path):
            options.binary_location = chrome_env_path
            logging.info(
                f"Using Chrome at path from environment variable: {chrome_env_path}"
            )
        else:
            # Try multiple common Chrome locations on macOS
            chrome_locations = [
                "/Users/marzella/chrome/mac_arm-134.0.6998.88/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",  # Chrome for Testing
                os.path.expanduser(
                    "~/chrome/mac_arm-134.0.6998.88/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
                ),  # Chrome for Testing with home directory
            ]

            chrome_found = False
            for location in chrome_locations:
                if os.path.exists(location):
                    options.binary_location = location
                    chrome_found = True
                    logging.info(f"Found Chrome at: {location}")
                    break

            if not chrome_found:
                logging.warning(
                    "Chrome binary not found in common locations. Proceeding without setting binary location."
                )
                logging.warning(
                    "Consider setting CHROME_BINARY_PATH in your .env file to specify the Chrome location."
                )

        # Basic options
        options.add_argument("--disable-extensions")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)

        # Add these options to bypass Google's automated browser detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-browser-side-navigation")

        # Set a common user agent
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        )

        # Create and use a user data directory for persistence
        user_data_dir = os.path.expanduser("~/chrome_automation_profile")
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)
        options.add_argument(f"--user-data-dir={user_data_dir}")

        # Attempt initialization with retries
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                self.driver = webdriver.Chrome(options=options)
                self.driver.implicitly_wait(10)
                self.driver.set_window_size(1920, 1080)
                logging.info(
                    "Chrome WebDriver initialized successfully with local browser"
                )
                return self.driver
            except Exception as e:
                retry_count += 1
                logging.warning(
                    f"Attempt {retry_count}/{max_retries} to initialize Chrome WebDriver failed: {str(e)}"
                )

                # Wait a bit before retrying
                time.sleep(2)

                if retry_count >= max_retries:
                    logging.error(
                        f"Failed to initialize Chrome WebDriver after {max_retries} attempts: {str(e)}"
                    )
                    raise

    def navigate_to(self, url: str):
        """Navigate the browser to a specific URL."""
        if not self.driver:
            self.initialize()

        self.driver.get(url)

    def wait_for_element(
        self, selector: str, by: By = By.CSS_SELECTOR, timeout: int = 10
    ):
        """Wait for an element to be present and return it."""
        if not self.driver:
            raise Exception("Driver not initialized. Call initialize() first.")

        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, selector))
        )

    def wait_for_clickable(
        self, selector: str, by: By = By.CSS_SELECTOR, timeout: int = 10
    ):
        """Wait for an element to be clickable and return it."""
        if not self.driver:
            raise Exception("Driver not initialized. Call initialize() first.")

        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, selector))
        )

    def find_element(self, selector: str, by: By = By.CSS_SELECTOR):
        """Find an element using the specified selector."""
        if not self.driver:
            raise Exception("Driver not initialized. Call initialize() first.")

        return self.driver.find_element(by, selector)

    def find_elements(self, selector: str, by: By = By.CSS_SELECTOR):
        """Find elements using the specified selector."""
        if not self.driver:
            raise Exception("Driver not initialized. Call initialize() first.")

        return self.driver.find_elements(by, selector)

    def login_seek(self):
        """Handle Seek.com.au login process."""
        if self.is_logged_in:
            return

        try:
            self.navigate_to("https://www.seek.com.au")

            print("\n=== Login Required ===")
            print("1. Please sign in with Google in the browser window")
            print("2. Make sure you're fully logged in")
            print("3. Press Enter when ready to continue...")
            input()

            self.is_logged_in = True
            logging.info("Successfully logged into Seek")

        except Exception as e:
            raise Exception(f"Failed to login to Seek: {str(e)}")

    @property
    def current_url(self) -> str:
        """Get the current URL."""
        if not self.driver:
            raise Exception("Driver not initialized. Call initialize() first.")

        return self.driver.current_url

    @property
    def page_source(self) -> str:
        """Get the current page source."""
        if not self.driver:
            raise Exception("Driver not initialized. Call initialize() first.")

        return self.driver.page_source

    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.is_logged_in = False
