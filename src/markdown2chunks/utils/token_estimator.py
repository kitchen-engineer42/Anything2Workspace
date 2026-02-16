"""Token estimation using tiktoken."""

import tiktoken
import structlog

from ..config import settings

logger = structlog.get_logger(__name__)

# Use cl100k_base encoding (used by GPT-4, Claude-compatible)
_encoder = None


def _get_encoder() -> tiktoken.Encoding:
    """Get or create the tiktoken encoder (lazy loading)."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in a text string.

    Args:
        text: Input text to tokenize

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    encoder = _get_encoder()
    return len(encoder.encode(text))


def get_token_limit() -> int:
    """Get the configured maximum token length."""
    return settings.max_token_length


def text_to_tokens(text: str) -> list[int]:
    """
    Convert text to token IDs.

    Args:
        text: Input text

    Returns:
        List of token IDs
    """
    encoder = _get_encoder()
    return encoder.encode(text)


def tokens_to_text(tokens: list[int]) -> str:
    """
    Convert token IDs back to text.

    Args:
        tokens: List of token IDs

    Returns:
        Decoded text
    """
    encoder = _get_encoder()
    return encoder.decode(tokens)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """
    Truncate text to a maximum number of tokens.

    Args:
        text: Input text
        max_tokens: Maximum tokens to keep

    Returns:
        Truncated text
    """
    encoder = _get_encoder()
    tokens = encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return encoder.decode(tokens[:max_tokens])


def get_text_window(text: str, start_token: int, window_tokens: int) -> tuple[str, int]:
    """
    Get a window of text by token positions.

    Args:
        text: Full text
        start_token: Starting token position
        window_tokens: Number of tokens in window

    Returns:
        Tuple of (window text, actual token count)
    """
    encoder = _get_encoder()
    tokens = encoder.encode(text)

    end_token = min(start_token + window_tokens, len(tokens))
    window = tokens[start_token:end_token]

    return encoder.decode(window), len(window)
