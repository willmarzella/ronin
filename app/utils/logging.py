import os
import sys

from loguru import logger


def setup_logger():
    """Configure and setup logging."""

    # Configure loguru logger
    logger.remove()  # Remove default handler

    # Add console handler
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="INFO",
    )

    # Add file handler if log directory exists
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, "app.log")
    logger.add(
        log_file,
        rotation="1 day",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="DEBUG",
    )

    return logger
