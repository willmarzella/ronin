import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.blog_posts import (
    NoteParser,
    ThemeAnalyzer,
    CategorySelector,
    CategoryDistribution,
    PostPublisher,
    PostGenerator,
)
from blocks.ai_service import AIService
from models.blog_post import BlogPost

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # format: "username/repo"
MATAROA_API_KEY = os.getenv("MATAROA_API_KEY")
AI_API_KEY = os.getenv("OPENAI_API_KEY")
OUTPUT_DIR = os.getenv("BLOG_OUTPUT_DIR", "output/blog_posts")


class BlogPostPipeline:
    def __init__(self):
        """Initialize all components of the blog post pipeline"""
        # Initialize services
        self.ai_service = AIService(api_key=AI_API_KEY)

        # Initialize components
        self.note_parser = NoteParser(github_token=GITHUB_TOKEN, repo_name=GITHUB_REPO)
        self.theme_analyzer = ThemeAnalyzer(ai_service=self.ai_service)
        self.post_generator = PostGenerator(ai_service=self.ai_service)
        self.category_selector = CategorySelector(
            distribution=CategoryDistribution(
                shitposting=0.25, sermonposting=0.25, nerdposting=0.50
            )
        )
        self.post_publisher = PostPublisher(mataroa_api_key=MATAROA_API_KEY)

        # Pipeline context
        self.context: Dict[str, Any] = {}

    def fetch_and_parse_notes(self, days_lookback: int = 7) -> List[Dict]:
        """
        Task 1: Fetch and parse notes from GitHub repository
        """
        logger.info(f"Fetching notes modified in the last {days_lookback} days")
        notes = self.note_parser.get_repo_notes(
            directory_path="02 - timeline/daily-notes", days=days_lookback
        )

        if not notes:
            logger.warning("No modified notes found in the specified time period")
            return []

        logger.info(f"Found {len(notes)} modified notes")
        self.context["notes"] = notes
        return notes

    def analyze_themes(self) -> Optional[List[Dict]]:
        """
        Task 2: Analyze notes and extract themes
        """
        notes = self.context.get("notes")
        if not notes:
            logger.warning("No notes available for theme analysis")
            return None

        logger.info("Analyzing themes from notes")
        themes = self.theme_analyzer.analyze_notes(notes)

        if not themes:
            logger.warning("No themes extracted from notes")
            return None

        logger.info(f"Extracted {len(themes)} themes")
        self.context["themes"] = themes
        return themes

    def generate_post(self) -> Optional[BlogPost]:
        """
        Task 4: Generate the blog post using AI service
        """
        themes = self.context.get("themes")

        if not themes:
            logger.warning("Missing required context for post generation")
            return None

        logger.info("Generating post with auto-detected category")

        try:
            # Generate post using PostGenerator with auto-detected category
            generated_content = self.post_generator.generate_post(
                themes=themes,
                category=None,  # Let the generator auto-detect the category
            )

            # Check if post generation was skipped due to no suitable themes
            if generated_content is None:
                logger.info(
                    f"No suitable themes found for auto-detected category. Skipping post generation."
                )
                return None

            # Create BlogPost object
            post = BlogPost(
                title=generated_content["title"],
                content=generated_content["content"],
                category=generated_content["category"],  # Use the detected category
                themes=themes,
                published_at=datetime.now(),
                metadata={
                    "generation_category": generated_content["category"]
                },  # Use the detected category
            )

            logger.info("Successfully generated post")
            self.context["post"] = post
            return post

        except Exception as e:
            logger.error(f"Failed to generate post: {str(e)}")
            return None

    def publish_post(self) -> Optional[Dict]:
        """
        Task 5: Publish the generated post to Mataroa
        """
        post = self.context.get("post")
        if not post:
            logger.warning("No post available for publishing")
            return None

        try:
            logger.info("Publishing post to Mataroa")
            result = self.post_publisher.publish_post(post)

            # Record in category history
            self.category_selector.record_post(post.category)

            logger.info(
                f"Successfully published post to {result.get('url', 'unknown URL')}"
            )
            return result

        except Exception as e:
            logger.error(f"Failed to publish post: {str(e)}")
            return None

    def run(self) -> Dict[str, Any]:
        """
        Run the blog post generation pipeline
        """
        start_time = datetime.now()
        logger.info("Starting blog post pipeline")

        try:
            # Step 1: Fetch and parse notes
            notes = self.fetch_and_parse_notes()
            if not notes:
                return self._create_result(
                    "skipped", "No notes found for the specified time period"
                )

            # Step 2: Analyze themes
            themes = self.analyze_themes()
            if not themes:
                return self._create_result("skipped", "No themes extracted from notes")

            # Step 3: Generate post (with auto-detected category)
            post = self.generate_post()
            if not post:
                return self._create_result(
                    "skipped", "Post generation skipped due to no suitable themes"
                )

            # Step 4: Publish post
            result = self.publish_post()
            if not result:
                return self._create_result("error", "Post publishing failed")

            # Calculate statistics
            duration = (datetime.now() - start_time).total_seconds()
            stats = self.post_publisher.get_publishing_stats()
            distribution = self.category_selector.get_category_distribution()

            return {
                "status": "success",
                "url": result.get("url"),
                "duration_seconds": duration,
                "stats": stats,
                "distribution": distribution,
                "post": {
                    "title": post.title,
                    "category": post.category,
                    "themes": [t["name"] for t in post.themes],
                },
            }

        except Exception as e:
            logger.error(f"Pipeline failed: {str(e)}")
            return self._create_result("error", str(e))

    def _create_result(self, status: str, message: str) -> Dict[str, Any]:
        """Helper method to create a result dictionary"""
        return {
            "status": status,
            "error": message,
            "duration_seconds": (
                datetime.now() - self.context.get("start_time", datetime.now())
            ).total_seconds(),
        }


def main():
    """Main entry point for the blog post pipeline"""
    try:
        # Check for required environment variables
        required_vars = [
            "GITHUB_TOKEN",
            "GITHUB_REPO",
            "MATAROA_API_KEY",
            "OPENAI_API_KEY",
        ]
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            logger.error(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )
            return

        # Run the pipeline
        pipeline = BlogPostPipeline()
        results = pipeline.run()

        # Print summary
        if results["status"] == "success":
            print("\nPipeline Summary:")
            print(f"Post Published: {results['url']}")
            print(f"Duration: {results['duration_seconds']:.2f} seconds")
            print("\nCategory Distribution:")
            for category, ratio in results["distribution"].items():
                print(f"- {category}: {ratio:.2%}")
            print("\nExtracted Themes:")
            for theme in results["post"]["themes"]:
                print(f"- {theme}")
        elif results["status"] == "skipped":
            print(f"\nPost generation skipped: {results['error']}")
            print(f"Duration: {results['duration_seconds']:.2f} seconds")
            print(
                "\nConsider trying a different category or adding more content with relevant themes."
            )
        else:
            print(f"\nPipeline failed: {results['error']}")

    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
