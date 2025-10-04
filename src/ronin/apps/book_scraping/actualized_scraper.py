"""Actualized.org book list scraper service."""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ronin.core.logging import setup_logger
from ronin.models.book import Book


class ActualizedScraper:
    """Scraper for Actualized.org book list with authentication."""

    def __init__(self, config: Dict):
        """Initialize the scraper with configuration."""
        self.config = config
        self.logger = setup_logger()
        self.session = requests.Session()
        self.driver = None

        # Set up user agent
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            }
        )

        # Book storage
        self.books_file = self.config.get("actualized", {}).get(
            "books_file", "data/actualized_books.json"
        )
        self.ensure_data_directory()

    def ensure_data_directory(self):
        """Ensure the data directory exists."""
        data_dir = os.path.dirname(self.books_file)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            self.logger.info(f"Created data directory: {data_dir}")

    def setup_driver(self) -> webdriver.Chrome:
        """Set up Chrome WebDriver with appropriate options."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in headless mode
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_argument(
            f'--user-agent={self.session.headers["User-Agent"]}'
        )

        driver = webdriver.Chrome(options=chrome_options)
        driver.implicitly_wait(10)
        return driver

    def login(self, username: str, password: str) -> bool:
        """Login to Actualized.org."""
        try:
            self.driver = self.setup_driver()
            login_url = "https://actualized.org/myproducts/01"

            self.logger.info(f"Navigating to login page: {login_url}")
            self.driver.get(login_url)

            # Wait for login form to load
            wait = WebDriverWait(self.driver, 20)

            # Find and fill email field
            email_field = wait.until(EC.presence_of_element_located((By.NAME, "email")))
            email_field.clear()
            email_field.send_keys(username)
            self.logger.info("Email field filled")

            # Find and fill password field
            password_field = self.driver.find_element(By.NAME, "password")
            password_field.clear()
            password_field.send_keys(password)
            self.logger.info("Password field filled")

            # Submit the form
            submit_button = self.driver.find_element(
                By.XPATH, "//input[@type='submit']"
            )
            submit_button.click()
            self.logger.info("Login form submitted")

            # Wait for redirect and check if login was successful
            time.sleep(3)
            current_url = self.driver.current_url

            if "login" not in current_url.lower() and "myproducts" in current_url:
                self.logger.info("Login successful")
                return True
            else:
                self.logger.error(f"Login failed. Current URL: {current_url}")
                return False

        except Exception as e:
            self.logger.error(f"Error during login: {str(e)}")
            return False

    def extract_books_from_page(self, page_source: str) -> List[Book]:
        """Extract book information from page HTML."""
        books = []
        soup = BeautifulSoup(page_source, "html.parser")

        # This will need to be adjusted based on the actual HTML structure
        # of the Actualized.org book list page
        book_elements = soup.find_all(
            ["div", "li", "tr"],
            class_=lambda x: x
            and any(
                keyword in x.lower() for keyword in ["book", "item", "entry", "row"]
            ),
        )

        if not book_elements:
            # Try alternative selectors
            book_elements = soup.find_all(
                ["p", "div"],
                string=lambda text: text
                and any(
                    keyword in text.lower() for keyword in ["by ", "author:", "isbn"]
                ),
            )

        for element in book_elements:
            try:
                book = self.parse_book_element(element)
                if book:
                    books.append(book)
            except Exception as e:
                self.logger.warning(f"Error parsing book element: {str(e)}")
                continue

        self.logger.info(f"Extracted {len(books)} books from page")
        return books

    def parse_book_element(self, element) -> Optional[Book]:
        """Parse a book element and extract book information."""
        try:
            text = element.get_text().strip()
            if not text or len(text) < 10:  # Skip very short text
                return None

            # Look for book patterns
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            if not lines:
                return None

            # Extract title (usually the first or most prominent line)
            title = None
            author = None
            description = None

            for line in lines:
                # Skip lines that look like navigation or metadata
                if any(
                    skip in line.lower()
                    for skip in ["login", "logout", "menu", "copyright", "terms"]
                ):
                    continue

                # Look for author patterns
                if " by " in line.lower() or "author:" in line.lower():
                    parts = line.split(" by ")
                    if len(parts) == 2:
                        title = parts[0].strip()
                        author = parts[1].strip()
                    else:
                        # Try author: pattern
                        if "author:" in line.lower():
                            parts = line.lower().split("author:")
                            if len(parts) == 2:
                                author = parts[1].strip()
                                # Title might be in a previous line or same line before "author:"
                                title_part = parts[0].strip()
                                if title_part and not title:
                                    title = title_part

                # If no title yet and line looks like a title
                elif (
                    not title and len(line) > 5 and not line.startswith(("http", "www"))
                ):
                    # Check if it's likely a book title
                    if any(char.isupper() for char in line) and not line.isupper():
                        title = line

            # If we still don't have a title, use the first substantial line
            if not title and lines:
                title = lines[0]

            if not title:
                return None

            # Clean up title and author
            title = self.clean_text(title)
            if author:
                author = self.clean_text(author)

            # Try to extract additional info from links
            url = None
            links = element.find_all("a", href=True)
            for link in links:
                href = link.get("href")
                if href and ("amazon" in href or "book" in href.lower()):
                    url = href
                    break

            return Book(
                title=title,
                author=author,
                description=description,
                url=url,
                date_added=datetime.now(),
            )

        except Exception as e:
            self.logger.warning(f"Error parsing book element: {str(e)}")
            return None

    def clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return text

        # Remove extra whitespace
        text = " ".join(text.split())

        # Remove common prefixes/suffixes
        prefixes = ["book:", "title:", "by:", "author:"]
        for prefix in prefixes:
            if text.lower().startswith(prefix):
                text = text[len(prefix) :].strip()

        # Remove quotes if they wrap the entire string
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]

        return text.strip()

    def scrape_books(self, username: str, password: str) -> List[Book]:
        """Scrape all books from the Actualized.org book list."""
        all_books = []

        try:
            # Login first
            if not self.login(username, password):
                self.logger.error("Failed to login, cannot scrape books")
                return []

            self.logger.info("Successfully logged in, starting book extraction")

            # Get the current page source
            page_source = self.driver.page_source

            # Extract books from current page
            books = self.extract_books_from_page(page_source)
            all_books.extend(books)

            # Look for pagination or additional pages
            # This would need to be implemented based on the actual site structure
            pagination_links = self.driver.find_elements(
                By.XPATH, "//a[contains(@href, 'page') or contains(text(), 'Next')]"
            )

            for link in pagination_links:
                try:
                    self.logger.info(
                        f"Following pagination link: {link.get_attribute('href')}"
                    )
                    link.click()
                    time.sleep(2)  # Wait for page load

                    page_source = self.driver.page_source
                    page_books = self.extract_books_from_page(page_source)
                    all_books.extend(page_books)

                except Exception as e:
                    self.logger.warning(f"Error following pagination link: {str(e)}")
                    continue

            self.logger.info(f"Total books scraped: {len(all_books)}")
            return all_books

        except Exception as e:
            self.logger.error(f"Error scraping books: {str(e)}")
            return []
        finally:
            if self.driver:
                self.driver.quit()

    def load_existing_books(self) -> Dict[str, Book]:
        """Load existing books from JSON file."""
        if not os.path.exists(self.books_file):
            self.logger.info(
                f"Books file {self.books_file} does not exist, starting fresh"
            )
            return {}

        try:
            with open(self.books_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            books = {}
            for book_data in data.get("books", []):
                book = Book.from_dict(book_data)
                # Use title + author as key for deduplication
                key = f"{book.title}|{book.author or ''}"
                books[key] = book

            self.logger.info(
                f"Loaded {len(books)} existing books from {self.books_file}"
            )
            return books

        except Exception as e:
            self.logger.error(f"Error loading existing books: {str(e)}")
            return {}

    def save_books(
        self, books: List[Book], existing_books: Dict[str, Book] = None
    ) -> Dict:
        """Save books to JSON file and return update statistics."""
        if existing_books is None:
            existing_books = self.load_existing_books()

        # Merge new books with existing ones
        all_books = existing_books.copy()
        new_count = 0
        updated_count = 0

        for book in books:
            key = f"{book.title}|{book.author or ''}"

            if key not in all_books:
                all_books[key] = book
                new_count += 1
                self.logger.info(f"Added new book: {book.title}")
            else:
                # Update existing book but preserve read_status and notes
                existing = all_books[key]
                book.read_status = existing.read_status
                book.notes = existing.notes

                # Check if other fields were updated
                if (
                    book.description != existing.description
                    or book.url != existing.url
                    or book.category != existing.category
                ):
                    all_books[key] = book
                    updated_count += 1
                    self.logger.info(f"Updated existing book: {book.title}")

        # Save to file
        try:
            books_data = {
                "last_updated": datetime.now().isoformat(),
                "total_books": len(all_books),
                "books": [book.to_dict() for book in all_books.values()],
            }

            with open(self.books_file, "w", encoding="utf-8") as f:
                json.dump(books_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Saved {len(all_books)} books to {self.books_file}")

            return {
                "total_books": len(all_books),
                "new_books": new_count,
                "updated_books": updated_count,
                "file_path": self.books_file,
            }

        except Exception as e:
            self.logger.error(f"Error saving books: {str(e)}")
            raise

    def get_book_statistics(self) -> Dict:
        """Get statistics about the book collection."""
        books = self.load_existing_books()

        if not books:
            return {"total": 0, "read": 0, "unread": 0, "read_percentage": 0}

        read_count = sum(1 for book in books.values() if book.read_status)
        total_count = len(books)
        unread_count = total_count - read_count
        read_percentage = (read_count / total_count * 100) if total_count > 0 else 0

        return {
            "total": total_count,
            "read": read_count,
            "unread": unread_count,
            "read_percentage": round(read_percentage, 1),
        }

    def mark_book_as_read(
        self, title: str, author: str = None, notes: str = None
    ) -> bool:
        """Mark a specific book as read."""
        books = self.load_existing_books()
        key = f"{title}|{author or ''}"

        if key in books:
            books[key].read_status = True
            if notes:
                books[key].notes = notes

            # Save updated books
            self.save_books(list(books.values()), books)
            self.logger.info(f"Marked as read: {title}")
            return True
        else:
            self.logger.warning(f"Book not found: {title}")
            return False
