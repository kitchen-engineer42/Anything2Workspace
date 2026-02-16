"""Main orchestration pipeline for knowledge extraction."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from chunks2skus.config import settings
from chunks2skus.router import Router
from chunks2skus.schemas.index import SKUEntry, SKUsIndex
from chunks2skus.schemas.sku import SKUType

logger = structlog.get_logger(__name__)


class ExtractionPipeline:
    """
    Main pipeline for extracting knowledge from chunks.

    Input: Module 2 output (chunks/ directory with chunks_index.json)
    Output: SKUs in output/skus/ with skus_index.json
    """

    def __init__(
        self,
        chunks_dir: Path | None = None,
        output_dir: Path | None = None,
    ):
        """
        Initialize the extraction pipeline.

        Args:
            chunks_dir: Directory with chunks (default: settings.chunks_dir)
            output_dir: Directory for SKU output (default: settings.skus_output_dir)
        """
        self.chunks_dir = chunks_dir or settings.chunks_dir
        self.output_dir = output_dir or settings.skus_output_dir

        self.router = Router(self.output_dir)
        self.index = self._load_or_create_index()

    def _load_or_create_index(self) -> SKUsIndex:
        """Load existing index or create new one."""
        index_path = self.output_dir / "skus_index.json"
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
                return SKUsIndex.model_validate(data)
            except Exception as e:
                logger.warning("Failed to load existing index", error=str(e))
        return SKUsIndex()

    def run(self) -> SKUsIndex:
        """
        Run the full extraction pipeline.

        Returns:
            SKUsIndex with all SKU information
        """
        start_time = datetime.now()
        logger.info(
            "Starting extraction pipeline",
            chunks_dir=str(self.chunks_dir),
            output_dir=str(self.output_dir),
        )

        # Create output directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        settings.factual_dir.mkdir(parents=True, exist_ok=True)
        settings.relational_dir.mkdir(parents=True, exist_ok=True)
        settings.procedural_dir.mkdir(parents=True, exist_ok=True)
        settings.meta_dir.mkdir(parents=True, exist_ok=True)

        # Load chunks
        chunks = self.router.load_chunks(self.chunks_dir)
        if not chunks:
            logger.warning("No chunks found to process")
            return self.index

        logger.info("Processing chunks", total=len(chunks))

        # Track all accumulated SKUs
        all_skus: list[dict[str, Any]] = []

        # Process each chunk sequentially
        for i, chunk in enumerate(chunks):
            # Skip already processed chunks
            if self.index.is_chunk_processed(chunk.chunk_id):
                logger.debug("Skipping processed chunk", chunk_id=chunk.chunk_id)
                continue

            logger.info(
                "Processing chunk",
                progress=f"{i + 1}/{len(chunks)}",
                chunk_id=chunk.chunk_id,
            )

            try:
                # Process through all extractors
                new_skus = self.router.process_chunk(chunk, all_skus)

                # Add to index
                for sku in new_skus:
                    self._add_sku_to_index(sku)

                all_skus.extend(new_skus)

                # Mark chunk as processed
                self.index.mark_chunk_processed(chunk.chunk_id)

                # Save index after each chunk (for recovery)
                self._save_index()

                logger.info(
                    "Chunk processed",
                    chunk_id=chunk.chunk_id,
                    new_skus=len(new_skus),
                    total_skus=self.index.total_skus,
                )

            except Exception as e:
                logger.error(
                    "Failed to process chunk",
                    chunk_id=chunk.chunk_id,
                    error=str(e),
                )

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Extraction pipeline complete",
            total_skus=self.index.total_skus,
            total_characters=self.index.total_characters,
            chunks_processed=len(self.index.chunks_processed),
            duration_seconds=f"{duration:.1f}",
        )

        return self.index

    def _add_sku_to_index(self, sku: dict[str, Any]) -> None:
        """Add an SKU to the index."""
        # Handle classification as string or enum
        classification = sku.get("classification")
        if isinstance(classification, str):
            classification = SKUType(classification)
        elif isinstance(classification, SKUType):
            pass
        else:
            classification = SKUType.FACTUAL

        entry = SKUEntry(
            sku_id=sku.get("sku_id", "unknown"),
            name=sku.get("name", "unknown"),
            classification=classification,
            path=sku.get("path", ""),
            source_chunk=sku.get("source_chunk", ""),
            character_count=sku.get("character_count", 0),
            description=sku.get("description", ""),
        )
        self.index.add_sku(entry)

    def _save_index(self) -> None:
        """Save index to disk."""
        index_path = self.output_dir / "skus_index.json"
        index_path.write_text(
            self.index.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def extract_single_chunk(self, chunk_path: Path) -> list[dict[str, Any]]:
        """
        Extract SKUs from a single chunk file.

        Args:
            chunk_path: Path to chunk file

        Returns:
            List of created SKUs
        """
        chunk = self.router.load_single_chunk(chunk_path)
        if not chunk:
            return []

        # Get existing SKUs for context
        existing_skus = [
            {
                "sku_id": s.sku_id,
                "name": s.name,
                "classification": s.classification.value,
                "path": s.path,
                "description": s.description,
            }
            for s in self.index.skus
        ]

        new_skus = self.router.process_chunk(chunk, existing_skus)

        # Add to index
        for sku in new_skus:
            self._add_sku_to_index(sku)

        self.index.mark_chunk_processed(chunk.chunk_id)
        self._save_index()

        return new_skus

    def show_index_summary(self) -> str:
        """Get a summary of the current index."""
        return self.index.summary()
