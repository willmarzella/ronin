"""LinkedIn login functionality."""

import logging
import os
import random
import time
from typing import Optional

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class LinkedInLoginHandler:
    """Class to handle LinkedIn login operations."""

    def __init__(self, driver):
        """
        Initialize with a Selenium WebDriver instance.

        Args:
            driver: Selenium WebDriver instance
        """
        self.driver = driver
        self.logger = logging.getLogger(__name__)

    def login(
        self, username: Optional[str] = None, password: Optional[str] = None
    ) -> bool:
        """
        Log in to LinkedIn using provided credentials or from environment variables.

        Args:
            username: LinkedIn username/email (if None, will use LINKEDIN_USERNAME
                env var)
            password: LinkedIn password (if None, will use LINKEDIN_PASSWORD
                env var)

        Returns:
            bool: True if login was successful, False otherwise
        """
        try:
            # Get credentials from parameters or environment variables
            username = username or os.getenv("LINKEDIN_USERNAME")
            password = password or os.getenv("LINKEDIN_PASSWORD")

            if not username or not password:
                self.logger.error(
                    "LinkedIn credentials not found in parameters or "
                    "environment variables"
                )
                return False

            self.logger.info("Logging in to LinkedIn")

            # Navigate to LinkedIn login page
            self.driver.get("https://www.linkedin.com/login")
            time.sleep(random.uniform(2, 4))

            # Enter username
            username_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            username_field.clear()
            username_field.send_keys(username)

            # Enter password
            password_field = self.driver.find_element(By.ID, "password")
            password_field.clear()
            password_field.send_keys(password)

            # Click login button
            login_button = self.driver.find_element(
                By.XPATH, "//button[contains(text(), 'Sign in')]"
            )
            login_button.click()

            # Wait for login to complete
            time.sleep(random.uniform(5, 8))

            # Check if login was successful
            if (
                "feed" in self.driver.current_url
                or "checkpoint" in self.driver.current_url
            ):
                self.logger.info("Successfully logged in to LinkedIn")
                return True
            else:
                self.logger.error("Failed to log in to LinkedIn")
                return False

        except Exception as e:
            self.logger.error(f"Error logging in to LinkedIn: {str(e)}")
            return False

    def is_logged_in(self) -> bool:
        """
        Check if the user is currently logged in to LinkedIn.

        Returns:
            bool: True if logged in, False otherwise
        """
        try:
            self.logger.info("Checking if logged in to LinkedIn")

            # Check current URL
            current_url = self.driver.current_url

            # If already on LinkedIn, check for login status
            if "linkedin.com" in current_url:
                # Look for common elements that appear when logged in
                try:
                    # Check for the navbar that appears when logged in
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".global-nav"))
                    )
                    self.logger.info("User is already logged in to LinkedIn")
                    return True
                except TimeoutException:
                    self.logger.info("User is not logged in to LinkedIn")
                    return False
            else:
                # Navigate to LinkedIn and check
                self.driver.get("https://www.linkedin.com/")
                time.sleep(random.uniform(3, 5))

                # Check if redirected to login page
                if "/login" in self.driver.current_url:
                    self.logger.info("User is not logged in to LinkedIn")
                    return False
                else:
                    try:
                        # Look for the navbar that appears when logged in
                        WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, ".global-nav")
                            )
                        )
                        self.logger.info("User is already logged in to LinkedIn")
                        return True
                    except TimeoutException:
                        self.logger.info("User is not logged in to LinkedIn")
                        return False

        except Exception as e:
            self.logger.error(f"Error checking login status: {str(e)}")
            return False

    def logout(self) -> bool:
        """
        Log out from LinkedIn.

        Returns:
            bool: True if logout was successful, False otherwise
        """
        try:
            self.logger.info("Attempting to log out from LinkedIn")

            # Check if already logged in
            if not self.is_logged_in():
                self.logger.info("Already logged out")
                return True

            # Click on the profile menu
            try:
                profile_menu = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".global-nav__me-photo")
                    )
                )
                profile_menu.click()
                time.sleep(random.uniform(1, 2))

                # Click on the sign out button
                sign_out_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//a[contains(@href, 'logout')]")
                    )
                )
                sign_out_button.click()
                time.sleep(random.uniform(3, 5))

                # Check if logout was successful
                if "/login" in self.driver.current_url:
                    self.logger.info("Successfully logged out from LinkedIn")
                    return True
                else:
                    self.logger.error("Failed to log out from LinkedIn")
                    return False

            except TimeoutException:
                self.logger.error("Timeout while attempting to log out")
                return False

        except Exception as e:
            self.logger.error(f"Error logging out from LinkedIn: {str(e)}")
            return False
