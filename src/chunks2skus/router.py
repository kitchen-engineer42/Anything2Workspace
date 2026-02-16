"""Router for loading chunks and routing to extractors."""

import json
from pathlib import Path
from typing import Any

import structlog

from chunks2skus.config import settings
from chunks2skus.extractors import (
    FactualExtractor,
    MetaExtractor,
    ProceduralExtractor,
    RelationalExtractor,
)
from chunks2skus.extractors.base import BaseExtractor

logger = structlog.get_logger(__name__)


class ChunkInfo:
    """Information about a chunk to be processed."""

    def __init__(
        self,
        chunk_id: str,
        file_path: Path,
        title: str,
        estimated_tokens: int,
        source_file: str,
    ):
        self.chunk_id = chunk_id
        self.file_path = file_path
        self.title = title
        self.estimated_tokens = estimated_tokens
        self.source_file = source_file
        self._content: str | None = None

    @property
    def content(self) -> str:
        """Lazy load chunk content."""
        if self._content is None:
            self._content = self.file_path.read_text(encoding="utf-8")
            # Remove YAML frontmatter if present
            if self._content.startswith("---"):
                parts = self._content.split("---", 2)
                if len(parts) >= 3:
                    self._content = parts[2].strip()
        return self._content


class Router:
    """
    Routes chunks to extractors in sequence.

    Processing order: Factual -> Relational -> Procedural -> Meta
    - Factual & Procedural: Isolated processing
    - Relational & Meta: Read-and-update with context
    """

    def __init__(self, output_dir: Path | None = None):
        """
        Initialize router with extractors.

        Args:
            output_dir: Output directory for SKUs (default: settings.skus_output_dir)
        """
        self.output_dir = output_dir or settings.skus_output_dir

        # Initialize extractors
        self.factual_extractor = FactualExtractor(self.output_dir)
        self.relational_extractor = RelationalExtractor(self.output_dir)
        self.procedural_extractor = ProceduralExtractor(self.output_dir)
        self.meta_extractor = MetaExtractor(self.output_dir)

        # Extraction sequence
        self.extractors: list[BaseExtractor] = [
            self.factual_extractor,
            self.relational_extractor,
            self.procedural_extractor,
            self.meta_extractor,
        ]

    def load_chunks(self, chunks_dir: Path | None = None) -> list[ChunkInfo]:
        """
        Load chunk information from chunks_index.json.

        Args:
            chunks_dir: Directory containing chunks (default: settings.chunks_dir)

        Returns:
            List of ChunkInfo objects sorted by chunk_id
        """
        chunks_dir = chunks_dir or settings.chunks_dir
        index_path = chunks_dir / "chunks_index.json"

        if not index_path.exists():
            logger.error("chunks_index.json not found", path=str(index_path))
            return []

        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            chunks = []

            for entry in data.get("chunks", []):
                chunk_info = ChunkInfo(
                    chunk_id=entry["chunk_id"],
                    file_path=Path(entry["file_path"]),
                    title=entry.get("title", ""),
                    estimated_tokens=entry.get("estimated_tokens", 0),
                    source_file=entry.get("source_file", ""),
                )
                chunks.append(chunk_info)

            # Sort by chunk_id to process in order
            chunks.sort(key=lambda c: c.chunk_id)

            logger.info("Loaded chunks", count=len(chunks))
            return chunks

        except Exception as e:
            logger.error("Failed to load chunks index", error=str(e))
            return []

    def process_chunk(
        self,
        chunk: ChunkInfo,
        accumulated_skus: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Process a single chunk through all extractors.

        Args:
            chunk: Chunk to process
            accumulated_skus: All SKUs created so far (for meta extractor)

        Returns:
            List of new SKUs created from this chunk
        """
        logger.info(
            "Processing chunk",
            chunk_id=chunk.chunk_id,
            title=chunk.title,
            tokens=chunk.estimated_tokens,
        )

        content = chunk.content
        chunk_id = chunk.chunk_id
        new_skus = []
        context: dict[str, Any] = {}

        # Process through each extractor in sequence
        for extractor in self.extractors:
            try:
                # Build context for this extractor
                extractor_context = context.copy()

                # Meta extractor needs all SKUs
                if extractor.extractor_name == "meta":
                    extractor_context["all_skus"] = accumulated_skus + new_skus

                # Extract knowledge
                skus = extractor.extract(content, chunk_id, extractor_context)
                new_skus.extend(skus)

                # Get context for next extractor
                next_context = extractor.get_context_for_next()
                context.update(next_context)

            except Exception as e:
                logger.error(
                    "Extractor failed",
                    extractor=extractor.extractor_name,
                    chunk_id=chunk_id,
                    error=str(e),
                )

        return new_skus

    def load_single_chunk(self, chunk_path: Path) -> ChunkInfo | None:
        """
        Load a single chunk file.

        Args:
            chunk_path: Path to chunk file

        Returns:
            ChunkInfo or None if failed
        """
        if not chunk_path.exists():
            logger.error("Chunk file not found", path=str(chunk_path))
            return None

        return ChunkInfo(
            chunk_id=chunk_path.stem,
            file_path=chunk_path,
            title=chunk_path.stem,
            estimated_tokens=0,
            source_file=chunk_path.name,
        )
