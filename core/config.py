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
    assert (
        isinstance(CONFIG_PATHS, list) and len(CONFIG_PATHS) > 0
    ), "CONFIG_PATHS must be non-empty list"

    for config_path in CONFIG_PATHS:
        assert isinstance(config_path, str), "Config path must be string"
        path = Path(config_path)
        if path.exists():
            try:
                with open(path, "r") as file:
                    config = yaml.safe_load(file)
                assert isinstance(config, dict), "Config must be a dictionary"
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
    """Load environment variables from .env file."""
    assert hasattr(load_dotenv, "__call__"), "load_dotenv must be callable"

    load_dotenv()
    root_dir = Path(__file__).parent.parent
    assert root_dir.exists(), "Root directory must exist"
    return root_dir
