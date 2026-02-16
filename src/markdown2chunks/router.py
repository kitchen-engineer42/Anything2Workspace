"""Router for determining how to handle each file type."""

from pathlib import Path

import structlog

from .chunkers import HeaderChunker, LLMChunker
from .chunkers.base import BaseChunker

logger = structlog.get_logger(__name__)


class Router:
    """
    Routes files to appropriate handling:
    - Markdown files -> chunkers
    - JSON files -> pass-through (no chunking)
    """

    def __init__(self):
        self.header_chunker = HeaderChunker()
        self.llm_chunker = LLMChunker()

    def should_chunk(self, file_path: Path) -> bool:
        """
        Determine if a file should be chunked.

        Args:
            file_path: Path to the file

        Returns:
            True if file should be chunked, False for pass-through
        """
        extension = file_path.suffix.lower()

        if extension == ".md":
            return True
        elif extension == ".json":
            logger.debug("JSON file, pass-through", file=file_path.name)
            return False
        else:
            logger.warning("Unknown file type", file=file_path.name, extension=extension)
            return False

    def get_chunker(self, content: str) -> BaseChunker:
        """
        Get the appropriate chunker for content.

        Args:
            content: File content to analyze

        Returns:
            Appropriate chunker instance
        """
        # Try header chunker first (preferred for structured markdown)
        if self.header_chunker.can_handle(content):
            logger.debug("Using header chunker")
            return self.header_chunker

        # Fallback to LLM chunker
        logger.debug("Using LLM chunker (no headers found)")
        return self.llm_chunker

    def needs_rechunking(self, content: str, max_tokens: int) -> bool:
        """
        Check if content exceeds token limit and needs chunking.

        Args:
            content: Content to check
            max_tokens: Maximum token limit

        Returns:
            True if content exceeds limit
        """
        from .utils.token_estimator import estimate_tokens

        tokens = estimate_tokens(content)
        return tokens > max_tokens
