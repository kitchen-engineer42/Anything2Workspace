"""Base extractor abstract class."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import structlog

from chunks2skus.schemas.sku import SKUType

logger = structlog.get_logger(__name__)


class BaseExtractor(ABC):
    """Abstract base class for knowledge extraction strategies."""

    extractor_name: str = "base"
    sku_type: SKUType = SKUType.FACTUAL

    def __init__(self, output_dir: Path):
        """
        Initialize the extractor.

        Args:
            output_dir: Base directory for SKU output
        """
        self.output_dir = output_dir
        self.type_dir = output_dir / self.sku_type.value
        self.type_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def extract(
        self,
        content: str,
        chunk_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Extract knowledge from content.

        Args:
            content: Chunk content to process
            chunk_id: Identifier of the source chunk
            context: Optional context from previous extractors

        Returns:
            List of extracted SKU info dicts
        """
        pass

    def get_context_for_next(self) -> dict[str, Any]:
        """
        Get context to pass to the next extractor.

        Override in subclasses that provide context.

        Returns:
            Dict of context data
        """
        return {}
