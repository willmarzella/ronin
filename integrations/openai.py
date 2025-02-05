"""OpenAI API integration."""

import os
import logging
from typing import Optional, Dict, Any
from openai import OpenAI


class OpenAIClient:
    """Generic wrapper for OpenAI API calls."""

    def __init__(self):
        """Initialize OpenAI client."""
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4-turbo-preview"  # Using the latest model for best results

    def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> Optional[Dict[str, Any]]:
        """
        Make a chat completion request to OpenAI.

        Args:
            system_prompt: The system prompt to use
            user_message: The user message to send
            model: The model to use (default: gpt-4-turbo-preview)
            temperature: Temperature setting (default: 0.7)
            max_tokens: Maximum tokens to generate (default: 1000)

        Returns:
            The complete response object or None if the request fails
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            return response.choices[0].message.dict()

        except Exception as e:
            logging.error(f"OpenAI API error: {str(e)}")
            return None
