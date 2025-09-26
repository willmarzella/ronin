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

        # Basic options for stability and functionality
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-default-apps")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)

        # Fix white screen and loading issues
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-browser-side-navigation")
        options.add_argument("--disable-features=TranslateUI")
        options.add_argument("--disable-ipc-flooding-protection")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--force-device-scale-factor=1")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-domain-reliability")
        options.add_argument("--disable-component-extensions-with-background-pages")
        
        # Additional options to fix blank page issues
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--enable-features=NetworkService,NetworkServiceLogging")
        options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-background-media-processing")
        options.add_argument("--disable-client-side-phishing-detection")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate")
        options.add_argument("--hide-scrollbars")
        options.add_argument("--mute-audio")
        options.add_argument("--disable-logging")
        options.add_argument("--disable-login-animations")
        options.add_argument("--disable-notifications")
        
        # Performance and memory optimizations
        options.add_argument("--memory-pressure-off")
        options.add_argument("--max_old_space_size=4096")
        options.add_argument("--disable-background-networking")

        # Set a common user agent
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        )

        # Create and use a user data directory for persistence
        user_data_dir = os.path.expanduser("~/chrome_automation_profile")
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)
        
        # Clear any corrupted profile data that might cause blank pages
        import shutil
        cache_dir = os.path.join(user_data_dir, "Default", "Cache")
        if os.path.exists(cache_dir):
            try:
                shutil.rmtree(cache_dir)
                logging.info("Cleared Chrome cache to prevent blank page issues")
            except Exception as e:
                logging.warning(f"Could not clear cache: {e}")
        
        options.add_argument(f"--user-data-dir={user_data_dir}")
        
        # Add window size to prevent rendering issues
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        
        # Additional debugging options
        options.add_argument("--enable-logging")
        options.add_argument("--log-level=0")
        options.add_argument("--v=1")

        # Attempt initialization with retries
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                self.driver = webdriver.Chrome(options=options)
                self.driver.implicitly_wait(10)
                self.driver.set_window_size(1920, 1080)
                
                # Test basic functionality to ensure browser is working
                try:
                    self.driver.get("data:text/html,<html><body><h1>Test</h1></body></html>")
                    time.sleep(1)  # Give it a moment to render
                    if "Test" not in self.driver.page_source:
                        raise Exception("Browser failed basic rendering test")
                    logging.info("Browser passed basic functionality test")
                except Exception as test_error:
                    logging.warning(f"Browser test failed: {test_error}")
                    self.driver.quit()
                    raise Exception("Browser failed initialization test")
                
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

        try:
            logging.info(f"Navigating to: {url}")
            self.driver.get(url)
            
            # Wait for page to load and verify it's not blank
            max_wait_time = 45  # Increased wait time for slow loading sites
            wait_time = 0
            
            while wait_time < max_wait_time:
                try:
                    # Check if page has loaded (not blank/white screen)
                    ready_state = self.driver.execute_script("return document.readyState")
                    
                    if ready_state == "complete":
                        # Multiple checks to ensure content is actually loaded
                        body_text = self.driver.execute_script("return document.body.innerText || ''")
                        page_html = self.driver.execute_script("return document.body.innerHTML || ''")
                        has_inputs = len(self.driver.find_elements(By.TAG_NAME, "input")) > 0
                        has_buttons = len(self.driver.find_elements(By.TAG_NAME, "button")) > 0
                        has_links = len(self.driver.find_elements(By.TAG_NAME, "a")) > 0
                        
                        # Check for specific Workforce Australia elements
                        if "workforceaustralia" in url.lower():
                            has_wa_content = any([
                                "workforce" in body_text.lower(),
                                "job" in body_text.lower(),
                                "search" in body_text.lower(),
                                len(page_html) > 1000,  # Page has substantial content
                                has_inputs or has_buttons or has_links
                            ])
                            
                            if has_wa_content:
                                logging.info("Workforce Australia page loaded successfully")
                                break
                        else:
                            # Generic content check
                            if body_text.strip() or has_inputs or has_buttons or len(page_html) > 100:
                                logging.info("Page loaded successfully")
                                break
                    
                    time.sleep(2)  # Increased sleep time for slower loading
                    wait_time += 2
                    
                    # Log progress every 10 seconds
                    if wait_time % 10 == 0:
                        logging.info(f"Still waiting for page to load... ({wait_time}s)")
                        
                except Exception as check_error:
                    logging.warning(f"Error checking page state: {check_error}")
                    time.sleep(2)
                    wait_time += 2
            
            if wait_time >= max_wait_time:
                logging.warning(f"Page may not have loaded properly after {max_wait_time}s")
                # Try a refresh as last resort
                try:
                    logging.info("Attempting page refresh...")
                    self.driver.refresh()
                    time.sleep(5)
                except Exception:
                    pass
                
        except Exception as e:
            logging.error(f"Error navigating to {url}: {str(e)}")
            raise

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

    def reset_profile(self):
        """Reset Chrome profile to fix persistent issues."""
        import shutil
        
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.is_logged_in = False
        
        user_data_dir = os.path.expanduser("~/chrome_automation_profile")
        if os.path.exists(user_data_dir):
            try:
                shutil.rmtree(user_data_dir)
                logging.info("Chrome profile reset successfully")
            except Exception as e:
                logging.error(f"Failed to reset Chrome profile: {e}")

    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.is_logged_in = False
