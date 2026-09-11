"""AI API integrations for OpenAI and Anthropic."""

import json
import os
import re
from typing import Any, Dict, Optional

import anthropic
from loguru import logger
from openai import OpenAI, OpenAIError


def _parse_json_response(response_content: str) -> Optional[Dict[str, Any]]:
    """Parse JSON from AI response, handling various formats."""
    cleaned_content = response_content

    # Remove markdown code block formatting if present
    markdown_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    markdown_match = re.search(markdown_pattern, response_content)
    if markdown_match:
        cleaned_content = markdown_match.group(1)

    # Try standard JSON parsing first - json.loads handles Unicode fine
    try:
        parsed_json = json.loads(cleaned_content)
        return _post_process_json(parsed_json)
    except json.JSONDecodeError:
        pass

    # Clean only control characters, preserve Unicode like em-dashes
    cleaned_content = re.sub(r"[\x00-\x1F\x7F]", "", cleaned_content)
    try:
        parsed_json = json.loads(cleaned_content)
        return _post_process_json(parsed_json)
    except json.JSONDecodeError:
        pass

    # Fix trailing commas (common LLM mistake) and retry
    fixed_content = re.sub(r",\s*}", "}", cleaned_content)
    fixed_content = re.sub(r",\s*\]", "]", fixed_content)
    try:
        parsed_json = json.loads(fixed_content)
        return _post_process_json(parsed_json)
    except json.JSONDecodeError:
        pass

    # Try to extract just the JSON object (handles extra text after closing brace)
    # Find the first { and match to its closing }
    start_idx = cleaned_content.find("{")
    if start_idx != -1:
        brace_count = 0
        for i, char in enumerate(cleaned_content[start_idx:], start_idx):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_str = cleaned_content[start_idx : i + 1]
                    try:
                        parsed_json = json.loads(json_str)
                        return _post_process_json(parsed_json)
                    except json.JSONDecodeError:
                        break

    logger.error("JSON parsing failed after all attempts")
    logger.error(f"Response content: {response_content[:500]}")
    raise json.JSONDecodeError(
        "Failed to parse response after multiple attempts",
        cleaned_content,
        0,
    )


def _post_process_json(parsed_json: Any) -> Any:
    """Post-process JSON to fix line breaks in text fields."""
    if isinstance(parsed_json, dict):
        for key, value in parsed_json.items():
            if isinstance(value, str):
                value = value.replace("\\n", "\n")
                paragraphs = [p.strip() for p in value.split("\n\n")]
                parsed_json[key] = "\n\n".join(p for p in paragraphs if p)
    return parsed_json


class AIService:
    """AI service wrapper for OpenAI API calls."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize OpenAI client."""
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o"

    def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> Optional[Dict[str, Any]]:
        """Make a chat completion request to OpenAI."""
        if not system_prompt or not system_prompt.strip():
            raise ValueError("System prompt must be non-empty string")
        if not user_message or not user_message.strip():
            raise ValueError("User message must be non-empty string")
        if not (0.0 <= temperature <= 2.0):
            raise ValueError("Temperature must be between 0.0 and 2.0")

        try:
            system_prompt = (
                system_prompt.strip()
                + "\n\nIMPORTANT: Your response MUST be a valid JSON object."
            )

            response = self.client.chat.completions.create(
                model=model or self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
            )

            response_content = response.choices[0].message.content
            if not response_content:
                logger.error("OpenAI returned empty response content")
                return None
            logger.debug(f"Raw OpenAI response: {response_content[:200]}...")

            return _parse_json_response(response_content)

        except OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            return None


class AnthropicService:
    """AI service wrapper for Anthropic Claude API calls."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Anthropic client."""
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        # Fallback for callers that pass no model. Keep this on a live model:
        # claude-sonnet-4-20250514 reached end-of-life and now returns 404.
        self.model = "claude-sonnet-4-6"

    def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Optional[Dict[str, Any]]:
        """Make a chat completion request to Anthropic Claude."""
        if not system_prompt or not system_prompt.strip():
            raise ValueError("System prompt must be non-empty string")
        if not user_message or not user_message.strip():
            raise ValueError("User message must be non-empty string")
        if not (0.0 <= temperature <= 1.0):
            raise ValueError("Temperature must be between 0.0 and 1.0")

        try:
            system_prompt = (
                system_prompt.strip()
                + "\n\nIMPORTANT: Your response MUST be a valid JSON object."
            )

            request = {
                "model": model or self.model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
                # anthropic 1.x removed `temperature` from messages.create (a
                # TypeError), so it rides in the raw body for models that take it.
                "extra_body": {"temperature": temperature},
            }
            try:
                response = self.client.messages.create(**request)
            except anthropic.APIError as exc:
                # Newer models reject `temperature` outright. Retry without it
                # rather than pinning a model allowlist that goes stale.
                if "temperature" not in str(exc):
                    raise
                logger.debug(
                    f"Model {request['model']} rejects temperature; retrying without it"
                )
                request.pop("extra_body", None)
                response = self.client.messages.create(**request)

            if not response.content:
                logger.error("Anthropic returned empty response content")
                return None
            response_content = response.content[0].text
            logger.debug(f"Raw Anthropic response: {response_content[:200]}...")

            return _parse_json_response(response_content)

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Anthropic response as JSON: {e}")
            return None
