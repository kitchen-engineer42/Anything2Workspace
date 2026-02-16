"""Base postprocessor abstract class."""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import structlog

from chunks2skus.config import settings
from chunks2skus.schemas.index import SKUsIndex

logger = structlog.get_logger(__name__)


class BasePostprocessor(ABC):
    """Abstract base class for postprocessing steps."""

    step_name: str = "base"

    def __init__(self, skus_dir: Path | None = None):
        """
        Initialize the postprocessor.

        Args:
            skus_dir: SKUs output directory (default: settings.skus_output_dir)
        """
        self.skus_dir = skus_dir or settings.skus_output_dir
        self.postprocessing_dir = self.skus_dir / "postprocessing"
        self.postprocessing_dir.mkdir(parents=True, exist_ok=True)

    def load_index(self) -> SKUsIndex:
        """Load the SKUs index from disk."""
        index_path = self.skus_dir / "skus_index.json"
        if not index_path.exists():
            raise FileNotFoundError(f"SKUs index not found: {index_path}")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return SKUsIndex.model_validate(data)

    def save_index(self, index: SKUsIndex) -> None:
        """Save the SKUs index to disk."""
        index_path = self.skus_dir / "skus_index.json"
        index_path.write_text(index.model_dump_json(indent=2), encoding="utf-8")

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the postprocessing step."""
        pass
