"""Factory for creating job appliers."""

from typing import Dict, Optional, Type
from app.appliers.base import BaseApplier
from app.appliers.seek import SeekApplier
from app.appliers.greenhouse import GreenhouseApplier

class JobApplierFactory:
    """Factory class for creating job appliers based on job board type."""

    _appliers: Dict[str, Type[BaseApplier]] = {
        "seek": SeekApplier,
        # Add more appliers here as they are implemented
        "greenhouse": GreenhouseApplier,
        # "workday": WorkdayApplier,
        # "lever": LeverApplier,
    }

    @classmethod
    def create_applier(cls, job_board: str) -> Optional[BaseApplier]:
        """
        Create an applier instance for the specified job board.

        Args:
            job_board: The name of the job board (e.g., 'seek', 'greenhouse')

        Returns:
            An instance of the appropriate applier, or None if not supported
        """
        applier_class = cls._appliers.get(job_board.lower())
        if applier_class:
            return applier_class()
        return None

    @classmethod
    def register_applier(cls, job_board: str, applier_class: Type[BaseApplier]):
        """
        Register a new applier class for a job board.

        Args:
            job_board: The name of the job board
            applier_class: The applier class to register
        """
        cls._appliers[job_board.lower()] = applier_class

    @classmethod
    def supported_job_boards(cls) -> list[str]:
        """Get a list of supported job boards."""
        return list(cls._appliers.keys())
