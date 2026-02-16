"""Index schema for tracking all SKUs."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from chunks2skus.schemas.sku import SKUType


class SKUEntry(BaseModel):
    """Entry in the SKUs index."""

    sku_id: str = Field(..., description="Unique SKU identifier")
    name: str = Field(..., description="SKU name")
    classification: SKUType = Field(..., description="Type of knowledge")
    path: str = Field(..., description="Path to SKU folder or file")
    source_chunk: str = Field(..., description="Source chunk ID")
    character_count: int = Field(default=0, description="Content size")
    description: str = Field(default="", description="One-line description")
    confidence: Optional[float] = Field(
        default=None, description="Proofreading confidence score (0.0-1.0)"
    )


class SKUsIndex(BaseModel):
    """Master index of all extracted SKUs."""

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    total_skus: int = Field(default=0)
    total_characters: int = Field(default=0)
    chunks_processed: list[str] = Field(default_factory=list)
    skus: list[SKUEntry] = Field(default_factory=list)

    # Counters by type
    factual_count: int = Field(default=0)
    relational_count: int = Field(default=0)
    procedural_count: int = Field(default=0)
    meta_count: int = Field(default=0)

    def add_sku(self, entry: SKUEntry) -> None:
        """Add an SKU entry and update statistics."""
        self.skus.append(entry)
        self.total_skus = len(self.skus)
        self.total_characters += entry.character_count
        self.updated_at = datetime.now()

        # Update type counter
        if entry.classification == SKUType.FACTUAL:
            self.factual_count += 1
        elif entry.classification == SKUType.RELATIONAL:
            self.relational_count += 1
        elif entry.classification == SKUType.PROCEDURAL:
            self.procedural_count += 1
        elif entry.classification == SKUType.META:
            self.meta_count += 1

    def mark_chunk_processed(self, chunk_id: str) -> None:
        """Mark a chunk as processed."""
        if chunk_id not in self.chunks_processed:
            self.chunks_processed.append(chunk_id)
            self.updated_at = datetime.now()

    def is_chunk_processed(self, chunk_id: str) -> bool:
        """Check if a chunk has been processed."""
        return chunk_id in self.chunks_processed

    def get_skus_by_type(self, sku_type: SKUType) -> list[SKUEntry]:
        """Get all SKUs of a specific type."""
        return [s for s in self.skus if s.classification == sku_type]

    def get_skus_by_source(self, source_chunk: str) -> list[SKUEntry]:
        """Get all SKUs from a specific source chunk."""
        return [s for s in self.skus if s.source_chunk == source_chunk]

    def remove_sku(self, sku_id: str) -> bool:
        """
        Remove an SKU entry by ID and update statistics.

        Returns:
            True if removed, False if not found.
        """
        for i, entry in enumerate(self.skus):
            if entry.sku_id == sku_id:
                removed = self.skus.pop(i)
                self.total_skus = len(self.skus)
                self.total_characters -= removed.character_count

                if removed.classification == SKUType.FACTUAL:
                    self.factual_count -= 1
                elif removed.classification == SKUType.RELATIONAL:
                    self.relational_count -= 1
                elif removed.classification == SKUType.PROCEDURAL:
                    self.procedural_count -= 1
                elif removed.classification == SKUType.META:
                    self.meta_count -= 1

                self.updated_at = datetime.now()
                return True
        return False

    def summary(self) -> str:
        """Get a text summary of the index."""
        return f"""SKUs Index Summary
==================
Total SKUs: {self.total_skus}
Total Characters: {self.total_characters:,}
Chunks Processed: {len(self.chunks_processed)}

By Type:
  - Factual: {self.factual_count}
  - Relational: {self.relational_count}
  - Procedural: {self.procedural_count}
  - Meta: {self.meta_count}

Last Updated: {self.updated_at.isoformat()}
"""
