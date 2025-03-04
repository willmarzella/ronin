"""LinkedIn search functionality."""

import logging
from typing import List, Dict, Any, Optional
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import random
import re


class LinkedInSearcher:
    """Class to handle LinkedIn searches."""

    def __init__(self, driver):
        """Initialize with a Selenium WebDriver instance."""
        self.driver = driver
        self.logger = logging.getLogger(__name__)

    def go_to_company_page(self, company_name: str) -> bool:
        """
        Navigate to a company's LinkedIn page.

        Args:
            company_name: Name of the company to navigate to

        Returns:
            bool: True if successful, False otherwise
        """

        def clean_company_name(company_name):
            return re.sub(
                r"\s*(Inc\.|Corp\.|Pty Ltd\.|LLC)\s*", "", company_name
            ).strip()

        try:
            self.logger.info(f"Starting navigation to company page for: {company_name}")
            cleaned_name = clean_company_name(company_name)
            self.logger.info(f"Cleaned company name: {cleaned_name}")

            # Go to LinkedIn search page
            self.logger.info("Navigating to LinkedIn company search page...")
            self.driver.get("https://www.linkedin.com/search/results/companies/")
            self.logger.info("Waiting for search page to load...")
            time.sleep(random.uniform(2, 4))

            # Enter company name in search
            self.logger.info("Looking for search input field...")
            search_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CLASS_NAME, "search-global-typeahead__input")
                )
            )
            self.logger.info("Found search input field, entering company name...")
            search_box.clear()
            search_box.send_keys(cleaned_name)
            search_box.send_keys(Keys.ENTER)
            self.logger.info("Submitted search query")
            time.sleep(random.uniform(3, 5))

            # Find and click on the company in search results
            self.logger.info("Looking for company in search results...")
            company_results = WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located(
                    (
                        By.CSS_SELECTOR,
                        ".entity-result__title-line a, .LpFNBAhDBfqcqSUtuZfWcTwvoFpKwLeFrzk a, ul[role='list'] li a.EsZtTLoFIUAUIwpVUZrTgOCpNfIJUjpMMI",
                    )
                )
            )
            self.logger.info(f"Found {len(company_results)} potential company results")

            for result in company_results:
                try:
                    # First try the new CSS structure
                    self.logger.info(
                        "Attempting to extract company name from result..."
                    )
                    company_element = result.find_element(
                        By.CSS_SELECTOR, "span.RWdWnGItSmSKgAQzUIYieSgzrFWSBijM"
                    )
                    company_text = company_element.text
                except:
                    # Fall back to the element's own text if the specific span isn't found
                    self.logger.info(
                        "Using alternative method to extract company name..."
                    )
                    company_text = result.text

                if company_name.lower() in company_text.lower():
                    self.logger.info(f"Found matching company: {company_text}")
                    self.logger.info("Clicking on company result...")
                    result.click()
                    self.logger.info("Waiting for company page to load...")
                    time.sleep(random.uniform(3, 5))
                    self.logger.info("Successfully navigated to company page")
                    return True

            self.logger.warning(f"Company '{company_name}' not found in search results")
            return False

        except TimeoutException:
            self.logger.error(f"Timeout while searching for company: {company_name}")
            return False
        except Exception as e:
            self.logger.error(f"Error navigating to company page: {str(e)}")
            return False

    def search_people_at_company(
        self, company_name: str, titles: List[str], max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for people with specific titles at a company.

        Args:
            company_name: Name of the company
            titles: List of titles to search for (e.g., "recruiter", "talent")
            max_results: Maximum number of results to return

        Returns:
            List of people data dictionaries
        """
        people = []

        try:
            self.logger.info(
                f"Starting search for people at {company_name} with titles: {titles}"
            )
            self.logger.info(f"Maximum results to return: {max_results}")

            # Navigate directly to the company people page with keywords filter
            self.logger.info("Navigating to company people page...")
            if not self.navigate_to_company_people_page(company_name, titles):
                self.logger.error(
                    f"Failed to navigate to people page for {company_name}"
                )
                return people

            # Extract the search results
            try:
                self.logger.info("Looking for profile cards on the page...")
                # Get all profile cards
                profile_cards = self.driver.find_elements(
                    By.CSS_SELECTOR, ".org-people-profile-card__profile-card-spacing"
                )
                self.logger.info(f"Found {len(profile_cards)} profile cards")

                # Limit to max_results
                profile_cards = profile_cards[:max_results] if profile_cards else []
                self.logger.info(f"Processing {len(profile_cards)} profile cards")

                # Create a LinkedInPeopleHandler to extract information from cards
                from tasks.job_outreach.people import LinkedInPeopleHandler

                people_handler = LinkedInPeopleHandler(self.driver)

                # Process each profile
                for index, card in enumerate(profile_cards, 1):
                    try:
                        self.logger.info(
                            f"Processing profile card {index}/{len(profile_cards)}"
                        )
                        # Extract data from the card using the people handler
                        person_data = people_handler.extract_person_from_card(card)

                        # Add company information
                        person_data["company"] = company_name

                        # Only add if we got a profile URL
                        if person_data["profile_url"]:
                            people.append(person_data)
                            self.logger.info(
                                f"Successfully processed profile {index}: {person_data['name']}, {person_data['title']}"
                            )
                        else:
                            self.logger.warning(
                                f"Profile {index} had no profile URL, skipping"
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Error processing profile card {index}: {str(e)}"
                        )
                        continue

            except TimeoutException:
                self.logger.warning("Timeout waiting for people search results")

            self.logger.info(
                f"Search completed. Found {len(people)} people at {company_name} with titles: {titles}"
            )
            return people

        except Exception as e:
            self.logger.error(f"Error searching for people: {str(e)}")
            return []

    def clean_company_name(self, company_name):
        """Clean company name for URL construction."""
        return company_name.lower().replace(" ", "-").replace("&", "and").strip()

    def navigate_to_company_people_page(
        self, company_name: str, keywords: List[str] = None, wait_time: float = 3.0
    ) -> bool:
        """
        Navigate directly to a company's people page, optionally with keyword filters.

        Args:
            company_name: Name of the company
            keywords: Optional list of keywords to filter profiles (e.g., ["recruiter", "talent"])
            wait_time: Time to wait after navigation (randomized)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.info(
                f"Starting navigation to people page for company: {company_name}"
            )
            if keywords:
                self.logger.info(f"Using keywords filter: {keywords}")

            # First get the company identifier
            company_identifier = ""
            current_url = self.driver.current_url

            if "linkedin.com/company/" in current_url:
                # Extract the company identifier from the current URL
                self.logger.info("Extracting company identifier from current URL...")
                company_identifier = current_url.split("linkedin.com/company/")[
                    1
                ].split("/")[0]
                self.logger.info(f"Found company identifier: {company_identifier}")
            else:
                # We need to go to the company page first to get the identifier
                self.logger.info(
                    "Not on company page, navigating to company page first..."
                )
                if not self.go_to_company_page(company_name):
                    self.logger.error(
                        f"Could not navigate to company page for {company_name}"
                    )
                    return False
                current_url = self.driver.current_url
                company_identifier = current_url.split("linkedin.com/company/")[
                    1
                ].split("/")[0]
                self.logger.info(f"Found company identifier: {company_identifier}")

            # Construct the URL with keywords if provided
            if keywords and len(keywords) > 0:
                # URL encode the keywords
                self.logger.info("Encoding keywords for URL...")
                keywords_param = "%2C%20".join(
                    [k.replace(" ", "%20") for k in keywords]
                )
                url = f"https://www.linkedin.com/company/{company_identifier}/people/?keywords={keywords_param}"
            else:
                url = f"https://www.linkedin.com/company/{company_identifier}/people/"

            self.logger.info(f"Navigating to people page URL: {url}")
            self.driver.get(url)

            # Add random wait time to be more human-like
            wait_time = random.uniform(wait_time, wait_time + 2)
            self.logger.info(f"Waiting {wait_time:.1f} seconds for page to load...")
            time.sleep(wait_time)

            # Verify we're on the people page
            self.logger.info("Verifying we're on the people page...")
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".org-people-profile-card__profile-card-spacing")
                )
            )
            self.logger.info("Successfully loaded people page")
            return True

        except TimeoutException:
            self.logger.error(
                f"Timeout navigating to company people page: {company_name}"
            )
            return False
        except Exception as e:
            self.logger.error(f"Error navigating to company people page: {str(e)}")
            return False
