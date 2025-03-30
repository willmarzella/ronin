"""
Basic infrastructure that everything else depends on. Config handling, logging setup, environment variables. Keep this minimal - most "frameworks" bloat this with useless abstractions. You want just enough to make the rest work.
"""

from .config import load_config
from .logging import setup_logger

__all__ = ["load_config", "setup_logger"]
