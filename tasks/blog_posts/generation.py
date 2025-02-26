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
                for theme in themes
            ]
        )

        print("category: ", category)
        print("theme_info: ", theme_info)

        system_prompt = f"""I will provide you with raw, unstructured thoughts and ideas throughout my day. These will be short, stream-of-consciousness notes that are not fully developed. There'll be themes attached to these notes and ideas to give you a better idea of what I'm looking for.  

Your role is to transform these scattered thoughts into a coherent personal reflection. The goal is to collect and refine these ideas so I can focus on my daily work without worrying about what to write while also allowing me to review and get feedback on my ideas.  

Content falls into three main categories:  
1. **Nerdposting** – deep dives, Wikipedia rabbit holes, history, art, movies, music, and general internet exploration.  
2. **Sermonposting** – philosophical reflections, life advice, etc.  
3. **Shitposting** – humor, irreverence, self-deprecating jokes, and absurd observations.  



#### **Instructions:**  
- I will give you a list of ideas.  
- Choose **only one** idea that has the most promising potential for a strong reflective note.  
- Write a reflection expanding on that idea using the example, and tone and style that I've provided below.
- IMPORTANT: Format the content with clear paragraphs and line breaks. Each paragraph should be separated by a blank line.
- Use natural paragraph breaks to make the content readable and engaging.
- Never write the entire post as one big paragraph.

#### **Tone:**  
{OVERALL_TONE}

#### **Title Requirements:**  
- **Max 70 characters**  
- **No punctuation or colons**  
- **Should read like a short sentence, i.e no capitalizing the first letter of each word**  

#### *Content Requirements:*
- The reflective note should read like a stream of consciousness or a Twitter thread, with short paragraphs and line breaks. But I don't want it to be too fragmented or too cringey with emojis and hashtags should just be text.
- It should always be written in the first person. These are MY thoughts and experiences and I never want to come across as arrogant or self-important like I'm telling you how to live your life. I'm just rambling on about my own thoughts and experiences and what's worked for me.
- **Max 200 words**

#### **Example:**

Below is an example of the kind of note I'm looking for (each new paragraph is separated by a blank line):

Oh my god. This entire time, this entire *decade* I've never felt "fear of failure" and "perfectionism" describe my feelings when I get stuck. But I can never articulate it better. I found it: to me it feels as if *trying* itself means I've failed miserably.

Not as in "failure in the process of trying to do good" is bad, but *trying*, in and of itself, regardless of outcomes, means I deserve punishment and scorn.

somewhere along the way I must've realized that I'm not allowed to do anything outside of the very small set of behavior I was supposed to do. anything beyond that, anything "out of the ordinary" is complete and utter danger zones.

the feeling grows along the scale from how sinful it is. the more heinously unconventional, the more I look away. looking directly at it hurts--because I couldn't have done it before when I was young and had no freedom, and acknowledging the cage hurts even moreso

The fact that I AM looking at it directly eye to eye now speaks to how much *safer* I am than before. How I'm no longer experiencing a situation where I'm going to be insulted for every single moment of my existence. Lucky, I am lucky to be able to meet it.

#### **Response Format:**  
{{
    "title": "Generated title (70 characters max, no punctuation or colons)",
    "content": "Generated content with proper line breaks between paragraphs. Each paragraph should be separated by a blank line. Never write the entire post as one big block of text."
}}

**Important:** Do not include any unnecessary closing braces (`}}`) unless they are part of the content.
        """

        try:
            response = self.ai_service.chat_completion(
                system_prompt=system_prompt,
                user_message=f"Create a {category} post ({prompt}) on the below ideas and themes. Remember the tone and style of the post that I've provided:\n\n {OVERALL_TONE}. \n\n ------ \n\nTOPICS OR IDEAS TO CHOOSE FROM: {theme_info}",
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
