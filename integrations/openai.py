"""OpenAI API integration."""

import os
import logging
from typing import Optional, Dict, Any
from openai import OpenAI
import json


class OpenAIClient:
    """Generic wrapper for OpenAI API calls."""

    def __init__(self):
        """Initialize OpenAI client."""
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o-mini"  # Using the latest model for best results

    def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
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
            # Add explicit instructions about JSON format
            system_prompt = (
                system_prompt.strip()
                + "\n\nIMPORTANT: Your response MUST be a valid JSON object. Do not include any explanatory text outside the JSON structure."
            )

            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )

            # Get the response content
            response_content = response.choices[0].message.content

            # Log the raw response for debugging
            logging.debug(f"Raw OpenAI response: {response_content}")

            # If the response is already a dict, return it
            if isinstance(response_content, dict):
                return response_content

            # Try to parse the response as JSON if it's a string
            try:
                # Remove any leading/trailing whitespace and ensure we have valid JSON
                cleaned_content = response_content.strip()
                if not cleaned_content.startswith("{"):
                    logging.error(f"Invalid JSON response format: {cleaned_content}")
                    return None

                parsed_response = json.loads(cleaned_content)
                logging.debug(f"Parsed JSON response: {parsed_response}")
                return parsed_response

            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse OpenAI response as JSON: {str(e)}")
                logging.error(f"Response content: {response_content}")

                # Try to fix common JSON formatting issues
                try:
                    # Remove any markdown formatting that might have been added
                    cleaned_content = response_content.replace("```json", "").replace(
                        "```", ""
                    )
                    # Remove any explanatory text before or after the JSON
                    json_start = cleaned_content.find("{")
                    json_end = cleaned_content.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_content = cleaned_content[json_start:json_end]
                        return json.loads(json_content)
                except Exception as e2:
                    logging.error(f"Failed to fix JSON formatting: {str(e2)}")
                return None

        except Exception as e:
            logging.error(f"OpenAI API error: {str(e)}")
            return None