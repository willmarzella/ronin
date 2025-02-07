"""Configuration loading and management."""

from pathlib import Path
from typing import Dict

import yaml
from loguru import logger

# Default config paths to check in order
CONFIG_PATHS = [
    "config/config.yaml",  # Local development
    "/app/config/config.yaml",  # Docker
    "config.yaml",  # Root directory
]


def load_config() -> Dict:
    for config_path in CONFIG_PATHS:
        path = Path(config_path)
        if path.exists():
            logger.info(f"Loading config from {path}")
            try:
                with open(path, "r") as file:
                    config = yaml.safe_load(file)
                return config
            except Exception as e:
                logger.error(f"Error loading config file {path}: {str(e)}")
                continue

    # If we get here, no config file was found
    raise FileNotFoundError(
        f"No config file found. Looked in: {', '.join(CONFIG_PATHS)}"
    )
