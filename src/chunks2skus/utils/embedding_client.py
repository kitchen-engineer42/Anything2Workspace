"""Embedding client for SiliconFlow bge-m3 API."""

from typing import Optional

import structlog
from openai import OpenAI

from chunks2skus.config import settings

logger = structlog.get_logger(__name__)

# Module-level client (lazy initialized)
_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    """Get or create the OpenAI client for embeddings."""
    global _client
    if _client is None:
        if not settings.siliconflow_api_key:
            logger.warning("SiliconFlow API key not configured for embeddings")
            return None
        _client = OpenAI(
            api_key=settings.siliconflow_api_key,
            base_url=settings.siliconflow_base_url,
        )
    return _client


_MAX_BATCH_SIZE = 64


def get_embeddings(texts: list[str], model: Optional[str] = None) -> Optional[list[list[float]]]:
    """
    Get embeddings for a list of texts via SiliconFlow API.

    Automatically batches requests to stay within API batch size limits.

    Args:
        texts: List of text strings to embed
        model: Embedding model (default: settings.embedding_model)

    Returns:
        List of embedding vectors, or None on failure.
    """
    if not texts:
        return []

    client = _get_client()
    if client is None:
        return None

    model = model or settings.embedding_model
    all_embeddings: list[list[float]] = []

    try:
        for i in range(0, len(texts), _MAX_BATCH_SIZE):
            batch = texts[i : i + _MAX_BATCH_SIZE]
            response = client.embeddings.create(
                model=model,
                input=batch,
            )
            all_embeddings.extend(item.embedding for item in response.data)
            logger.debug(
                "Embeddings batch retrieved",
                batch=f"{i // _MAX_BATCH_SIZE + 1}/{(len(texts) - 1) // _MAX_BATCH_SIZE + 1}",
                count=len(batch),
                model=model,
            )

        return all_embeddings

    except Exception as e:
        logger.error("Embedding API call failed", model=model, error=str(e))
        return None
