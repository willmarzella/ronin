import random
from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class CategoryDistribution:
    shitposting: float = 0.25
    sermonposting: float = 0.25
    nerdposting: float = 0.50

    def validate(self) -> bool:
        """Check if distribution ratios sum to 1.0"""
        total = self.shitposting + self.sermonposting + self.nerdposting
        return abs(total - 1.0) < 0.001


class CategorySelector:
    def __init__(self, distribution: CategoryDistribution = CategoryDistribution()):
        """
        Initialize the category selector with target distribution ratios

        Args:
            distribution (CategoryDistribution): Target distribution of content categories
        """
        if not distribution.validate():
            raise ValueError("Category distribution ratios must sum to 1.0")
        self.distribution = distribution
        self.history: List[Tuple[str, datetime]] = []

    def get_current_distribution(self, days: int = 30) -> Dict[str, float]:
        """
        Calculate the current distribution of categories over the specified time period

        Args:
            days (int): Number of days to look back

        Returns:
            Dict[str, float]: Current distribution ratios
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_posts = [post for post in self.history if post[1] >= cutoff]
        total_posts = len(recent_posts) or 1  # Avoid division by zero

        return {
            "shitposting": len([p for p in recent_posts if p[0] == "shitposting"])
            / total_posts,
            "sermonposting": len([p for p in recent_posts if p[0] == "sermonposting"])
            / total_posts,
            "nerdposting": len([p for p in recent_posts if p[0] == "nerdposting"])
            / total_posts,
        }

    def calculate_category_weights(self) -> Dict[str, float]:
        """
        Calculate weights for each category based on current vs target distribution

        Returns:
            Dict[str, float]: Weight for each category
        """
        current = self.get_current_distribution()

        # Calculate how far each category is from its target
        deficits = {
            "shitposting": max(
                0, self.distribution.shitposting - current["shitposting"]
            ),
            "sermonposting": max(
                0, self.distribution.sermonposting - current["sermonposting"]
            ),
            "nerdposting": max(
                0, self.distribution.nerdposting - current["nerdposting"]
            ),
        }

        # If all categories are at or above target, use base distribution
        if all(v == 0 for v in deficits.values()):
            return {
                "shitposting": self.distribution.shitposting,
                "sermonposting": self.distribution.sermonposting,
                "nerdposting": self.distribution.nerdposting,
            }

        # Normalize deficits to sum to 1.0
        total_deficit = sum(deficits.values()) or 1.0  # Avoid division by zero
        return {k: v / total_deficit for k, v in deficits.items()}

    def select_category(self) -> str:
        """
        Select a category based on current distribution and target ratios

        Returns:
            str: Selected category name
        """
        weights = self.calculate_category_weights()
        categories = list(weights.keys())
        probabilities = list(weights.values())

        selected = random.choices(categories, weights=probabilities, k=1)[0]
        self.history.append((selected, datetime.now()))

        return selected

    def record_post(self, category: str, timestamp: datetime = None):
        """
        Record a post in the history

        Args:
            category (str): Category of the post
            timestamp (datetime, optional): Timestamp of the post. Defaults to current time.
        """
        if timestamp is None:
            timestamp = datetime.now()
        self.history.append((category, timestamp))

    def get_category_prompt(self, category: str) -> str:
        """
        Get the appropriate prompt template for the selected category

        Args:
            category (str): Selected category name

        Returns:
            str: Prompt template for the category
        """
        from tasks.blog_posts.prompts import (
            SHITPOSTING_PROMPT,
            SERMONPOSTING_PROMPT,
            NERDPOSTING_PROMPT,
        )

        prompts = {
            "shitposting": SHITPOSTING_PROMPT,
            "sermonposting": SERMONPOSTING_PROMPT,
            "nerdposting": NERDPOSTING_PROMPT,
        }

        return prompts.get(category, NERDPOSTING_PROMPT)

    def get_category_distribution(self) -> Dict[str, float]:
        """
        Get the current target distribution of categories

        Returns:
            Dict[str, float]: Target distribution ratios
        """
        return {
            "shitposting": self.distribution.shitposting,
            "sermonposting": self.distribution.sermonposting,
            "nerdposting": self.distribution.nerdposting,
        }
