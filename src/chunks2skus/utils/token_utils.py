"""Token estimation utilities using tiktoken."""

import tiktoken

# Cache the encoding instance
_encoding: tiktoken.Encoding | None = None


def _get_encoding() -> tiktoken.Encoding:
    """Get or create the cl100k_base encoding."""
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a text string.

    Args:
        text: Input text

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return len(_get_encoding().encode(text))
