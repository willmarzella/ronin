"""OpenAI API integration."""

from typing import Optional

import openai
from loguru import logger


class OpenAIClient:
    """Generic wrapper for OpenAI API calls."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize OpenAI client with optional API key."""
        if api_key:
            openai.api_key = api_key

        if not openai.api_key:
            raise ValueError("OpenAI API key not set")

    def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "gpt-4-turbo",
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> Optional[str]:
        """
        Make a chat completion request to OpenAI.

        Args:
            system_prompt: The system prompt to use
            user_message: The user message to send
            model: The model to use (default: gpt-4)
            temperature: Temperature setting (default: 0.7)
            max_tokens: Maximum tokens to generate (default: 1000)

        Returns:
            The response content or None if the request fails
        """
        try:
            response = openai.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Error making OpenAI request: {str(e)}")
            return None
