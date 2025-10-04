#!/usr/bin/env python3
"""
📚 Book Scraping Script
Simple script to scrape book content locally.
"""

import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ronin.apps.book_scraping.actualized_scraper import ActualizedScraper
from ronin.core.config import load_config


def main():
    """Main book scraping function."""
    print("📚 Starting book scraping...")

    try:
        # Load configuration
        config = load_config()
        print("📋 Configuration loaded")

        # Initialize book scraper
        scraper = ActualizedScraper(config)
        print("✅ Book scraper initialized")

        # Check if credentials are available
        username = config.get("actualized", {}).get("username")
        password = config.get("actualized", {}).get("password")

        if not username or not password:
            print("⚠️ No Actualized.org credentials found in config")
            print(
                "ℹ️ Please add username and password to config.yaml under 'actualized' section"
            )
            return

        # Start book scraping
        print("📚 Starting book scraping from Actualized.org...")
        print(f"🔐 Logging in as: {username}")

        try:
            books = scraper.scrape_books(username, password)

            if books:
                print(f"✅ Successfully scraped {len(books)} books!")
                print("\n📚 Book Summary:")
                for i, book in enumerate(books[:5], 1):  # Show first 5 books
                    print(f"  {i}. {book.title}")
                    print(f"     Author: {book.author}")
                    print(f"     Rating: {book.rating}")
                    print(f"     Status: {book.status}")
                    print()

                if len(books) > 5:
                    print(f"  ... and {len(books) - 5} more books")

                # Get statistics
                stats = scraper.get_book_statistics()
                print(f"\n📊 Statistics:")
                print(f"  Total books: {stats.get('total_books', 0)}")
                print(f"  Read books: {stats.get('read_books', 0)}")
                print(f"  Average rating: {stats.get('average_rating', 0):.1f}")
            else:
                print("ℹ️ No books found or scraping failed")

        except Exception as scrape_error:
            print(f"❌ Error during scraping: {scrape_error}")
            print("ℹ️ This might be due to login issues or website changes")

        print("✅ Book scraping complete!")

    except Exception as e:
        print(f"❌ Error during book scraping: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
