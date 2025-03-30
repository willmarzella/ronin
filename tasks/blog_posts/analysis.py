"""Theme analysis using AI service."""

from typing import Dict, List
from blocks.ai_service import AIService
import logging
from tasks.blog_posts.prompts import OVERALL_TONE


class ThemeAnalyzer:
    def __init__(self, ai_service: AIService):
        """
        Initialize the theme analyzer with an AI service

        Args:
            ai_service (AIService): Instance of the AI service for theme extraction
        """
        self.ai_service = ai_service

    def consolidate_notes(self, notes: List[Dict]) -> str:
        """
        Combine all note content into a single corpus

        Args:
            notes (List[Dict]): List of note dictionaries

        Returns:
            str: Combined note content
        """
        consolidated = []
        for note in notes:
            content = note.get("content", "").strip()
            if content:
                consolidated.append(
                    f"# {note.get('path', 'Untitled Note')}\n\n{content}"
                )

        return "\n\n---\n\n".join(consolidated)

    def extract_themes(self, content: str, max_themes: int = 5) -> List[Dict]:
        """
        Extract themes from content using AI service

        Args:
            content (str): Text content to analyze
            max_themes (int): Maximum number of themes to extract

        Returns:
            List[Dict]: List of theme objects with name and examples
        """

        system_prompt = f"""CONTEXT:
Key Areas of Focus:
1. CONTROVERSY & PROVOCATION
- Ideas that push boundaries and challenge social norms
- Thoughts that make people uncomfortable but contain deep insight
- Perspectives opposing current mainstream narratives
- Uncomfortable truths and revelations

2. INTELLECTUAL EVOLUTION
- Initial naive thoughts developing into nuanced perspectives
- Moments of intellectual crisis or paradigm shifts
- Contradictions between earlier and later thoughts
- Instances of questioning conventional wisdom

3. NARRATIVE THREADS
- Recurring motifs showing intellectual development
- Patterns of questioning and revelation
- Tension between different belief systems
- Signs of wrestling with difficult truths

Content Characteristics:
- Politically incorrect but intellectually honest
- Challenging to popular narratives
- Personally revealing or vulnerable
- Seemingly contradictory or paradoxical
- Raw, unfiltered thoughts revealing deeper truths

Tone & Personality Context:
{OVERALL_TONE}

RETURN FORMAT:
{{
    "themes": [
        {{
            "name": "Idea sentence or thesis or title (should read like a provocative statement or summary of the idea, 70 chars max, no punctuation)",
            "examples": ["Summary of the idea, max 200 words"]
        }}
    ]
}}

WARNINGS:
- Limit response to FIVE (5) ideas maximum
- Return ONLY raw JSON without any formatting
- No markdown, code blocks, or additional text
- Focus on the most mature and evolving ideas
- Each idea summary must not exceed 200 words

GOAL:
You are a provocative theme extraction expert analyzing personal notes. Your task is to identify and extract the most controversial, irreverent, and evolving ideas that challenge conventional wisdom. Look for thoughts that might be too raw or controversial for casual conversation but represent important intellectual territory.
"""

        response = self.ai_service.chat_completion(
            system_prompt=system_prompt,
            user_message=content,
            temperature=0.7,  # Increased temperature for more creative/diverse responses
        )

        logging.info(f"Theme extraction response: {response}")

        if response and "themes" in response:
            themes = response["themes"]
            return themes[:max_themes] if max_themes else themes
        return []

    def analyze_notes(self, notes: List[Dict]) -> List[Dict]:
        """
        Analyze notes and return theme information

        Args:
            notes (List[Dict]): List of note dictionaries

        Returns:
            List[Dict]: List of theme objects with additional metadata
        """
        # Consolidate all note content
        corpus = self.consolidate_notes(notes)
        if not corpus:
            return []

        # Extract themes
        themes = self.extract_themes(corpus)

        # Add metadata and frequency analysis
        for theme in themes:
            theme["frequency"] = self._calculate_theme_frequency(theme, notes)
            theme["related_notes"] = self._find_related_notes(theme, notes)

        return themes

    def evaluate_themes_for_category(self, themes: List[Dict], category: str) -> bool:
        """
        Evaluate if the extracted themes are suitable for a specific content category

        Args:
            themes (List[Dict]): List of theme objects
            category (str): Content category (shitposting, sermonposting, nerdposting)

        Returns:
            bool: True if themes are suitable for the category, False otherwise
        """
        if not themes:
            logging.info(f"No themes available for {category}")
            return False

        # Define category-specific keywords based on the three principles
        category_keywords = {
            # Friendliness keywords (shitposting)
            "shitposting": [
                "nourishing",
                "supportive",
                "encouraging",
                "comfortable",
                "honest feelings",
                "friend",
                "friendship",
                "neediness",
                "insecurities",
                "abundance",
                "compliments",
                "gracious",
                "host",
                "conversation",
                "social",
                "connection",
                "community",
                "empathy",
                "kindness",
                "generosity",
                "warmth",
                "welcoming",
            ],
            # Ambition keywords (sermonposting)
            "sermonposting": [
                "dream bigger",
                "larger life",
                "ambition",
                "desire",
                "power",
                "prestige",
                "intimate",
                "do more",
                "be more",
                "see more",
                "learn more",
                "know more",
                "imagination",
                "bottleneck",
                "good",
                "create",
                "untethered",
                "dangerous",
                "temper",
                "good taste",
                "sensitivity",
                "tremendous",
                "potential",
                "growth",
                "vision",
                "purpose",
            ],
            # Nerdiness keywords (nerdposting)
            "nerdposting": [
                "taste",
                "curiosity",
                "beautiful",
                "nerds",
                "music",
                "technology",
                "science",
                "movies",
                "books",
                "exploring",
                "interests",
                "joy",
                "gift",
                "liberate",
                "worrying",
                "opinions",
                "rigorous",
                "honest",
                "regard",
                "thoughts",
                "valuing",
                "expertise",
                "knowledge",
                "discovery",
                "analysis",
                "insight",
            ],
        }

        # Get keywords for the requested category
        keywords = category_keywords.get(category.lower(), [])
        if not keywords:
            logging.warning(f"Unknown category: {category}")
            return False

        # Check if any theme matches the category keywords
        for theme in themes:
            theme_text = (f"{theme['name']} {' '.join(theme['examples'])} ").lower()

            for keyword in keywords:
                if keyword.lower() in theme_text:
                    logging.info(
                        f"Theme '{theme['name']}' matches category '{category}'"
                    )
                    return True

        # If no suitable themes found for this category
        logging.info(f"No themes suitable for category '{category}'")
        return False

    def _calculate_theme_frequency(self, theme: Dict, notes: List[Dict]) -> float:
        """
        Calculate how frequently a theme appears across notes

        Args:
            theme (Dict): Theme object with name and examples
            notes (List[Dict]): List of note dictionaries

        Returns:
            float: Frequency score between 0 and 1
        """
        theme_name = theme["name"].lower()
        total_notes = len(notes)
        notes_with_theme = 0

        for note in notes:
            content = note.get("content", "").lower()
            if theme_name in content or any(
                ex.lower() in content for ex in theme["examples"]
            ):
                notes_with_theme += 1

        return notes_with_theme / total_notes if total_notes > 0 else 0

    def _find_related_notes(self, theme: Dict, notes: List[Dict]) -> List[str]:
        """
        Find notes that are related to a specific theme

        Args:
            theme (Dict): Theme object with name and examples
            notes (List[Dict]): List of note dictionaries

        Returns:
            List[str]: List of note paths that contain the theme
        """
        theme_name = theme["name"].lower()
        related_notes = []

        for note in notes:
            content = note.get("content", "").lower()
            if theme_name in content or any(
                ex.lower() in content for ex in theme["examples"]
            ):
                related_notes.append(note["path"])

        return related_notes

    def determine_prevalent_category(self, themes: List[Dict]) -> str:
        """
        Determine the most prevalent category based on the themes.

        Args:
            themes (List[Dict]): List of theme objects

        Returns:
            str: The most prevalent category (shitposting, sermonposting, nerdposting)
        """
        if not themes:
            return "nerdposting"  # Default category if no themes are available

        # Define category-specific keywords based on the three principles
        category_keywords = {
            # Friendliness keywords (shitposting)
            "shitposting": [
                "nourishing",
                "supportive",
                "encouraging",
                "comfortable",
                "honest feelings",
                "friend",
                "friendship",
                "neediness",
                "insecurities",
                "abundance",
                "compliments",
                "gracious",
                "host",
                "conversation",
                "social",
                "connection",
                "community",
                "empathy",
                "kindness",
                "generosity",
                "warmth",
                "welcoming",
            ],
            # Ambition keywords (sermonposting)
            "sermonposting": [
                "dream bigger",
                "larger life",
                "ambition",
                "desire",
                "power",
                "prestige",
                "intimate",
                "do more",
                "be more",
                "see more",
                "learn more",
                "know more",
                "imagination",
                "bottleneck",
                "good",
                "create",
                "untethered",
                "dangerous",
                "temper",
                "good taste",
                "sensitivity",
                "tremendous",
                "potential",
                "growth",
                "vision",
                "purpose",
            ],
            # Nerdiness keywords (nerdposting)
            "nerdposting": [
                "taste",
                "curiosity",
                "beautiful",
                "nerds",
                "music",
                "technology",
                "science",
                "movies",
                "books",
                "exploring",
                "interests",
                "joy",
                "gift",
                "liberate",
                "worrying",
                "opinions",
                "rigorous",
                "honest",
                "regard",
                "thoughts",
                "valuing",
                "expertise",
                "knowledge",
                "discovery",
                "analysis",
                "insight",
            ],
        }

        # Count matches for each category
        category_scores = {"shitposting": 0, "sermonposting": 0, "nerdposting": 0}

        for theme in themes:
            theme_text = (
                f"{theme['name']} {' '.join(theme['examples'])} "
                f"{theme.get('significance', '')}"
            ).lower()

            for category, keywords in category_keywords.items():
                for keyword in keywords:
                    if keyword.lower() in theme_text:
                        category_scores[category] += 1

        # Find the category with the highest score
        max_score = 0
        prevalent_category = "nerdposting"  # Default if no matches

        for category, score in category_scores.items():
            if score > max_score:
                max_score = score
                prevalent_category = category

        # If no category had any matches, use a more general approach
        if max_score == 0:
            logging.info("No direct category matches found, using fallback analysis")
            # Analyze themes based on the three principles
            friendliness_score = 0
            ambition_score = 0
            nerdiness_score = 0

            # Friendliness indicators (shitposting)
            friendliness_keywords = (
                [
                    "nourishing",
                    "supportive",
                    "encouraging",
                    "comfortable",
                    "honest feelings",
                    "friend",
                    "friendship",
                    "neediness",
                    "insecurities",
                    "abundance",
                    "compliments",
                    "gracious",
                    "host",
                    "conversation",
                    "social",
                    "connection",
                    "community",
                    "empathy",
                    "kindness",
                    "generosity",
                    "warmth",
                    "welcoming",
                ],
            )
            # Ambition keywords (sermonposting)
            ambition_keywords = [
                "dream bigger",
                "larger life",
                "ambition",
                "desire",
                "power",
                "prestige",
                "intimate",
                "do more",
                "be more",
                "see more",
                "learn more",
                "know more",
                "imagination",
                "bottleneck",
                "good",
                "create",
                "untethered",
                "dangerous",
                "temper",
                "good taste",
                "sensitivity",
                "tremendous",
                "potential",
                "growth",
                "vision",
                "purpose",
            ]
            # Nerdiness keywords (nerdposting)
            nerdiness_keywords = (
                [
                    "taste",
                    "curiosity",
                    "beautiful",
                    "nerds",
                    "music",
                    "technology",
                    "science",
                    "movies",
                    "books",
                    "exploring",
                    "interests",
                    "joy",
                    "gift",
                    "liberate",
                    "worrying",
                    "opinions",
                    "rigorous",
                    "honest",
                    "regard",
                    "thoughts",
                    "valuing",
                    "expertise",
                    "knowledge",
                    "discovery",
                    "analysis",
                    "insight",
                ],
            )

            for theme in themes:
                theme_text = (f"{theme['name']} {' '.join(theme['examples'])} ").lower()

                for keyword in friendliness_keywords:
                    if keyword in theme_text:
                        friendliness_score += 1

                for keyword in ambition_keywords:
                    if keyword in theme_text:
                        ambition_score += 1

                for keyword in nerdiness_keywords:
                    if keyword in theme_text:
                        nerdiness_score += 1

            # Determine category based on highest score
            if (
                friendliness_score > ambition_score
                and friendliness_score > nerdiness_score
            ):
                prevalent_category = "shitposting"
            elif ambition_score > nerdiness_score:
                prevalent_category = "sermonposting"
            else:
                prevalent_category = "nerdposting"

        logging.info(
            f"Determined prevalent category: {prevalent_category} with score {max_score}"
        )
        return prevalent_category
