"""Implements the logic to apply to jobs on Workforce Australia (Centrelink)"""

from typing import Dict, Optional, List
import logging
import time
import re
import os

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
            # Direct navigation to apply URL - fastest approach
            apply_url = f"{self.base_url}/individuals/jobs/apply/{job_id}"
            self.chrome_driver.navigate_to(apply_url)
            # No wait time - we'll handle checking in the apply_to_job function
        except Exception as e:
            logging.error(f"Failed to navigate to job {job_id}: {str(e)}")

    def _click_next_step(self) -> bool:
        """Click the 'Continue' button on the application form with blazing speed."""
        try:
            # TURBO SPEED: Direct JavaScript execution for maximum speed
            turbo_script = """
                // BLAZING FAST button finder and clicker
                // Try multiple approaches in one go for maximum speed
                
                // First look for Submit button specifically (final step)
                var submitButtons = document.querySelectorAll('button');
                for (var i = 0; i < submitButtons.length; i++) {
                    var btn = submitButtons[i];
                    if (btn.offsetParent === null) continue; // Skip hidden buttons
                    
                    var text = btn.textContent.toLowerCase().trim();
                    if (text === 'submit' || text.includes('submit application') || text.includes('apply now')) {
                        console.log("Found submit button: " + text);
                        btn.scrollIntoView({block: 'center'});
                        btn.click();
                        return "CLICKED_SUBMIT";
                    }
                }
                
                // Approach 1: Direct attribute targeting (fastest)
                var btn = document.querySelector('button[data-v-cb7c258b]');
                if (btn && btn.offsetParent !== null) {
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return "CLICKED_DIRECT";
                }
                
                // Approach 2: Text content targeting (very fast)
                var allButtons = document.querySelectorAll('button');
                for (var i = 0; i < allButtons.length; i++) {
                    var button = allButtons[i];
                    if (button.offsetParent === null) continue; // Skip hidden buttons
                    
                    var text = button.textContent.toLowerCase().trim();
                    if (text === 'continue' || text.includes('next step')) {
                        button.scrollIntoView({block: 'center'});
                        button.click();
                        return "CLICKED_TEXT";
                    }
                }
                
                // Approach 3: Class-based targeting (fast)
                var primaryBtn = document.querySelector('.mint-button.primary');
                if (primaryBtn && primaryBtn.offsetParent !== null) {
                    primaryBtn.scrollIntoView({block: 'center'});
                    primaryBtn.click();
                    return "CLICKED_CLASS";
                }
                
                // Approach 4: Any button with primary class (fallback)
                var anyPrimaryBtn = document.querySelector('button.primary');
                if (anyPrimaryBtn && anyPrimaryBtn.offsetParent !== null) {
                    anyPrimaryBtn.scrollIntoView({block: 'center'});
                    anyPrimaryBtn.click();
                    return "CLICKED_ANY_PRIMARY";
                }
                
                // Approach 5: ANY visible button as last resort
                var allVisibleButtons = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null);
                if (allVisibleButtons.length > 0) {
                    // Try to find the most prominent button (largest or centered)
                    allVisibleButtons.sort((a, b) => {
                        var aRect = a.getBoundingClientRect();
                        var bRect = b.getBoundingClientRect();
                        // Sort by size (area) - larger buttons are likely more important
                        return (bRect.width * bRect.height) - (aRect.width * aRect.height);
                    });
                    
                    // Click the largest visible button
                    allVisibleButtons[0].scrollIntoView({block: 'center'});
                    allVisibleButtons[0].click();
                    return "CLICKED_LARGEST_BUTTON";
                }
                
                return "NO_BUTTON_FOUND";
            """

            result = self.chrome_driver.driver.execute_script(turbo_script)

            if "CLICKED" in result:
                # Minimal wait - just enough for the page to respond
                time.sleep(0.5)
                return True

            # Super fast fallback using Selenium if JavaScript approach failed
            try:
                # Look for Submit button first
                try:
                    submit_button = self.chrome_driver.driver.find_element(
                        By.XPATH,
                        '//button[contains(translate(., "SUBMIT", "submit"), "submit") or contains(., "Apply")]',
                    )
                    self.chrome_driver.driver.execute_script(
                        "arguments[0].click();", submit_button
                    )
                    time.sleep(0.5)
                    return True
                except Exception:
                    pass

                # Then try Continue button
                continue_button = self.chrome_driver.driver.find_element(
                    By.XPATH,
                    '//button[contains(translate(., "CONTINUE", "continue"), "continue")]',
                )
                self.chrome_driver.driver.execute_script(
                    "arguments[0].click();", continue_button
                )
                time.sleep(0.5)
                return True
            except Exception:
                pass

            return False
        except Exception as e:
            logging.error(f"Error in click_next_step: {str(e)}")
            return False

    def _is_success_page(self) -> bool:
        """Ultra-fast check if we're on a success page."""
        try:
            # TURBO: Combined URL and content check in one JavaScript execution
            turbo_success_script = """
                var url = window.location.href.toLowerCase();
                var urlSuccess = url.includes('success');
                
                // Only check content if URL looks promising
                if (urlSuccess) {
                    var pageText = document.body.textContent.toLowerCase();
                    var hasSuccessText = 
                        pageText.includes('successfully applied') ||
                        pageText.includes('application successful') ||
                        pageText.includes('application submitted') ||
                        pageText.includes('application complete');
                    
                    return hasSuccessText;
                }
                
                return false;
            """

            return self.chrome_driver.driver.execute_script(turbo_success_script)
        except Exception:
            return False

    def _check_page_status(self) -> str:
        """Blazingly fast check of the current page status."""
        try:
            # TURBO: All checks in one JavaScript execution
            turbo_status_script = """
                var url = window.location.href.toLowerCase();
                var text = document.body.textContent.toLowerCase();
                
                // Success check
                if (url.includes('success') && 
                    (text.includes('successfully applied') || 
                     text.includes('application successful') ||
                     text.includes('application submitted') ||
                     text.includes('application complete'))) {
                    return 'SUCCESS';
                }
                
                // Already applied check
                if (text.includes('already applied') || text.includes('have already applied')) {
                    return 'ALREADY_APPLIED';
                }
                
                // Invalid link check
                if (text.includes('link is invalid') || text.includes('invalid link') || text.includes('job not found')) {
                    return 'INVALID_LINK';
                }
                
                return 'NORMAL';
            """

            status = self.chrome_driver.driver.execute_script(turbo_status_script)
            if status in ["SUCCESS", "ALREADY_APPLIED", "INVALID_LINK"]:
                return status

            return "NORMAL"
        except Exception:
            return "NORMAL"

    def _complete_application_steps(self) -> bool:
        """Complete all steps in the application process with blazing speed."""
        try:
            max_steps = 8  # Increased to allow for more steps
            step_count = 0
            last_content_hash = None
            consecutive_stuck_count = 0

            # TURBO: Fast content hash function
            fast_hash_script = """
                // Ultra-fast content hash
                var hash = '';
                
                // Get visible buttons (most important for state detection)
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < Math.min(buttons.length, 5); i++) {
                    if (buttons[i].offsetParent !== null) {
                        hash += buttons[i].textContent.trim().substring(0, 10) + ';';
                    }
                }
                
                // Get headings for page identification
                var h1s = document.querySelectorAll('h1');
                if (h1s.length > 0) {
                    hash += h1s[0].textContent.trim() + ';';
                }
                
                return hash;
            """

            while step_count < max_steps:
                # Generate quick content hash
                current_content_hash = self.chrome_driver.driver.execute_script(
                    fast_hash_script
                )

                # Quick success check
                if self._is_success_page():
                    return True

                # Check if stuck
                if current_content_hash == last_content_hash and step_count > 0:
                    consecutive_stuck_count += 1
                    if consecutive_stuck_count >= 2:
                        # Try clicking any button as a last resort
                        self.chrome_driver.driver.execute_script(
                            """
                            // Look for submit buttons first
                            var submitButtons = Array.from(document.querySelectorAll('button')).filter(b => 
                                b.offsetParent !== null && 
                                (b.textContent.toLowerCase().includes('submit') || 
                                 b.textContent.toLowerCase().includes('apply'))
                            );
                            
                            if (submitButtons.length > 0) {
                                submitButtons[0].scrollIntoView({block: 'center'});
                                submitButtons[0].click();
                                return;
                            }
                            
                            // Then try any button
                            var buttons = document.querySelectorAll('button');
                            for (var i = 0; i < buttons.length; i++) {
                                if (buttons[i].offsetParent !== null && !buttons[i].disabled) {
                                    buttons[i].click();
                                    break;
                                }
                            }
                        """
                        )

                        # Wait a bit longer after this emergency click
                        time.sleep(1)

                        if consecutive_stuck_count >= 3:
                            # Final attempt: Look for a submit button specifically
                            try:
                                submit_buttons = self.chrome_driver.driver.find_elements(
                                    By.XPATH,
                                    '//button[contains(translate(., "SUBMIT", "submit"), "submit") or contains(., "Apply")]',
                                )
                                if submit_buttons:
                                    for btn in submit_buttons:
                                        try:
                                            if btn.is_displayed():
                                                self.chrome_driver.driver.execute_script(
                                                    "arguments[0].click();", btn
                                                )
                                                time.sleep(1)
                                                break
                                        except Exception:
                                            continue
                            except Exception:
                                pass

                            break
                else:
                    consecutive_stuck_count = 0

                # Click next button - turbo version
                clicked = self._click_next_step()
                if not clicked:
                    # One retry with minimal wait
                    time.sleep(0.5)
                    clicked = self._click_next_step()
                    if not clicked and step_count > 1:
                        # Last resort: try to find any submit button
                        try:
                            submit_buttons = self.chrome_driver.driver.find_elements(
                                By.XPATH,
                                '//button[contains(translate(., "SUBMIT", "submit"), "submit") or contains(., "Apply")]',
                            )
                            if submit_buttons:
                                for btn in submit_buttons:
                                    try:
                                        if btn.is_displayed():
                                            self.chrome_driver.driver.execute_script(
                                                "arguments[0].click();", btn
                                            )
                                            time.sleep(1)
                                            break
                                    except Exception:
                                        continue
                                # Continue even if we found and clicked a submit button
                            else:
                                break
                        except Exception:
                            break

                # Minimal wait between steps
                time.sleep(0.5)
                last_content_hash = current_content_hash
                step_count += 1

            # Final success check
            return self._is_success_page()

        except Exception as e:
            logging.error(f"Error completing application steps: {str(e)}")
            return False

    def apply_to_job(
        self, job_id: str, job_title: str = "", company_name: str = ""
    ) -> str:
        """Apply to a specific job on Workforce Australia with blazing speed."""
        try:
            # Initialize chrome driver if not already initialized
            self.chrome_driver.initialize()

            # Make sure we're logged in
            if not self.chrome_driver.is_logged_in:
                self._login_centrelink()

            # Check if we've already applied to this job (memory check - fastest)
            if job_id in self.applied_jobs:
                return "ALREADY_APPLIED"

            # Navigate to the job application page
            self._navigate_to_job(job_id)

            # Minimal wait for page load - just enough to be reliable
            time.sleep(1)

            # Quick check page status
            page_status = self._check_page_status()

            # Handle pre-application status
            if page_status == "ALREADY_APPLIED":
                self.applied_jobs.add(job_id)
                return "ALREADY_APPLIED"

            if page_status == "INVALID_LINK":
                return "INVALID_LINK"

            if page_status == "SUCCESS":
                self.applied_jobs.add(job_id)
                return "APPLIED"

            # Turbo-complete the application process
            application_result = self._complete_application_steps()

            # Final validation
            if application_result:
                logging.info(f"Successfully applied to job {job_id}")
                self.applied_jobs.add(job_id)
                return "APPLIED"
            else:
                # Quick re-check
                final_status = self._check_page_status()
                if final_status == "SUCCESS":
                    self.applied_jobs.add(job_id)
                    return "APPLIED"
                elif final_status == "ALREADY_APPLIED":
                    self.applied_jobs.add(job_id)
                    return "ALREADY_APPLIED"
                else:
                    return "UNCERTAIN"

        except Exception as e:
            logging.error(f"Exception during application for job {job_id}: {str(e)}")
            return "APP_ERROR"

    def cleanup(self):
        """Clean up resources - call this when completely done with all applications"""
        self.chrome_driver.cleanup()
