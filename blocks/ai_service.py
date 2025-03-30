"""OpenAI API integration."""

import os
import logging
from typing import Optional, Dict, Any
from openai import OpenAI
import json
import re


class AIService:
    """AI service wrapper for OpenAI API calls."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize OpenAI client."""
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4-turbo-preview"  # Using GPT-4 Turbo model

    def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> Optional[Dict[str, Any]]:
        """
        Make a chat completion request to OpenAI.

        Args:
            system_prompt: The system prompt to use
            user_message: The user message to send
            model: The model to use (default: instance default)
            temperature: Temperature setting (default: 0.7)

        Returns:
            The complete response object or None if the request fails
        """
        try:
            # Add explicit instructions about JSON format
            system_prompt = (
                system_prompt.strip()
                + "\n\nIMPORTANT: Your response MUST be a valid JSON object. For text responses that include line breaks, use actual line breaks in the text, not escaped \\n characters. Format your entire response as a JSON object with no additional text or explanation."
            )

            response = self.client.chat.completions.create(
                model=model or self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
            )

            # Get the response content
            response_content = response.choices[0].message.content

            # Log the raw response for debugging
            logging.debug(f"Raw OpenAI response: {response_content}")

            # Try to parse the response as JSON
            try:
                # Clean the response content if it's wrapped in markdown code blocks
                cleaned_content = response_content

                # Remove markdown code block formatting if present
                markdown_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
                markdown_match = re.search(markdown_pattern, response_content)
                if markdown_match:
                    cleaned_content = markdown_match.group(1)

                # First try standard JSON parsing
                try:
                    parsed_json = json.loads(cleaned_content)
                except json.JSONDecodeError:
                    # If that fails, try with more lenient parsing
                    # Replace common problematic characters
                    cleaned_content = re.sub(r"[\x00-\x1F\x7F]", "", cleaned_content)

                    # Try again with the cleaned content
                    try:
                        parsed_json = json.loads(cleaned_content)
                    except json.JSONDecodeError:
                        # Last resort: use a more permissive approach
                        import ast

                        # Convert JSON-like string to Python dict, then back to JSON
                        try:
                            # Replace single quotes with double quotes for proper JSON
                            fixed_content = cleaned_content.replace("'", '"')
                            # Use ast.literal_eval as a safer alternative to eval
                            parsed_dict = ast.literal_eval(fixed_content)
                            # Convert back to proper JSON
                            parsed_json = json.loads(json.dumps(parsed_dict))
                        except (SyntaxError, ValueError) as e:
                            logging.error(f"All parsing attempts failed: {str(e)}")
                            raise json.JSONDecodeError(
                                f"Failed to parse response after multiple attempts",
                                cleaned_content,
                                0,
                            )

                # Post-process any text fields to ensure proper line breaks
                if isinstance(parsed_json, dict):
                    for key, value in parsed_json.items():
                        if isinstance(value, str):
                            # Replace escaped newlines with actual newlines
                            value = value.replace("\\n", "\n")
                            # Ensure paragraphs are properly separated
                            paragraphs = [p.strip() for p in value.split("\n\n")]
                            # Remove empty paragraphs and join with double newlines
                            parsed_json[key] = "\n\n".join(p for p in paragraphs if p)

                return parsed_json

            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse OpenAI response as JSON: {str(e)}")
                logging.error(f"Response content: {response_content}")
                return None

        except Exception as e:
            logging.error(f"OpenAI API error: {str(e)}")
            return None

    def generate_blog_post(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> Optional[Dict[str, Any]]:
        """
        Specialized method for generating blog posts with proper handling of content formatting.

        Args:
            system_prompt: The system prompt to use
            user_message: The user message to send
            model: The model to use (default: instance default)
            temperature: Temperature setting (default: 0.7)

        Returns:
            The blog post content as a dictionary or None if the request fails
        """
        try:
            # Add explicit instructions about content formatting
            system_prompt = (
                system_prompt.strip()
                + "\n\nIMPORTANT: Your response MUST be a valid JSON object. For text content that includes line breaks, use actual line breaks in the text, not escaped \\n characters. Do not use markdown formatting in the JSON itself."
            )

            response = self.client.chat.completions.create(
                model=model or self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                response_format={
                    "type": "json_object"
                },  # Explicitly request JSON format
            )

            # Get the response content
            response_content = response.choices[0].message.content

            # Log the raw response for debugging
            logging.debug(f"Raw OpenAI blog post response: {response_content}")

            # Try to parse the response as JSON with special handling for blog content
            try:
                # Clean the response content if it's wrapped in markdown code blocks
                cleaned_content = response_content

                # Remove markdown code block formatting if present
                markdown_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
                markdown_match = re.search(markdown_pattern, response_content)
                if markdown_match:
                    cleaned_content = markdown_match.group(1)

                # Parse the JSON with careful handling
                try:
                    parsed_json = json.loads(cleaned_content)
                except json.JSONDecodeError:
                    # If standard parsing fails, try a more robust approach
                    import json5  # More lenient JSON parser, install with: pip install json5

                    try:
                        parsed_json = json5.loads(cleaned_content)
                    except:
                        # Last resort: manual cleaning
                        cleaned_content = re.sub(
                            r"[\x00-\x1F\x7F]", "", cleaned_content
                        )
                        parsed_json = json.loads(cleaned_content)

                # Post-process any text fields to ensure proper line breaks
                if isinstance(parsed_json, dict):
                    for key, value in parsed_json.items():
                        if isinstance(value, str):
                            # Replace escaped newlines with actual newlines
                            value = value.replace("\\n", "\n")
                            # Ensure paragraphs are properly separated
                            paragraphs = [p.strip() for p in value.split("\n\n")]
                            # Remove empty paragraphs and join with double newlines
                            parsed_json[key] = "\n\n".join(p for p in paragraphs if p)

                return parsed_json

            except Exception as e:
                logging.error(f"Failed to parse blog post response: {str(e)}")
                logging.error(f"Response content: {response_content}")
                return None

        except Exception as e:
            logging.error(f"OpenAI API error in blog post generation: {str(e)}")
            return None
