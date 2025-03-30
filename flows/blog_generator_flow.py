#!/usr/bin/env python
"""
Blog Generator Flow for Prefect
This flow generates blog posts based on trending topics and content strategy.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add the parent directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))

import yaml
from dotenv import load_dotenv
from prefect import flow, task, get_run_logger
from prefect.blocks.system import Secret
from prefect.context import get_run_context

from openai import OpenAI

from utils.config import load_config
from tasks.blog_posts.topic_generator import TopicGenerator
from tasks.blog_posts.content_generator import ContentGenerator
from tasks.blog_posts.image_generator import ImageGenerator
from tasks.blog_posts.blog_publisher import BlogPublisher
from blocks.airtable_service import AirtableManager
from blocks.notification_service import NotificationService


@task(name="generate_blog_topics", retries=1)
def generate_blog_topics(config: Dict[str, Any], num_topics: int = 3) -> List[Dict]:
    """Generate blog post topic ideas based on trending topics and preferences."""
    logger = get_run_logger()
    logger.info(f"Generating {num_topics} blog post topics")

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize topic generator
    topic_generator = TopicGenerator(config, openai_client)

    # Generate topics
    topics = topic_generator.generate_topics(num_topics=num_topics)

    logger.info(f"Generated {len(topics)} blog post topics")
    for i, topic in enumerate(topics):
        logger.info(f"Topic {i+1}: {topic.get('title', 'Unknown title')}")

    return topics


@task(name="select_blog_topic", retries=1)
def select_blog_topic(topics: List[Dict], config: Dict[str, Any]) -> Dict:
    """Select the best blog topic from the generated options."""
    logger = get_run_logger()

    if not topics:
        logger.warning("No topics provided for selection")
        raise ValueError("No topics provided for selection")

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize topic generator (which also has topic ranking capability)
    topic_generator = TopicGenerator(config, openai_client)

    # Select the best topic
    selected_topic = topic_generator.select_best_topic(topics)

    logger.info(f"Selected blog topic: {selected_topic.get('title', 'Unknown title')}")
    return selected_topic


@task(name="generate_blog_content", retries=1)
def generate_blog_content(topic: Dict, config: Dict[str, Any]) -> Dict:
    """Generate the full blog post content for the selected topic."""
    logger = get_run_logger()
    topic_title = topic.get("title", "Unknown topic")
    logger.info(f"Generating blog content for: {topic_title}")

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize content generator
    content_generator = ContentGenerator(config, openai_client)

    # Generate blog content
    blog_post = content_generator.generate_blog_post(topic)

    # Add metadata
    blog_post["topic"] = topic
    blog_post["generation_date"] = datetime.now().isoformat()

    logger.info(f"Successfully generated blog content for: {topic_title}")
    logger.info(
        f"Blog stats: {len(blog_post.get('content', '').split())} words, {len(blog_post.get('sections', []))} sections"
    )

    return blog_post


@task(name="generate_blog_images", retries=2, retry_delay_seconds=60)
def generate_blog_images(blog_post: Dict, config: Dict[str, Any]) -> Dict:
    """Generate images for the blog post."""
    logger = get_run_logger()
    topic_title = blog_post.get("title", "Unknown blog")
    logger.info(f"Generating images for blog: {topic_title}")

    # Get OpenAI client
    openai_api_key = Secret.load("openai-api-key")
    openai_client = OpenAI(api_key=openai_api_key.get())

    # Initialize image generator
    image_generator = ImageGenerator(config, openai_client)

    try:
        # Generate main feature image
        logger.info("Generating main feature image")
        feature_image_path = image_generator.generate_feature_image(blog_post)
        blog_post["feature_image"] = feature_image_path

        # Generate section images if needed
        if config.get("blog", {}).get("generate_section_images", False):
            logger.info("Generating section images")
            section_images = image_generator.generate_section_images(blog_post)
            blog_post["section_images"] = section_images

        blog_post["images_generated"] = True
        logger.info(f"Successfully generated images for blog: {topic_title}")
        return blog_post
    except Exception as e:
        logger.error(f"Error generating images for blog {topic_title}: {str(e)}")
        blog_post["images_generated"] = False
        blog_post["image_error"] = str(e)
        return blog_post


@task(name="save_blog_to_airtable", retries=2, retry_delay_seconds=30)
def save_blog_to_airtable(blog_post: Dict) -> Dict:
    """Save the generated blog post to Airtable."""
    logger = get_run_logger()
    topic_title = blog_post.get("title", "Unknown blog")
    logger.info(f"Saving blog post to Airtable: {topic_title}")

    airtable = AirtableManager()

    try:
        # Save blog post to Airtable
        record_id = airtable.save_blog_post(blog_post)

        # Update blog post with record ID
        blog_post["airtable_id"] = record_id
        blog_post["saved_to_airtable"] = True

        logger.info(
            f"Successfully saved blog post to Airtable: {topic_title} (ID: {record_id})"
        )
        return blog_post
    except Exception as e:
        logger.error(f"Error saving blog post to Airtable: {topic_title}: {str(e)}")
        blog_post["saved_to_airtable"] = False
        blog_post["airtable_error"] = str(e)
        return blog_post


@task(name="publish_blog_post", retries=2, retry_delay_seconds=60)
def publish_blog_post(blog_post: Dict, config: Dict[str, Any]) -> Dict:
    """Publish the blog post to the configured platform."""
    logger = get_run_logger()
    topic_title = blog_post.get("title", "Unknown blog")

    if config.get("blog", {}).get("auto_publish", False) is False:
        logger.info(f"Auto-publish is disabled. Skipping publication of: {topic_title}")
        blog_post["published"] = False
        blog_post["publication_status"] = "skipped"
        return blog_post

    logger.info(f"Publishing blog post: {topic_title}")

    # Initialize blog publisher
    blog_publisher = BlogPublisher(config)

    try:
        # Publish blog post
        publication_result = blog_publisher.publish_blog_post(blog_post)

        # Update blog post with publication result
        blog_post["published"] = publication_result.get("success", False)
        blog_post["publication_status"] = (
            "published" if blog_post["published"] else "failed"
        )
        blog_post["publication_url"] = publication_result.get("url", "")
        blog_post["publication_date"] = datetime.now().isoformat()

        logger.info(f"Blog post publication result: {blog_post['publication_status']}")
        if blog_post["published"]:
            logger.info(f"Published URL: {blog_post['publication_url']}")

        return blog_post
    except Exception as e:
        logger.error(f"Error publishing blog post {topic_title}: {str(e)}")
        blog_post["published"] = False
        blog_post["publication_status"] = "error"
        blog_post["publication_error"] = str(e)
        return blog_post


@flow(name="Blog Generator", log_prints=True)
def blog_generator_flow(
    num_topics: int = 3, auto_publish: bool = None
) -> Dict[str, Any]:
    """
    Main blog generator flow that coordinates the creation and publication of blog posts.

    Args:
        num_topics: Number of topic ideas to generate before selection.
        auto_publish: Override for auto-publish setting in config.

    Returns:
        Dictionary with results of the blog generation process.
    """
    logger = get_run_logger()
    run_context = get_run_context()
    logger.info(f"Starting blog generator flow run: {run_context.flow_run.name}")

    # Load environment variables
    load_dotenv()

    # Load configuration
    config = load_config()

    # Override auto_publish if provided
    if auto_publish is not None:
        config["blog"]["auto_publish"] = auto_publish

    # Set up notification service
    notification_service = NotificationService(config)

    try:
        # Step 1: Generate blog topics
        topics = generate_blog_topics(config=config, num_topics=num_topics)

        if not topics:
            error_msg = "Failed to generate any blog topics"
            logger.error(error_msg)
            notification_service.send_error_notification(
                error_message=error_msg,
                context={"error_type": "GENERATION_ERROR"},
                pipeline_name="Blog Generator Pipeline",
            )
            return {"status": "error", "error": error_msg}

        # Step 2: Select best topic
        selected_topic = select_blog_topic(topics=topics, config=config)

        # Step 3: Generate blog content
        blog_post = generate_blog_content(topic=selected_topic, config=config)

        # Step 4: Generate images
        blog_post_with_images = generate_blog_images(blog_post=blog_post, config=config)

        # Step 5: Save to Airtable
        saved_blog_post = save_blog_to_airtable(blog_post=blog_post_with_images)

        # Step 6: Publish blog post if enabled
        final_blog_post = publish_blog_post(blog_post=saved_blog_post, config=config)

        # Send success notification
        if final_blog_post.get("published", False):
            notification_service.send_success_notification(
                message=f"Successfully published blog post: {final_blog_post.get('title', 'Unknown title')}",
                context={
                    "title": final_blog_post.get("title", "Unknown title"),
                    "url": final_blog_post.get("publication_url", ""),
                    "word_count": len(final_blog_post.get("content", "").split()),
                },
                pipeline_name="Blog Generator Pipeline",
            )
        elif final_blog_post.get("saved_to_airtable", False):
            notification_service.send_success_notification(
                message=f"Successfully generated blog post (not published): {final_blog_post.get('title', 'Unknown title')}",
                context={
                    "title": final_blog_post.get("title", "Unknown title"),
                    "airtable_id": final_blog_post.get("airtable_id", ""),
                    "word_count": len(final_blog_post.get("content", "").split()),
                },
                pipeline_name="Blog Generator Pipeline",
            )

        logger.info(
            f"Blog generator flow complete for: {final_blog_post.get('title', 'Unknown title')}"
        )

        return {
            "status": "complete",
            "blog_post": final_blog_post,
            "published": final_blog_post.get("published", False),
            "saved_to_airtable": final_blog_post.get("saved_to_airtable", False),
        }

    except Exception as e:
        error_msg = f"Error in blog generator flow: {str(e)}"
        logger.error(error_msg)

        # Send error notification
        notification_service.send_error_notification(
            error_message=error_msg,
            context={"error_type": "FLOW_ERROR"},
            pipeline_name="Blog Generator Pipeline",
        )

        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    blog_generator_flow()
