"""Base chunker abstract class."""

from abc import ABC, abstractmethod
from pathlib import Path

import structlog

from ..schemas.chunk import Chunk

logger = structlog.get_logger(__name__)


class BaseChunker(ABC):
    """Abstract base class for chunking strategies."""

    chunker_name: str = "base"

    @abstractmethod
    def chunk(self, content: str, source_path: Path) -> list[Chunk]:
        """
        Split content into chunks.

        Args:
            content: Full text content to chunk
            source_path: Path to the source file

        Returns:
            List of Chunk objects
        """
        pass

    @abstractmethod
    def can_handle(self, content: str) -> bool:
        """
        Check if this chunker can handle the given content.

        Args:
            content: Content to check

        Returns:
            True if this chunker should be used
        """
        pass
