"""Jina web search client for proofreading verification."""

import time
from typing import Optional

import httpx
import structlog

from chunks2skus.config import settings

logger = structlog.get_logger(__name__)

# Rate limiting state
_last_request_time: float = 0.0
_MIN_INTERVAL: float = 0.6  # ~100 RPM


def search_web(query: str, num_results: int = 5) -> Optional[list[dict]]:
    """
    Search the web using Jina s.jina.ai.

    Args:
        query: Search query string
        num_results: Number of results to return (default: 5)

    Returns:
        List of result dicts with 'title', 'url', 'snippet', or None on failure.
    """
    global _last_request_time

    if not settings.jina_api_key:
        logger.warning("Jina API key not configured")
        return None

    # Rate limiting
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)

    url = f"https://s.jina.ai/{query}"
    headers = {
        "Authorization": f"Bearer {settings.jina_api_key}",
        "Accept": "application/json",
        "X-Retain-Images": "none",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            _last_request_time = time.time()
            response.raise_for_status()

        data = response.json()
        results = []
        items = data.get("data", [])[:num_results]
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", item.get("description", ""))[:1000],
            })

        logger.debug("Jina search completed", query=query[:50], results=len(results))
        return results

    except Exception as e:
        logger.error("Jina search failed", query=query[:50], error=str(e))
        return None
