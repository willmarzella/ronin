#!/usr/bin/env python3
"""
✍️ Blog Generation Script
Simple script to generate blog posts locally.
"""

import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ronin.apps.blog_generation.generation import PostGenerator
from ronin.core.config import load_config
from ronin.services.ai_service import AIService


def main():
    """Main blog generation function."""
    print("✍️ Starting blog generation...")

    try:
        # Load configuration
        config = load_config()
        print("📋 Configuration loaded")

        # Initialize AI service and blog generator
        ai_service = AIService()
        generator = PostGenerator(ai_service)
        print("✅ Blog generator initialized")

        # Generate a sample blog post
        print("✍️ Generating blog post...")

        # Create sample themes for blog generation
        sample_themes = [
            {
                "name": "Data Engineering Automation",
                "examples": [
                    "AI-powered job search",
                    "automated data pipelines",
                    "machine learning workflows",
                ],
                "content": "Data engineering automation and AI-powered job search",
                "category": "nerdposting",
                "sentiment": "positive",
                "relevance_score": 0.9,
            },
            {
                "name": "Modern Data Infrastructure",
                "examples": [
                    "scalable data pipelines",
                    "cloud platforms",
                    "containerized applications",
                ],
                "content": "Building scalable data pipelines with modern tools",
                "category": "nerdposting",
                "sentiment": "positive",
                "relevance_score": 0.8,
            },
        ]

        # Generate the blog post
        blog_post = generator.generate_post(sample_themes, category="nerdposting")

        if blog_post:
            print("✅ Blog post generated successfully!")
            print(f"\n📝 Title: {blog_post.get('title', 'N/A')}")
            print(f"\n📄 Content Preview:")
            content = blog_post.get("content", "")
            preview = content[:200] + "..." if len(content) > 200 else content
            print(preview)
            print(f"\n📊 Full content length: {len(content)} characters")
        else:
            print("❌ Failed to generate blog post")

        print("✅ Blog generation complete!")

    except Exception as e:
        print(f"❌ Error during blog generation: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
