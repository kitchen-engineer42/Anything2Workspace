"""LLM client wrapper for SiliconFlow API calls."""

import json
import re
from typing import Any, Optional

import structlog
from openai import OpenAI

from chunks2skus.config import settings

logger = structlog.get_logger(__name__)

# Module-level client (lazy initialized)
_client: Optional[OpenAI] = None

# Default retry count for JSON parse failures
DEFAULT_MAX_RETRIES = 2


def get_llm_client() -> Optional[OpenAI]:
    """
    Get or create the OpenAI client for SiliconFlow.

    Returns:
        OpenAI client, or None if API key not configured.
    """
    global _client

    if _client is None:
        if not settings.siliconflow_api_key:
            logger.warning("SiliconFlow API key not configured")
            return None

        _client = OpenAI(
            api_key=settings.siliconflow_api_key,
            base_url=settings.siliconflow_base_url,
        )

    return _client


def call_llm(
    prompt: str,
    system_prompt: str = "You are a knowledge extraction assistant. Output ONLY valid JSON.",
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4000,
    response_format: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """
    Call the LLM with the given prompt.

    Args:
        prompt: User prompt
        system_prompt: System prompt (default: knowledge extraction context)
        model: Model to use (default: settings.extraction_model)
        temperature: Sampling temperature (default: 0.3)
        max_tokens: Maximum tokens in response (default: 4000)
        response_format: Optional response format dict, e.g. {"type": "json_object"}

    Returns:
        LLM response text, or None on failure.
    """
    client = get_llm_client()
    if client is None:
        return None

    model = model or settings.extraction_model

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if response_format is not None:
        kwargs["response_format"] = response_format

    try:
        response = client.chat.completions.create(**kwargs)

        result = response.choices[0].message.content.strip()
        logger.debug("LLM call successful", model=model, response_length=len(result))
        return result

    except Exception as e:
        logger.error("LLM call failed", model=model, error=str(e))
        return None


def call_llm_json(
    prompt: str,
    system_prompt: str = "You are a knowledge extraction assistant. Output ONLY valid JSON.",
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4000,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Optional[dict[str, Any]]:
    """
    Call LLM and parse JSON response, with structured output and retry on parse failure.

    On first call, requests JSON format. If parsing fails, retries with error feedback
    appended to the prompt so the LLM can self-correct.

    Args:
        prompt: User prompt
        system_prompt: System prompt
        model: Model to use
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
        max_retries: Max retries on parse failure (default: 2)

    Returns:
        Parsed JSON dict, or None if all attempts fail.
    """
    # Try with response_format first
    response = call_llm(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )

    if response:
        parsed = parse_json_response(response)
        if parsed is not None:
            return parsed

        # First parse failed — retry with error feedback
        last_error = response[:300]
        for attempt in range(max_retries):
            retry_prompt = (
                f"{prompt}\n\n"
                f"IMPORTANT: Your previous response was not valid JSON. "
                f"Here is what you returned:\n{last_error}\n\n"
                f"Please output ONLY valid JSON with no extra text, no markdown code blocks."
            )
            response = call_llm(
                prompt=retry_prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=max(0.1, temperature - 0.1),  # Slightly lower temp for retry
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            if response:
                parsed = parse_json_response(response)
                if parsed is not None:
                    logger.info("JSON parse succeeded on retry", attempt=attempt + 1)
                    return parsed
                last_error = response[:300]

        logger.warning("All JSON parse attempts failed", attempts=max_retries + 1)
        return None

    # Fallback: try without response_format (some models may not support it)
    response = call_llm(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response:
        return parse_json_response(response)

    return None


def parse_json_response(text: str) -> Optional[dict[str, Any]]:
    """
    Parse LLM JSON response with fallback for common formatting issues.

    Args:
        text: Raw LLM response text

    Returns:
        Parsed dict, or None on failure.
    """
    if not text:
        return None

    # Remove markdown code blocks if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```) and last line (```)
        if len(lines) > 2:
            cleaned = "\n".join(lines[1:-1])

    # Try standard JSON parsing
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try fixing common issues
    try:
        # Replace single quotes with double quotes (risky but sometimes works)
        fixed = cleaned.replace("'", '"')
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    logger.warning("Failed to parse JSON response", preview=cleaned[:200])
    return None


def extract_json_blocks(text: str) -> list[dict[str, Any]]:
    """
    Extract multiple JSON objects from text that may contain mixed content.

    Useful when LLM outputs multiple JSON blocks or explanatory text.

    Args:
        text: Text potentially containing JSON objects

    Returns:
        List of parsed JSON dicts.
    """
    results = []

    # Pattern to find JSON objects (handles nested braces)
    # This is a simple heuristic - look for { ... } blocks
    depth = 0
    start = -1

    for i, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                block = text[start : i + 1]
                parsed = parse_json_response(block)
                if parsed:
                    results.append(parsed)
                start = -1

    return results


def extract_field_value(text: str, field_name: str) -> Optional[str]:
    """
    Extract a field value from potentially malformed JSON using regex.

    Args:
        text: Text containing JSON-like structure
        field_name: Name of the field to extract

    Returns:
        Field value as string, or None if not found.
    """
    # Pattern: "field_name": "value" or 'field_name': 'value'
    pattern = rf'["\']?{re.escape(field_name)}["\']?\s*:\s*["\'](.+?)["\']'
    match = re.search(pattern, text, re.DOTALL)

    if match:
        value = match.group(1)
        # Unescape common escapes
        value = value.replace('\\"', '"').replace("\\'", "'").replace("\\n", "\n")
        return value

    return None
