import logging
import time

import schedule

from main import main as scraper_main


def job():
    """Run the scraper job"""
    logging.info("Starting scheduled job")
    try:
        scraper_main()
    except Exception as e:
        error_msg = f"❌ Error in scheduled job: {str(e)}"
        logging.error(error_msg)
    logging.info("Completed scheduled job")


def run_scheduler():
    # Schedule job to run every 2 hours
    schedule.every(2).hours.do(job)

    logging.info("Scheduler started. Will run every 2 hours.")

    # Run the job immediately on start
    job()

    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute for pending jobs


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    run_scheduler()
