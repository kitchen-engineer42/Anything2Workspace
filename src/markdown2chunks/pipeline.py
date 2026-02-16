"""Main orchestration pipeline for chunking markdown files."""

import json
import shutil
from datetime import datetime
from pathlib import Path

import structlog

from .config import settings
from .router import Router
from .schemas.chunk import Chunk
from .schemas.index import ChunkEntry, ChunksIndex
from .utils.token_estimator import estimate_tokens

logger = structlog.get_logger(__name__)


class ChunkingPipeline:
    """
    Main pipeline for processing markdown files into chunks.

    Input: Module 1 output directory (markdown and JSON files)
    Output: chunks/ directory with chunk files and chunks_index.json
    """

    def __init__(self, input_dir: Path | None = None, output_dir: Path | None = None):
        """
        Initialize the chunking pipeline.

        Args:
            input_dir: Directory with markdown/JSON files (default: settings.output_dir)
            output_dir: Directory to write chunks (default: settings.output_dir/chunks)
        """
        # Input is module 1's output
        self.input_dir = input_dir or settings.output_dir
        self.output_dir = output_dir or (settings.output_dir / "chunks")
        self.passthrough_dir = settings.output_dir / "passthrough"

        self.router = Router()
        self.index = ChunksIndex()

    def run(self) -> ChunksIndex:
        """
        Run the full chunking pipeline.

        Returns:
            ChunksIndex with all chunk information
        """
        start_time = datetime.now()
        logger.info(
            "Starting chunking pipeline",
            input_dir=str(self.input_dir),
            output_dir=str(self.output_dir),
        )

        # Create output directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.passthrough_dir.mkdir(parents=True, exist_ok=True)

        # Find all files
        files = list(self.input_dir.glob("*"))
        markdown_files = [f for f in files if f.suffix.lower() == ".md"]
        json_files = [f for f in files if f.suffix.lower() == ".json"]

        logger.info(
            "Found files",
            markdown=len(markdown_files),
            json=len(json_files),
        )

        # Process markdown files
        for md_file in markdown_files:
            self._process_markdown(md_file)

        # Pass through JSON files
        for json_file in json_files:
            self._passthrough_json(json_file)

        # Write index
        index_path = self.output_dir / "chunks_index.json"
        index_path.write_text(
            self.index.model_dump_json(indent=2),
            encoding="utf-8",
        )

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Chunking pipeline complete",
            total_chunks=self.index.total_chunks,
            total_tokens=self.index.total_tokens,
            source_files=len(self.index.source_files),
            duration_seconds=f"{duration:.1f}",
        )

        return self.index

    def _process_markdown(self, file_path: Path) -> None:
        """
        Process a single markdown file.

        Args:
            file_path: Path to markdown file
        """
        logger.info("Processing markdown", file=file_path.name)

        try:
            content = file_path.read_text(encoding="utf-8")
            tokens = estimate_tokens(content)

            logger.debug("File stats", chars=len(content), tokens=tokens)

            # Check if needs chunking
            if tokens <= settings.max_token_length:
                # Single chunk - no splitting needed
                chunks = self._create_single_chunk(content, file_path)
            else:
                # Get appropriate chunker
                chunker = self.router.get_chunker(content)
                chunks = chunker.chunk(content, file_path)

                # Check if any chunks still exceed limit (need LLM rechunking)
                chunks = self._rechunk_if_needed(chunks)

            # Write chunks to files
            for chunk in chunks:
                self._write_chunk(chunk, file_path)

            logger.info(
                "Processed markdown",
                file=file_path.name,
                chunks=len(chunks),
            )

        except Exception as e:
            logger.error("Failed to process markdown", file=file_path.name, error=str(e))

    def _create_single_chunk(self, content: str, source_path: Path) -> list[Chunk]:
        """Create a single chunk for small files."""
        from .schemas.chunk import Chunk, ChunkMetadata

        return [
            Chunk(
                content=content,
                metadata=ChunkMetadata(
                    title=source_path.stem,
                    chunk_index=0,
                    total_chunks=1,
                    character_count=len(content),
                    estimated_tokens=estimate_tokens(content),
                    source_file=source_path.name,
                    source_path=str(source_path),
                    header_level=None,
                    chunking_method="single",
                ),
            )
        ]

    def _rechunk_if_needed(self, chunks: list[Chunk]) -> list[Chunk]:
        """
        Re-chunk any chunks that still exceed token limit.

        Args:
            chunks: List of chunks to check

        Returns:
            List of chunks (possibly with some re-chunked)
        """
        result = []
        max_tokens = settings.max_token_length

        for chunk in chunks:
            if chunk.metadata.estimated_tokens <= max_tokens:
                result.append(chunk)
            else:
                # Need to re-chunk with LLM
                logger.info(
                    "Re-chunking oversized chunk",
                    title=chunk.metadata.title,
                    tokens=chunk.metadata.estimated_tokens,
                )
                sub_chunks = self.router.llm_chunker.chunk(
                    chunk.content,
                    Path(chunk.metadata.source_path),
                )
                # Update titles to indicate parent
                for i, sub in enumerate(sub_chunks):
                    sub.metadata.title = f"{chunk.metadata.title} (Part {i + 1})"
                result.extend(sub_chunks)

        # Update chunk indices
        for i, chunk in enumerate(result):
            chunk.metadata.chunk_index = i
            chunk.metadata.total_chunks = len(result)

        return result

    def _write_chunk(self, chunk: Chunk, source_path: Path) -> None:
        """
        Write a chunk to file and add to index.

        Args:
            chunk: Chunk to write
            source_path: Original source file path
        """
        # Generate chunk filename
        stem = source_path.stem
        chunk_id = f"{stem}_chunk_{chunk.metadata.chunk_index + 1:03d}"
        chunk_filename = f"{chunk_id}.md"
        chunk_path = self.output_dir / chunk_filename

        # Write with frontmatter
        chunk_path.write_text(
            chunk.to_markdown_with_frontmatter(),
            encoding="utf-8",
        )

        # Add to index
        entry = ChunkEntry(
            chunk_id=chunk_id,
            file_path=str(chunk_path),
            title=chunk.metadata.title,
            estimated_tokens=chunk.metadata.estimated_tokens,
            source_file=chunk.metadata.source_file,
            chunking_method=chunk.metadata.chunking_method,
        )
        self.index.add_chunk(entry)

    def _passthrough_json(self, file_path: Path) -> None:
        """
        Pass through JSON file without chunking.

        Args:
            file_path: Path to JSON file
        """
        dest_path = self.passthrough_dir / file_path.name
        shutil.copy2(file_path, dest_path)
        logger.debug("Passed through JSON", file=file_path.name)

    def chunk_single_file(self, file_path: Path) -> list[Chunk]:
        """
        Chunk a single file (for CLI use).

        Args:
            file_path: Path to markdown file

        Returns:
            List of chunks
        """
        content = file_path.read_text(encoding="utf-8")
        tokens = estimate_tokens(content)

        if tokens <= settings.max_token_length:
            return self._create_single_chunk(content, file_path)

        chunker = self.router.get_chunker(content)
        chunks = chunker.chunk(content, file_path)
        return self._rechunk_if_needed(chunks)
