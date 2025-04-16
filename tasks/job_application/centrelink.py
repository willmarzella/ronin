"""Implements the logic to apply to jobs on Workforce Australia (Centrelink)"""

from typing import Dict, Optional, List
import logging
import time
import re

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from core.config import load_config
from services.airtable_service import AirtableManager
from tasks.job_application.chrome import ChromeDriver


class CentrelinkApplier:
    """Handles job applications on Workforce Australia (Centrelink)."""

    def __init__(self):
        self.config = load_config()
        self.airtable = AirtableManager()
        self.chrome_driver = ChromeDriver()
        self.base_url = "https://www.workforceaustralia.gov.au"
        self.applied_jobs = set()  # Keep track of jobs we've already applied to

    def _login_centrelink(self):
        """Handle Workforce Australia login process."""
        if self.chrome_driver.is_logged_in:
            return

        try:
            self.chrome_driver.navigate_to(f"{self.base_url}/individuals/jobs/search")

            print("\n=== Login Required ===")
            print("1. Please sign in to Workforce Australia in the browser window")
            print("2. Make sure you're fully logged in")
            print("3. Press Enter when ready to continue...")
            input()

            self.chrome_driver.is_logged_in = True
            logging.info("Successfully logged into Workforce Australia")

        except Exception as e:
            raise Exception(f"Failed to login to Workforce Australia: {str(e)}")

    def _navigate_to_job_search(self, search_text: str = "", page_number: int = 1):
        """Navigate to the job search page with pagination support."""
        try:
            # The base search URL may change, so try a few variations
            search_url = f"{self.base_url}/individuals/jobs/search?searchText={search_text}&pageNumber={page_number}"
            self.chrome_driver.navigate_to(search_url)

            # Wait for the page to fully load
            time.sleep(0.5)  # Reduced wait time

        except Exception as e:
            raise Exception(f"Failed to navigate to job search page: {str(e)}")

    def get_jobs_from_search_page(
        self, search_text: str = "", limit: int = 100, max_pages: int = 5
    ) -> List[Dict]:
        """Scrape jobs from the Workforce Australia search page with pagination support."""
        all_jobs = []
        current_page = 1
        job_count = 0

        try:
            # Initialize chrome driver if not already initialized
            self.chrome_driver.initialize()

            # Make sure we're logged in first
            if not self.chrome_driver.is_logged_in:
                self._login_centrelink()

            # Process each page until limit is reached or no more pages
            while current_page <= max_pages and job_count < limit:
                # Navigate to the current page
                logging.info(
                    f"Navigating to search page {current_page} for '{search_text}'"
                )
                self._navigate_to_job_search(search_text, current_page)

                # Get jobs from the current page
                page_jobs = self._extract_jobs_from_current_page(limit - job_count)

                if page_jobs:
                    all_jobs.extend(page_jobs)
                    job_count += len(page_jobs)
                    logging.info(
                        f"Found {len(page_jobs)} jobs on page {current_page}, total jobs: {job_count}"
                    )
                else:
                    # No jobs found on this page, we've reached the end of results
                    logging.info(
                        f"No jobs found on page {current_page}, end of results reached"
                    )
                    break

                # Check if we've reached the job limit
                if job_count >= limit:
                    logging.info(f"Reached job limit of {limit}, stopping pagination")
                    break

                # Move to the next page
                current_page += 1

            logging.info(
                f"Collected a total of {len(all_jobs)} jobs across {current_page} pages"
            )
            return all_jobs

        except Exception as e:
            logging.error(f"Error getting jobs from search pages: {str(e)}")
            # Return any jobs we did manage to collect
            return all_jobs

    def _extract_jobs_from_current_page(self, remaining_limit: int) -> List[Dict]:
        """Extract jobs from the currently loaded page."""
        jobs = []

        try:
            # Wait for job listings to load
            job_card_found = False
            selectors_to_try = [
                ".mint-search-result-item",  # Most precise selector from the actual HTML
                ".results-list > section",  # Parent container with sections
                "section.mint-search-result-item",  # Alternative with tag
            ]

            for selector in selectors_to_try:
                try:
                    WebDriverWait(self.chrome_driver.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    job_cards = self.chrome_driver.driver.find_elements(
                        By.CSS_SELECTOR, selector
                    )
                    if job_cards:
                        logging.info(f"Found job listings using selector: {selector}")
                        job_card_found = True
                        break
                except TimeoutException:
                    logging.info(f"No job cards found with selector: {selector}")
                    continue

            if not job_card_found:
                logging.warning("No job cards found on this page")
                return jobs

            logging.info(f"Found {len(job_cards)} job cards on current page")

            # Process each job card up to the limit
            for i, card in enumerate(job_cards):
                if i >= remaining_limit:
                    break

                try:
                    # Extract job details - try different selector patterns
                    title = None
                    company = None
                    job_link = None

                    # First priority: get the job link, as that's the most critical
                    try:
                        if card.tag_name == "a":
                            job_link = card.get_attribute("href")
                        else:
                            # Try to find job link in the h5 heading first (most accurate from HTML example)
                            heading_link = card.find_elements(
                                By.CSS_SELECTOR, "h5.mint-sri-heading a.mint-link"
                            )
                            if heading_link:
                                job_link = heading_link[0].get_attribute("href")
                                title = heading_link[0].text.strip()
                            else:
                                # Fallback to any anchor tag
                                anchors = card.find_elements(By.TAG_NAME, "a")
                                for anchor in anchors:
                                    href = anchor.get_attribute("href")
                                    if href and (
                                        "/individuals/jobs/details/" in href
                                        or "/individuals/jobs/apply/" in href
                                    ):
                                        job_link = href
                                        # If we found a job link anchor, also try to get title from it
                                        if not title:
                                            title = anchor.text.strip()
                                        break
                    except Exception as anchor_e:
                        logging.error(f"Error finding anchors: {str(anchor_e)}")

                    # If we still don't have a job link, skip this card
                    if not job_link:
                        logging.warning(
                            f"Could not find job link in card {i+1}, skipping"
                        )
                        continue

                    # Now try to get title if we don't have it yet
                    if not title:
                        try:
                            # Try heading first based on the HTML structure
                            h5_selector = "h5.mint-sri-heading"
                            try:
                                h5_elem = card.find_element(
                                    By.CSS_SELECTOR, h5_selector
                                )
                                title = h5_elem.text.strip()
                            except NoSuchElementException:
                                # Try other title selectors
                                for title_selector in [
                                    ".job-title",
                                    "h3",
                                    "h4",
                                    "h2",
                                    "h5",
                                    "[data-automation='job-title']",
                                    ".title",
                                    "[class*='title']",
                                    "[class*='jobTitle']",
                                    "strong",  # Sometimes titles are in bold text
                                    "b",  # or just bold
                                    "a > span",  # Sometimes titles are in spans within links
                                ]:
                                    try:
                                        title_elem = card.find_element(
                                            By.CSS_SELECTOR, title_selector
                                        )
                                        title = title_elem.text.strip()
                                        break
                                    except NoSuchElementException:
                                        continue
                        except Exception as title_e:
                            logging.error(f"Error finding title: {str(title_e)}")

                    # Try to get company/metadata - in the provided HTML, it's in the metadata section
                    try:
                        # Look for the location/metadata div
                        metadata_div = card.find_elements(
                            By.CSS_SELECTOR, "div.metadata ul li"
                        )
                        if metadata_div and len(metadata_div) > 0:
                            # First item is location, second is position type
                            location = (
                                metadata_div[0].text.strip()
                                if len(metadata_div) > 0
                                else "Unknown Location"
                            )
                            position_type = (
                                metadata_div[1].text.strip()
                                if len(metadata_div) > 1
                                else ""
                            )

                            # Look for company logo alt text or use a default
                            img_elem = card.find_elements(
                                By.CSS_SELECTOR, "div.img-wrapper img"
                            )
                            if img_elem:
                                alt_text = img_elem[0].get_attribute("alt")
                                if alt_text and "Employer logo" in alt_text:
                                    # Try to extract employer name from alt text if possible
                                    company = "Unknown Company"
                                else:
                                    company = alt_text or "Unknown Company"
                            else:
                                company = "Unknown Company"
                        else:
                            # Fallback to old company detection methods
                            for company_selector in [
                                ".job-company",
                                ".company",
                                "[data-automation='job-company']",
                                ".employer",
                                "[class*='company']",
                                "[class*='employer']",
                                "[class*='organization']",
                                "p",  # Sometimes company name is in a paragraph
                            ]:
                                try:
                                    company_elem = card.find_element(
                                        By.CSS_SELECTOR, company_selector
                                    )
                                    company = company_elem.text.strip()
                                    break
                                except NoSuchElementException:
                                    continue
                    except Exception as company_e:
                        logging.error(f"Error finding company: {str(company_e)}")
                        company = "Unknown Company"

                    # Extract job ID from URL - try both details and apply URLs
                    job_id = None
                    if "/individuals/jobs/details/" in job_link:
                        job_id = (
                            job_link.split("/individuals/jobs/details/")[1].split("?")[
                                0
                            ]
                            if "?" in job_link
                            else job_link.split("/individuals/jobs/details/")[1]
                        )
                    elif "/individuals/jobs/apply/" in job_link:
                        job_id = self._extract_job_id_from_url(job_link)

                    # Skip if we can't get a job ID
                    if not job_id:
                        logging.warning(
                            f"Could not extract job ID from link: {job_link}"
                        )
                        continue

                    # Skip jobs we've already applied to
                    if job_id in self.applied_jobs:
                        logging.info(f"Skipping already applied job: {job_id}")
                        continue

                    # If we still don't have a title, use generic name with job ID
                    if not title or title.strip() == "":
                        title = f"Job {job_id}"

                    # Create job object with whatever info we have
                    job = {
                        "job_id": job_id,
                        "title": title,
                        "company": company or "Unknown Company",
                        "source": "centrelink",
                        "url": job_link,
                    }

                    jobs.append(job)
                    logging.info(
                        f"Added job to list: {job['title']} at {job['company']}"
                    )

                except Exception as e:
                    logging.error(
                        f"Error extracting job details from card {i+1}: {str(e)}"
                    )
                    continue

            # If we didn't find any jobs with the normal approach, try a more aggressive method
            if not jobs:
                logging.info(
                    "No jobs found with standard extraction, trying direct link extraction"
                )
                try:
                    all_links = self.chrome_driver.driver.find_elements(
                        By.TAG_NAME, "a"
                    )
                    job_counter = 0
                    for link in all_links:
                        if job_counter >= remaining_limit:
                            break

                        try:
                            href = link.get_attribute("href")
                            if href and "/individuals/jobs/apply/" in href:
                                job_id = self._extract_job_id_from_url(href)
                                if job_id and job_id not in self.applied_jobs:
                                    # Try to get title from link text or parent element
                                    title = link.text.strip()
                                    if not title:
                                        # Try parent element text
                                        parent = link.find_element(By.XPATH, "..")
                                        title = parent.text.strip()

                                    # If still no title, use generic one
                                    if not title:
                                        title = f"Job {job_id}"

                                    job = {
                                        "job_id": job_id,
                                        "title": title,
                                        "company": "Unknown Company",
                                        "source": "centrelink",
                                        "url": href,
                                    }
                                    jobs.append(job)
                                    job_counter += 1
                                    logging.info(
                                        f"Added job from direct link: {job_id}"
                                    )
                        except Exception as link_e:
                            logging.error(f"Error processing link: {str(link_e)}")
                            continue
                except Exception as direct_e:
                    logging.error(f"Error in direct link extraction: {str(direct_e)}")

        except Exception as e:
            logging.error(f"Error getting jobs from current page: {str(e)}")

        return jobs

    def _navigate_to_job(self, job_id: str):
        """Navigate to the specific job application page with zero wait."""
        try:
            # Try navigating directly to the apply URL - fastest approach
            apply_url = f"{self.base_url}/individuals/jobs/apply/{job_id}"
            self.chrome_driver.navigate_to(apply_url)

            # No wait time - we'll handle checking for button immediately
            # time.sleep is completely removed here

        except Exception as e:
            logging.error(f"Failed to navigate to job {job_id}: {str(e)}")

    def _click_next_step(self) -> bool:
        """Click the 'Next step' button on the application form with ultra-fast approach."""
        try:
            # Target the exact button structure shown in the comment
            # <button type="button" class="mint-button primary mobileBlock" data-v-438dc630=""><span class="mint-button-inner"><span class="visually-hidden" role="status"></span><!----><span class="mint-button-text" aria-hidden="false"><!----> Next step <!----></span></span></button>

            # Direct JavaScript approach - fastest possible method
            script = """
                // Ultra-fast button finder and clicker
                // First, try the most specific selectors
                var btn = document.querySelector('.mint-button.primary.mobileBlock') || 
                          document.querySelector('button.primary') || 
                          document.querySelector('.mint-button') ||
                          document.querySelector('button[data-v-438dc630]');
                          
                if (btn) {
                    // Quick scroll (if needed) and immediate click
                    var rect = btn.getBoundingClientRect();
                    if (rect.top < 0 || rect.bottom > window.innerHeight) {
                        btn.scrollIntoView({block: 'center'});
                    }
                    try { 
                        btn.click(); 
                        return true; 
                    } catch(e) {
                        // If direct click fails, use event dispatch
                        var evt = new MouseEvent('click', {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        });
                        btn.dispatchEvent(evt);
                        return true;
                    }
                }
                
                // Fast text-based search if specific selectors failed
                var allButtons = document.querySelectorAll('button');
                for (var i = 0; i < allButtons.length; i++) {
                    var btnText = allButtons[i].textContent.toLowerCase();
                    if (btnText.includes('next') || btnText.includes('continue') || btnText.includes('submit')) {
                        allButtons[i].scrollIntoView({block: 'center'});
                        allButtons[i].click();
                        return true;
                    }
                }
                
                // Try spans with button text that might be inside buttons (last resort)
                var buttonTextSpans = document.querySelectorAll('span.mint-button-text');
                for (var i = 0; i < buttonTextSpans.length; i++) {
                    if (buttonTextSpans[i].textContent.toLowerCase().includes('next') || 
                        buttonTextSpans[i].textContent.toLowerCase().includes('continue')) {
                        var parentButton = buttonTextSpans[i].closest('button');
                        if (parentButton) {
                            parentButton.click();
                            return true;
                        }
                    }
                }
                
                return false;
            """

            result = self.chrome_driver.driver.execute_script(script)
            if result:
                # Ultra-minimal wait after click
                time.sleep(0.1)  # Ultra-fast: reduced from 0.2s to 0.1s
                return True

            # Quick fallback using Selenium if JavaScript approach failed
            for selector in [
                ".mint-button.primary.mobileBlock",
                ".mint-button.primary",
                "button.primary",
                ".mint-button",
            ]:
                try:
                    element = WebDriverWait(self.chrome_driver.driver, 0.2).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    # Use JavaScript click to avoid any Selenium overhead
                    self.chrome_driver.driver.execute_script(
                        "arguments[0].click();", element
                    )
                    time.sleep(0.1)  # Ultra-fast: reduced from 0.2s to 0.1s
                    return True
                except Exception:
                    continue

            return False
        except Exception as e:
            logging.debug(f"Error in click_next_step: {str(e)}")
            return False

    def _complete_application_steps(self) -> bool:
        """Complete all steps in the application process with ultra-fast approach."""
        try:
            # There are typically 4 steps in the application
            for step in range(4):
                # Check for success after each step for early exit
                if "success" in self.chrome_driver.current_url:
                    logging.info(f"Success detected after step {step}, exiting early")
                    return True

                if not self._click_next_step():
                    # Try once more before giving up on this step
                    time.sleep(0.1)
                    if not self._click_next_step():
                        logging.warning(f"Failed on step {step+1}, but will continue")

                # Ultra-minimal wait between steps
                time.sleep(0.1)  # Ultra-fast: reduced from 0.2s to 0.1s

            return True
        except Exception as e:
            logging.error(f"Error completing application steps: {str(e)}")
            return False

    # Fast success check - uses lightweight methods
    def _is_success_page(self) -> bool:
        """Ultra-fast check if we're on a success page."""
        try:
            # Quick URL check first (fastest)
            if "success" in self.chrome_driver.current_url:
                return True

            # Quick JavaScript check for success indicators
            script = """
                // Fast check for common success page elements
                return (
                    document.title.toLowerCase().includes('success') ||
                    document.documentElement.textContent.includes('successfully applied') ||
                    document.documentElement.textContent.includes('application successful') ||
                    document.querySelector('.success-message, .application-success, [class*="success"]') !== null
                );
            """
            return self.chrome_driver.driver.execute_script(script)
        except Exception:
            return False

    # Unified error check function to reduce redundancy
    def _check_page_status(self) -> str:
        """Check the current page status - returns one of:
        'ALREADY_APPLIED', 'INVALID_LINK', 'SUCCESS', or 'NORMAL'
        """
        try:
            # Quick success check first
            if self._is_success_page():
                return "SUCCESS"

            # Fast JavaScript check for common page status indicators
            script = """
                var text = document.documentElement.textContent.toLowerCase();
                if (text.includes('already applied') || text.includes('have already applied')) {
                    return 'ALREADY_APPLIED';
                }
                if (text.includes('link is invalid') || text.includes('invalid link') || text.includes('job not found')) {
                    return 'INVALID_LINK';
                }
                return 'NORMAL';
            """
            status = self.chrome_driver.driver.execute_script(script)
            if status in ["ALREADY_APPLIED", "INVALID_LINK"]:
                return status

            # Fallback to element check if JavaScript check didn't find anything
            error_container = None
            try:
                error_container = self.chrome_driver.driver.find_elements(
                    By.CSS_SELECTOR, ".container-fluid.job-error"
                )
            except Exception:
                pass

            if error_container:
                # Get the page source once for all checks
                page_source = self.chrome_driver.driver.page_source.lower()

                # Check for already applied message
                if "already applied" in page_source:
                    return "ALREADY_APPLIED"

                # Check for invalid link message
                if "link is invalid" in page_source:
                    return "INVALID_LINK"

            # No special status detected
            return "NORMAL"

        except Exception as e:
            logging.debug(f"Error checking page status: {str(e)}")
            return "NORMAL"  # Default to normal in case of error

    def apply_to_job(
        self, job_id: str, job_title: str = "", company_name: str = ""
    ) -> str:
        """Apply to a specific job on Workforce Australia with zero-delay approach"""
        try:
            # Initialize chrome driver if not already initialized
            self.chrome_driver.initialize()

            # Make sure we're logged in
            if not self.chrome_driver.is_logged_in:
                self._login_centrelink()

            # Check if we've already applied to this job (memory check - fastest)
            if job_id in self.applied_jobs:
                return "ALREADY_APPLIED"

            # Navigate to the job application page - zero delay
            self._navigate_to_job(job_id)

            # IMMEDIATELY check for quick conditions that don't require waiting
            if "success" in self.chrome_driver.current_url:
                self.applied_jobs.add(job_id)
                return "APPLIED"

            # Quick JavaScript check to detect page type without waiting
            page_type_script = """
                if (document.readyState !== 'loading') {
                    // Page already loaded
                    var text = document.documentElement.textContent.toLowerCase();
                    if (text.includes('already applied') || text.includes('have already applied')) {
                        return 'ALREADY_APPLIED';
                    }
                    if (text.includes('link is invalid') || text.includes('invalid link') || text.includes('job not found')) {
                        return 'INVALID_LINK';
                    }
                    if (text.includes('success') || document.title.toLowerCase().includes('success')) {
                        return 'SUCCESS';
                    }
                    
                    // Check for application form indicators (fast)
                    if (document.querySelector('.mint-button.primary.mobileBlock, button.primary, .mint-button')) {
                        return 'READY_TO_APPLY';
                    }
                }
                return 'LOADING';
            """

            # Execute immediate check
            initial_status = self.chrome_driver.driver.execute_script(page_type_script)

            # Handle immediate status results
            if initial_status == "ALREADY_APPLIED":
                self.applied_jobs.add(job_id)
                return "ALREADY_APPLIED"

            if initial_status == "INVALID_LINK":
                return "INVALID_LINK"

            if initial_status == "SUCCESS":
                self.applied_jobs.add(job_id)
                return "APPLIED"

            if initial_status == "READY_TO_APPLY":
                # We detected the apply form is ready, go directly to applying without status check
                self._complete_application_steps()

                # Quick check after applying
                if (
                    "success" in self.chrome_driver.current_url
                    or self._is_success_page()
                ):
                    self.applied_jobs.add(job_id)
                    return "APPLIED"
                return "UNCERTAIN"

            # If we couldn't determine page state immediately, do a minimal wait and check again
            time.sleep(0.05)  # Ultra-minimal wait - just 50ms

            # Standard checks after minimal wait
            page_status = self._check_page_status()

            if page_status == "ALREADY_APPLIED":
                self.applied_jobs.add(job_id)
                return "ALREADY_APPLIED"

            if page_status == "INVALID_LINK":
                return "INVALID_LINK"

            if page_status == "SUCCESS":
                self.applied_jobs.add(job_id)
                return "APPLIED"

            # Complete all the application steps - with fast success checking
            self._complete_application_steps()

            # Final success check after completing steps
            if self._is_success_page() or "success" in self.chrome_driver.current_url:
                self.applied_jobs.add(job_id)
                return "APPLIED"
            else:
                # One more check for success indicators in page content
                if self._check_page_status() == "SUCCESS":
                    self.applied_jobs.add(job_id)
                    return "APPLIED"
                return "UNCERTAIN"

        except Exception as e:
            logging.error(f"Exception during application for job {job_id}: {str(e)}")
            # Quick check if we somehow ended up on the success page despite errors
            if self._is_success_page():
                self.applied_jobs.add(job_id)
                return "APPLIED"
            return "APP_ERROR"

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        self.chrome_driver.cleanup()
