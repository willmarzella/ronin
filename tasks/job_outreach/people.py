"""Person-related functionality for LinkedIn outreach."""

import logging
from typing import Dict, Any, Optional, List
import time
import random
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
)


class LinkedInPeopleHandler:
    """Class to handle people-related operations on LinkedIn."""

    def __init__(self, driver):
        """Initialize with a Selenium WebDriver instance."""
        self.driver = driver
        self.logger = logging.getLogger(__name__)

    def visit_profile(self, profile_url: str) -> bool:
        """
        Visit a LinkedIn profile.

        Args:
            profile_url: URL of the profile to visit

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.info(f"Starting to visit profile: {profile_url}")
            self.logger.info("Navigating to profile URL...")
            self.driver.get(profile_url)
            self.logger.info("Waiting for page to load...")
            time.sleep(random.uniform(3, 5))

            # Verify we're on a profile page by checking for the main profile section
            try:
                self.logger.info("Checking for profile page elements...")
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "section.artdeco-card.soWRbpDuDgYLgTMssoCzkulbQTrIuZSVMjuPos",
                        )
                    )
                )
                self.logger.info("Successfully loaded profile page")
                return True
            except TimeoutException:
                self.logger.error("Timeout waiting for profile page to load")
                return False

        except Exception as e:
            self.logger.error(f"Error visiting profile: {str(e)}")
            return False

    def extract_profile_info(self) -> Dict[str, Any]:
        """
        Extract information from the current profile page.

        Returns:
            Dictionary with profile information
        """
        profile_info = {
            "name": "",
            "headline": "",
            "company": "",
            "title": "",
            "location": "",
            "connection_degree": "",
            "about": "",
            "profile_url": "",
        }

        try:
            self.logger.info("Starting profile information extraction")
            profile_info["profile_url"] = self.driver.current_url
            self.logger.info(f"Current profile URL: {profile_info['profile_url']}")

            # Extract name
            try:
                self.logger.info("Attempting to extract profile name...")
                name_element = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".pv-top-card--list .text-heading-xlarge")
                    )
                )
                profile_info["name"] = name_element.text.strip()
                self.logger.info(f"Successfully extracted name: {profile_info['name']}")
            except:
                self.logger.warning("Could not extract profile name")

            # Extract headline
            try:
                self.logger.info("Attempting to extract profile headline...")
                headline_element = self.driver.find_element_by_css_selector(
                    ".pv-top-card--list .text-body-medium"
                )
                profile_info["headline"] = headline_element.text.strip()
                self.logger.info(
                    f"Successfully extracted headline: {profile_info['headline']}"
                )

                # Try to separate company and title
                if " at " in profile_info["headline"]:
                    parts = profile_info["headline"].split(" at ", 1)
                    profile_info["title"] = parts[0].strip()
                    profile_info["company"] = parts[1].strip()
                    self.logger.info(f"Extracted title: {profile_info['title']}")
                    self.logger.info(f"Extracted company: {profile_info['company']}")
            except:
                self.logger.warning("Could not extract profile headline")

            # Extract location
            try:
                self.logger.info("Attempting to extract profile location...")
                location_element = self.driver.find_element_by_css_selector(
                    ".pv-top-card--list .text-body-small"
                )
                profile_info["location"] = location_element.text.strip()
                self.logger.info(
                    f"Successfully extracted location: {profile_info['location']}"
                )
            except:
                self.logger.warning("Could not extract profile location")

            # Extract connection degree
            try:
                self.logger.info("Attempting to extract connection degree...")
                degree_element = self.driver.find_element_by_css_selector(
                    ".pv-top-card__distance-badge .dist-value"
                )
                profile_info["connection_degree"] = degree_element.text.strip()
                self.logger.info(
                    f"Successfully extracted connection degree: {profile_info['connection_degree']}"
                )
            except:
                self.logger.warning("Could not extract connection degree")

            # Extract about section if available
            try:
                self.logger.info("Attempting to extract about section...")
                about_element = self.driver.find_element_by_css_selector(
                    ".pv-about-section .inline-show-more-text"
                )
                profile_info["about"] = about_element.text.strip()
                self.logger.info("Successfully extracted about section")
            except:
                # Try to click the "About" section first if not immediately visible
                try:
                    self.logger.info(
                        "About section not immediately visible, attempting to scroll to it..."
                    )
                    about_section = self.driver.find_element_by_xpath(
                        "//section[.//h2[contains(text(), 'About')]]"
                    )
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView();", about_section
                    )
                    time.sleep(1)
                    about_element = about_section.find_element_by_css_selector(
                        ".inline-show-more-text"
                    )
                    profile_info["about"] = about_element.text.strip()
                    self.logger.info(
                        "Successfully extracted about section after scrolling"
                    )
                except:
                    self.logger.warning("Could not extract about section")

            self.logger.info("Profile information extraction completed")
            return profile_info

        except Exception as e:
            self.logger.error(f"Error extracting profile info: {str(e)}")
            return profile_info

    def can_message_directly(self) -> bool:
        """
        Check if we can message the person directly.

        Returns:
            bool: True if direct messaging is possible, False otherwise
        """
        try:
            self.logger.info("Checking if direct messaging is possible")

            # Look for the message button using modern Selenium API
            try:
                message_buttons = self.driver.find_elements(
                    By.XPATH,
                    "//button[contains(@aria-label, 'Message') or contains(text(), 'Message')]",
                )

                for button in message_buttons:
                    if button.is_displayed() and button.is_enabled():
                        self.logger.info("Message button found and is clickable")
                        return True

                # If we get here, no enabled message buttons were found
                self.logger.info("No clickable message buttons found")
                return False

            except NoSuchElementException:
                self.logger.warning("No message button found on this profile")
                return False

        except Exception as e:
            self.logger.error(
                f"Error checking if direct messaging is possible: {str(e)}"
            )
            return False

    def send_connection_request(self, note: str = "") -> bool:
        """
        Send a connection request to the current profile.

        Args:
            note: Optional note to include with the connection request

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.info("Starting connection request process")
            self.logger.info(
                f"Note to be included: {note[:50]}..." if note else "No note included"
            )

            # Find and click the "Connect" button
            try:
                self.logger.info("Looking for main connect button...")
                # Try first approach - main connect button
                connect_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//button[contains(@aria-label, 'Connect') or contains(text(), 'Connect')]",
                        )
                    )
                )
                self.logger.info("Found main connect button, clicking...")
                connect_button.click()
                time.sleep(random.uniform(1, 2))
            except (TimeoutException, ElementClickInterceptedException):
                self.logger.info(
                    "Main connect button not found, trying More menu approach..."
                )
                # Try second approach - "More..." menu
                try:
                    more_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//button[contains(text(), 'More')]")
                        )
                    )
                    self.logger.info("Found More menu button, clicking...")
                    more_button.click()
                    time.sleep(random.uniform(1, 2))

                    connect_option = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable(
                            (
                                By.XPATH,
                                "//div[contains(@role, 'menuitem') and contains(text(), 'Connect')]",
                            )
                        )
                    )
                    self.logger.info("Found Connect option in More menu, clicking...")
                    connect_option.click()
                    time.sleep(random.uniform(1, 2))
                except:
                    self.logger.warning("Could not find Connect button or More menu")
                    return False

            # If a note is provided, add it to the connection request
            if note:
                try:
                    self.logger.info("Looking for Add a note button...")
                    # Check if "Add a note" button exists and click it
                    add_note_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//button[contains(text(), 'Add a note')]")
                        )
                    )
                    self.logger.info("Found Add a note button, clicking...")
                    add_note_button.click()
                    time.sleep(random.uniform(1, 2))

                    self.logger.info("Looking for note text field...")
                    # Enter the note
                    note_field = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located(
                            (
                                By.XPATH,
                                "//textarea[contains(@placeholder, 'Your message')]",
                            )
                        )
                    )
                    self.logger.info("Found note text field, entering message...")
                    # Clear existing text if any
                    note_field.clear()
                    # Type the note
                    note_field.send_keys(
                        note[:300]
                    )  # LinkedIn has a 300 character limit
                    time.sleep(random.uniform(1, 2))
                    self.logger.info("Successfully entered note")
                except:
                    self.logger.warning("Could not add note to connection request")

            # Send the connection request
            try:
                self.logger.info("Looking for Send button...")
                send_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(), 'Send')]")
                    )
                )
                self.logger.info("Found Send button, clicking...")
                send_button.click()
                time.sleep(random.uniform(2, 3))
                self.logger.info("Connection request sent successfully")
                return True
            except:
                self.logger.warning("Could not send connection request")
                return False

        except Exception as e:
            self.logger.error(f"Error sending connection request: {str(e)}")
            return False

    def send_direct_message(self, message: str) -> bool:
        """
        Send a direct message to the current profile.

        Args:
            message: Message to send

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.info("Attempting to send direct message")

            # First check if direct messaging is possible
            if not self.can_message_directly():
                self.logger.warning("Direct messaging is not possible for this profile")
                return False

            # Find and click the message button
            try:
                message_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//button[contains(@aria-label, 'Message') or contains(text(), 'Message')]",
                        )
                    )
                )
                message_button.click()
                time.sleep(random.uniform(2, 3))
            except:
                self.logger.warning("Could not click message button")
                return False

            # Enter the message in the message field
            try:
                message_field = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//div[contains(@role, 'textbox')]")
                    )
                )
                message_field.clear()
                message_field.send_keys(message)
                time.sleep(random.uniform(1, 2))
            except:
                self.logger.warning("Could not enter message text")
                return False

            # Send the message
            try:
                send_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(), 'Send')]")
                    )
                )
                send_button.click()
                time.sleep(random.uniform(2, 3))
                self.logger.info("Direct message sent successfully")
                return True
            except:
                self.logger.warning("Could not send direct message")
                return False

        except Exception as e:
            self.logger.error(f"Error sending direct message: {str(e)}")
            return False

    def extract_person_from_card(self, card) -> Dict[str, Any]:
        """
        Extract information from a LinkedIn profile card element.

        Args:
            card: The WebElement representing the profile card

        Returns:
            Dictionary containing the extracted profile information
        """
        person_data = {
            "name": "Unknown",
            "title": "",
            "profile_url": "",
            "image_url": "",
            "connection_degree": "",
            "additional_info": "",
            "has_mutual_connections": False,
            "mutual_connection": "",
            "can_message": False,
            "can_connect": False,
        }

        try:
            # Get profile URL and image URL
            try:
                # Look for the profile link in the lockup image section
                profile_link = card.find_element(
                    By.CSS_SELECTOR, ".artdeco-entity-lockup__image a"
                )
                person_data["profile_url"] = profile_link.get_attribute("href")

                # Try to get profile image
                try:
                    img_element = profile_link.find_element(By.TAG_NAME, "img")
                    person_data["image_url"] = img_element.get_attribute("src")
                except:
                    self.logger.debug("Could not extract profile image")
            except:
                self.logger.debug("Could not extract profile URL or image")

            # Get name
            try:
                name_element = card.find_element(
                    By.CSS_SELECTOR, ".artdeco-entity-lockup__title .t-black"
                )
                person_data["name"] = name_element.text.strip()
            except:
                try:
                    # Alternative selector based on the HTML structure
                    name_element = card.find_element(
                        By.CSS_SELECTOR, ".lt-line-clamp--single-line.t-black"
                    )
                    person_data["name"] = name_element.text.strip()
                except:
                    self.logger.debug("Could not extract name")

            # Get connection degree
            try:
                degree_element = card.find_element(
                    By.CSS_SELECTOR, ".artdeco-entity-lockup__degree"
                )
                connection_text = degree_element.text.strip()
                # Clean up the text (remove the dot and whitespace)
                person_data["connection_degree"] = connection_text.replace(
                    "·", ""
                ).strip()
            except:
                self.logger.debug("Could not extract connection degree")

            # Get title
            try:
                title_element = card.find_element(
                    By.CSS_SELECTOR,
                    ".artdeco-entity-lockup__subtitle .lt-line-clamp--multi-line",
                )
                person_data["title"] = title_element.text.strip()
            except:
                self.logger.debug("Could not extract title")

            # Get additional info (followers, mutual connections)
            try:
                info_element = card.find_element(
                    By.CSS_SELECTOR, ".t-12.t-black--light.mt2"
                )
                additional_info = info_element.text.strip()
                person_data["additional_info"] = additional_info

                # Extract mutual connections if present
                if "mutual connection" in additional_info:
                    person_data["has_mutual_connections"] = True
                    # Try to extract the mutual connection name
                    mutual_parts = additional_info.split(" is a mutual connection")
                    if len(mutual_parts) > 0:
                        person_data["mutual_connection"] = (
                            mutual_parts[0].split("•")[-1].strip()
                        )
            except:
                self.logger.debug("Could not extract additional info")

            # Check if user can be messaged directly
            try:
                message_button = card.find_element(
                    By.XPATH,
                    ".//button[contains(@aria-label, 'Message') or contains(text(), 'Message')]",
                )
                person_data["can_message"] = (
                    message_button.is_displayed() and message_button.is_enabled()
                )
            except:
                self.logger.debug("Could not determine message capability")

            # Check if user can be connected with
            try:
                connect_button = card.find_element(
                    By.XPATH,
                    ".//button[contains(@aria-label, 'Connect') or contains(text(), 'Connect')]",
                )
                person_data["can_connect"] = (
                    connect_button.is_displayed() and connect_button.is_enabled()
                )
            except:
                self.logger.debug("Could not determine connect capability")

            return person_data

        except Exception as e:
            self.logger.error(f"Error extracting profile data from card: {str(e)}")
            return person_data
