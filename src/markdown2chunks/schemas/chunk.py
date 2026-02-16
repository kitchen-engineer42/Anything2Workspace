"""Chunk and metadata schemas."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ChunkMetadata(BaseModel):
    """Metadata for a single chunk."""

    title: str = Field(description="Section title or LLM-generated summary")
    chunk_index: int = Field(description="Position in sequence (0-indexed)")
    total_chunks: int = Field(description="Total chunks from source file")
    character_count: int = Field(description="Number of characters in chunk")
    estimated_tokens: int = Field(description="Estimated token count")
    source_file: str = Field(description="Original filename")
    source_path: str = Field(description="Full path to source file")
    header_level: int | None = Field(default=None, description="H1=1, H2=2, etc.")
    chunking_method: Literal["header", "llm", "single"] = Field(
        description="Method used: header-based, LLM-based, or single chunk"
    )


class Chunk(BaseModel):
    """A single chunk with content and metadata."""

    content: str = Field(description="The actual chunk content")
    metadata: ChunkMetadata = Field(description="Chunk metadata")

    def to_markdown_with_frontmatter(self) -> str:
        """Generate markdown content with YAML frontmatter."""
        frontmatter = f"""---
title: "{self.metadata.title}"
source: "{self.metadata.source_file}"
chunk: {self.metadata.chunk_index + 1}
total: {self.metadata.total_chunks}
tokens: {self.metadata.estimated_tokens}
method: "{self.metadata.chunking_method}"
---

"""
        return frontmatter + self.content
