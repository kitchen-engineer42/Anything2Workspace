"""Chunks index schema for tracking all chunks."""

from datetime import datetime

from pydantic import BaseModel, Field


class ChunkEntry(BaseModel):
    """Entry for a single chunk in the index."""

    chunk_id: str = Field(description="Unique chunk identifier")
    file_path: str = Field(description="Path to chunk file")
    title: str = Field(description="Chunk title")
    estimated_tokens: int = Field(description="Token count")
    source_file: str = Field(description="Original source filename")
    chunking_method: str = Field(description="Method used for chunking")


class ChunksIndex(BaseModel):
    """Master index of all chunks."""

    created_at: datetime = Field(default_factory=datetime.now)
    total_chunks: int = Field(default=0)
    total_tokens: int = Field(default=0)
    source_files: list[str] = Field(default_factory=list)
    chunks: list[ChunkEntry] = Field(default_factory=list)

    def add_chunk(self, entry: ChunkEntry) -> None:
        """Add a chunk entry to the index."""
        self.chunks.append(entry)
        self.total_chunks = len(self.chunks)
        self.total_tokens += entry.estimated_tokens
        if entry.source_file not in self.source_files:
            self.source_files.append(entry.source_file)
