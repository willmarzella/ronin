import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from models.blog_post import BlogPost
from services.mataroa_service import MataroaService


class PostPublisher:
    def __init__(self, mataroa_api_key: Optional[str] = None):
        """
        Initialize the post publisher

        Args:
            mataroa_api_key (Optional[str]): Mataroa API key for blog publishing
        """
        self.stats_file = "./tests/publishing_stats.json"
        self.stats = self._load_stats()
        self.mataroa_service = MataroaService(api_key=mataroa_api_key)

    def _load_stats(self) -> Dict:
        """Load publishing statistics from file"""
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, "r") as f:
                    stats = json.load(f)
                    if "published_urls" not in stats:
                        stats["published_urls"] = []
                    return stats
            except json.JSONDecodeError:
                return self._initialize_stats()
        return self._initialize_stats()

    def _initialize_stats(self) -> Dict:
        """Initialize empty publishing statistics"""
        return {
            "total_posts": 0,
            "categories": {"shitposting": 0, "sermonposting": 0, "nerdposting": 0},
            "last_published": None,
            "theme_frequency": {},
            "published_urls": [],
        }

    def _save_stats(self):
        """Save publishing statistics to file"""
        try:
            with open(self.stats_file, "w") as f:
                json.dump(self.stats, f, indent=2, default=str)
        except Exception as e:
            import logging

            logging.error(f"Failed to save stats: {str(e)}")

    def _update_stats(self, post: BlogPost, publish_result: Optional[Dict] = None):
        """
        Update publishing statistics with new post

        Args:
            post (BlogPost): Published blog post
            publish_result (Optional[Dict]): Result from Mataroa API containing URL
        """
        self.stats["total_posts"] += 1
        self.stats["categories"][post.category] += 1
        self.stats["last_published"] = datetime.now().isoformat()

        # Update theme frequency
        for theme in post.themes:
            theme_name = theme["name"]
            if theme_name not in self.stats["theme_frequency"]:
                self.stats["theme_frequency"][theme_name] = 0
            self.stats["theme_frequency"][theme_name] += 1

        # Track published URL if available
        if (
            publish_result
            and isinstance(publish_result, dict)
            and "url" in publish_result
        ):
            self.stats["published_urls"].append(
                {
                    "title": post.title,
                    "url": publish_result["url"],
                    "published_at": post.published_at.isoformat(),
                }
            )

        self._save_stats()

    def publish_post(self, post: BlogPost) -> Dict:
        """
        Publish a blog post to Mataroa blog

        Args:
            post (BlogPost): Blog post to publish

        Returns:
            Dict: Result from Mataroa API containing URL
        """
        try:
            # Clean post content for Mataroa
            clean_content = post.content
            # Remove any trailing closing braces that might be part of JSON structure
            if clean_content.endswith("}") and clean_content.count(
                "}"
            ) > clean_content.count("{"):
                clean_content = clean_content.rstrip().rstrip("}")

            # Publish to Mataroa blog
            result = self.mataroa_service.create_post(
                title=post.title,
                body=clean_content,
                published_at=post.published_at.strftime("%Y-%m-%d"),
            )

            # Validate result
            if not isinstance(result, dict):
                import logging

                logging.warning(f"Unexpected result from Mataroa API: {result}")
                result = {}

            # Update stats with publish result
            self._update_stats(post, result)
            return result

        except Exception as e:
            import logging

            logging.error(f"Mataroa API error: {str(e)}")
            # If Mataroa publishing fails, still update local stats
            self._update_stats(post)
            # Create a more informative error message
            error_msg = str(e)
            if "'published_urls'" in error_msg:
                error_msg = "Error with published_urls in stats. Stats have been updated to fix this issue."
            raise Exception(f"Failed to publish to Mataroa blog: {error_msg}")

    def get_publishing_stats(self) -> Dict:
        """Get current publishing statistics"""
        return self.stats

    def get_category_distribution(self) -> Dict[str, float]:
        """Calculate current category distribution"""
        total = self.stats["total_posts"] or 1  # Avoid division by zero
        return {
            category: count / total
            for category, count in self.stats["categories"].items()
        }

    def get_popular_themes(self, limit: Optional[int] = None) -> List[Dict]:
        """Get most frequently used themes"""
        themes = [
            {"name": name, "count": count}
            for name, count in self.stats["theme_frequency"].items()
        ]
        themes.sort(key=lambda x: x["count"], reverse=True)
        return themes[:limit] if limit else themes
