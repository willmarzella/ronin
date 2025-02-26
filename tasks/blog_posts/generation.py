"""Post generation using AI service."""

from typing import Dict, List, Optional
import logging
from services.ai_service import AIService
from tasks.blog_posts.prompts import (
    SHITPOSTING_PROMPT,
    SERMONPOSTING_PROMPT,
    NERDPOSTING_PROMPT,
    OVERALL_TONE,
)
from tasks.blog_posts.analysis import ThemeAnalyzer


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
                f"Significance: {theme.get('significance', 'N/A')}\n"
                for theme in themes
            ]
        )

        print("category: ", category)
        print("theme_info: ", theme_info)

        system_prompt = f"""I will provide you with raw, unstructured thoughts and ideas throughout my day. These will be short, stream-of-consciousness notes that are not fully developed. There'll be themes attached to these notes and ideas to give you a better idea of what I'm looking for.  

Your role is to transform these scattered thoughts into a coherent personal reflection. The goal is to collect and refine these ideas so I can focus on my daily work without worrying about what to write while also allowing me to review and get feedback on my ideas.  

#### **Context:**  
I am a software engineer specializing in data modeling and data engineering. My blog content generally covers:  
- **Software Engineering** – technical insights, culture, and industry trends.  
- **Philosophy & Life** – broader reflections on work, thinking, and personal growth.  

Content falls into three main categories:  
1. **Nerdposting** – deep dives, Wikipedia rabbit holes, history, art, movies, music, and general internet exploration.  
2. **Sermonposting** – philosophical reflections, life advice, etc.  
3. **Shitposting** – humor, irreverence, self-deprecating jokes, and absurd observations.  

#### **Instructions:**  
- I will give you a list of ideas.  
- Choose **only one** idea that has the most promising potential for a strong note.  
- Write a reflection expanding on that idea using the tone and style that I've provided below.
- IMPORTANT: Format the content with clear paragraphs and line breaks. Each paragraph should be separated by a blank line.
- Use natural paragraph breaks to make the content readable and engaging.
- Never write the entire post as one big paragraph.

#### **Tone:**  
{OVERALL_TONE}

#### **Title Requirements:**  
- **Max 70 characters**  
- **No punctuation or colons**  
- **Should read like a short sentence, i.e no capitalizing the first letter of each word**  

#### **Response Format:**  
{{
    "title": "Generated title (70 characters max, no punctuation or colons)",
    "content": "Generated content with proper line breaks between paragraphs. Each paragraph should be separated by a blank line. Never write the entire post as one big block of text."
}}

**Important:** Do not include any unnecessary closing braces (`}}`) unless they are part of the markdown content.
        """

        try:
            response = self.ai_service.chat_completion(
                system_prompt=system_prompt,
                user_message=f"Create a reflection on the below ideas and themes. Remember the tone and style of the post that I've provided:\n\n {OVERALL_TONE}. \n\n ------ \n\nTOPICS OR IDEAS TO CHOOSE FROM: {theme_info}",
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
