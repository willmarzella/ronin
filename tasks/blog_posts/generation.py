"""Post generation using AI service."""

import logging
from typing import Dict, List, Optional

from services.ai_service import AIService
from tasks.blog_posts.analysis import ThemeAnalyzer
from tasks.blog_posts.prompts import (
    EXAMPLES,
    NERDPOSTING_PROMPT,
    OVERALL_TONE,
    SERMONPOSTING_PROMPT,
    SHITPOSTING_PROMPT,
)


class PostGenerator:
    def __init__(self, ai_service: AIService):
        """
        Initialize post generator with AI service.

        Args:
            ai_service (AIService): Instance of the AI service
        """
        self.ai_service = ai_service
        self.theme_analyzer = ThemeAnalyzer(ai_service)
        self.prompts = {
            "shitposting": SHITPOSTING_PROMPT,
            "sermonposting": SERMONPOSTING_PROMPT,
            "nerdposting": NERDPOSTING_PROMPT,
        }

    def generate_post(
        self, themes: List[Dict], category: str = None
    ) -> Optional[Dict[str, str]]:
        """
        Generate a blog post based on themes and category.
        If no category is provided, the most prevalent category based on themes will be used.
        Returns None if no suitable themes are found for the category.

        Args:
            themes: List of theme objects
            category: Post category (shitposting, sermonposting, nerdposting), or None to auto-detect

        Returns:
            Optional[Dict[str, str]]: Dictionary containing generated title and content,
            or None if no suitable themes are found
        """
        if not themes:
            logging.warning("No themes provided for post generation")
            return None

        # If no category is provided, determine the most prevalent one
        if category is None:
            category = self.theme_analyzer.determine_prevalent_category(themes)
            logging.info(f"Auto-detected category: {category}")

        # Check if there are any themes suitable for this category
        if not self.theme_analyzer.evaluate_themes_for_category(themes, category):
            logging.info(
                f"No suitable themes found for category '{category}'. Using general themes instead."
            )
            # We'll continue with the detected category but use all themes
            # This ensures we always generate a post with the most prevalent category

        # Get the appropriate prompt for the category
        prompt = self.prompts.get(category.lower())
        if not prompt:
            raise ValueError(f"Invalid category: {category}")

        # Prepare theme information for the prompt
        theme_info = "\n".join(
            [
                f"Theme: {theme['name']}\n"
                f"Examples: {', '.join(theme['examples'])}\n"
                for theme in themes
            ]
        )

        print("category: ", category)
        print("theme_info: ", theme_info)

        system_prompt = f"""THE EXACT WAY I WANT YOU TO WRITE:
{EXAMPLES}

        CONTEXT:
Content Categories:
1. Nerdposting – Deep intellectual explorations challenging accepted wisdom
2. Sermonposting – Personal revelations and uncomfortable truths about growth
3. Shitposting – Sharp, irreverent observations exposing deeper societal truths

Writing Guidelines:
- Start with surface ideas, then peel back layers
- Show evolution of thinking about the specific idea
- Make unexpected connections
- Be raw and authentic, but never gratuitously edgy
- Challenge assumptions, including your own

Style Requirements:
- First person perspective
- Conversational but intellectually rigorous
- Precise language
- Natural flow between paragraphs
- Build tension between initial understanding and deeper revelations
- End with most provocative or insightful observation

Tone:
{OVERALL_TONE}

WARNINGS:
- Focus on ONE theme only - go deep rather than wide
- Don't be controversial just for controversy's sake
- NEVER EVER USE "—" in your writing, it's a horrible character and I will kill you
- Avoid self-importance in writing style
- Don't use emotional manipulation for vulnerability
- No punctuation or colons in titles
- Keep paragraphs under 80 words

RETURN FORMAT:
{{
    "title": "Generated title (70 chars max, no punctuation)",
    "content": "Generated content exploring a single idea through multiple angles"
}}

GOAL:
You are a master of transforming raw, unfiltered thoughts into compelling narratives. Your task is to take a single idea from provided themes and explore it deeply, crafting it into a provocative, authentic piece that challenges conventional thinking while maintaining intellectual honesty.
"""

        try:
            response = self.ai_service.chat_completion(
                system_prompt=system_prompt,
                user_message=f"Create a post ({prompt}). REMEMBER THE STRUCTURE OF THE TITLE TOO. Remember the tone and style of the post that I've provided:\n\n {EXAMPLES}. \n\n ------ \n\nIDEAS TO WRITE ABOUT: {theme_info}",
                temperature=0.8,
            )

            if not response:
                logging.error("AI service returned empty response")
                return {"title": "Error: Post Generation Failed", "content": ""}

            # Extract and clean the title and content
            title = response.get("title", "Untitled Post")
            content = response.get("content", "Failed to generate content")

            # Additional cleaning for content
            if content.endswith("}") and content.count("}") > content.count("{"):
                content = content.rstrip().rstrip("}")
                logging.info("Removed trailing brace from content")

            logging.info(f"Successfully generated post with title: {title}")
            return {"title": title, "content": content, "category": category}

        except Exception as e:
            logging.error(f"Error generating post: {str(e)}")
            return {
                "title": "Error: Post Generation Failed",
                "content": f"Generation error: {str(e)}",
                "category": category,
            }
