"""Configuration loading and management."""

from pathlib import Path
from typing import Dict

import yaml
from loguru import logger
from dotenv import load_dotenv
# Default config paths to check in order
CONFIG_PATHS = [
    "configs/config.yaml",  # Local development
    "/configs/config.yaml",  # Docker
    "configs/config.yaml",  # Root directory
]


def load_config() -> Dict:
    for config_path in CONFIG_PATHS:
        path = Path(config_path)
        if path.exists():
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

# also need to load the .env file

def load_env():
    load_dotenv()
    ROOT_DIR = Path(__file__).parent.parent
