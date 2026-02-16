"""Header-based chunker - the 'Peeling Onion' strategy."""

from pathlib import Path

import structlog

from ..config import settings
from ..schemas.chunk import Chunk, ChunkMetadata
from ..utils.markdown_utils import MarkdownSection, build_section_tree, parse_headers
from ..utils.token_estimator import estimate_tokens, get_token_limit
from .base import BaseChunker

logger = structlog.get_logger(__name__)


class HeaderChunker(BaseChunker):
    """
    Chunk markdown by headers - the 'Peeling Onion' strategy.

    For well-structured markdown with headers, splits hierarchically
    by header levels (H1 -> H2 -> H3...), only splitting when a
    section exceeds the max token length.
    """

    chunker_name = "header"

    def __init__(self):
        self.max_tokens = get_token_limit()

    def can_handle(self, content: str) -> bool:
        """
        Check if content has markdown headers.

        Args:
            content: Markdown content

        Returns:
            True if content contains headers
        """
        sections = parse_headers(content)
        # Can handle if there are header sections (not just level=0)
        return any(s.level > 0 for s in sections)

    def chunk(self, content: str, source_path: Path) -> list[Chunk]:
        """
        Split markdown content by headers.

        Args:
            content: Full markdown text
            source_path: Path to source file

        Returns:
            List of Chunk objects
        """
        total_tokens = estimate_tokens(content)

        # If within limit, return as single chunk
        if total_tokens <= self.max_tokens:
            logger.info(
                "Content within token limit, single chunk",
                tokens=total_tokens,
                max=self.max_tokens,
            )
            return [
                self._create_chunk(
                    content=content,
                    title=source_path.stem,
                    source_path=source_path,
                    chunk_index=0,
                    total_chunks=1,
                    header_level=None,
                    method="single",
                )
            ]

        # Parse into sections
        sections = parse_headers(content)
        tree = build_section_tree(sections)

        # Process tree to create chunks
        chunks = []
        self._process_tree(tree, source_path, chunks)

        # Update total_chunks in all metadata
        for chunk in chunks:
            chunk.metadata.total_chunks = len(chunks)

        logger.info(
            "Header chunking complete",
            input_tokens=total_tokens,
            chunks=len(chunks),
        )

        return chunks

    def _process_tree(
        self, nodes: list[dict], source_path: Path, chunks: list[Chunk]
    ) -> None:
        """
        Recursively process section tree to create chunks.

        Args:
            nodes: List of tree nodes
            source_path: Source file path
            chunks: Accumulator list for chunks
        """
        for node in nodes:
            section: MarkdownSection = node["section"]
            children = node.get("children", [])

            # Calculate total tokens for this section + all children
            total_section_tokens = self._calculate_subtree_tokens(node)

            if total_section_tokens <= self.max_tokens:
                # This section (with all children) fits in one chunk
                content = self._extract_subtree_content(node)
                title = section.title if section.title else source_path.stem

                chunks.append(
                    self._create_chunk(
                        content=content,
                        title=title,
                        source_path=source_path,
                        chunk_index=len(chunks),
                        total_chunks=0,  # Updated later
                        header_level=section.level if section.level > 0 else None,
                        method="header",
                    )
                )
            else:
                # Section too large - need to split further
                if children:
                    # First, check if section header + intro content fits
                    intro_content = self._get_section_intro(section)
                    if intro_content.strip():
                        intro_tokens = estimate_tokens(intro_content)
                        if intro_tokens > 0:
                            chunks.append(
                                self._create_chunk(
                                    content=intro_content,
                                    title=f"{section.title} (Introduction)"
                                    if section.title
                                    else "Introduction",
                                    source_path=source_path,
                                    chunk_index=len(chunks),
                                    total_chunks=0,
                                    header_level=section.level if section.level > 0 else None,
                                    method="header",
                                )
                            )

                    # Recursively process children
                    self._process_tree(children, source_path, chunks)
                else:
                    # No children but still too large - this section needs LLM chunking
                    # Mark it for fallback (will be handled by pipeline)
                    logger.warning(
                        "Section exceeds token limit, needs LLM fallback",
                        title=section.title,
                        tokens=section.token_count,
                    )
                    # Still add it as a chunk, pipeline will re-chunk with LLM
                    chunks.append(
                        self._create_chunk(
                            content=section.content,
                            title=section.title if section.title else "Oversized Section",
                            source_path=source_path,
                            chunk_index=len(chunks),
                            total_chunks=0,
                            header_level=section.level if section.level > 0 else None,
                            method="header",  # Will be marked as needing LLM
                        )
                    )

    def _calculate_subtree_tokens(self, node: dict) -> int:
        """Calculate total tokens for a node and all its children."""
        section: MarkdownSection = node["section"]
        total = section.token_count

        for child in node.get("children", []):
            # Children's content is already included in parent's content
            # so we don't double-count
            pass

        return total

    def _extract_subtree_content(self, node: dict) -> str:
        """Extract full content for a node (children already included)."""
        section: MarkdownSection = node["section"]
        return section.content

    def _get_section_intro(self, section: MarkdownSection) -> str:
        """
        Get the introduction content of a section (before first child header).

        Args:
            section: MarkdownSection object

        Returns:
            Introduction content including the header
        """
        import re

        content = section.content

        # Find the first sub-header (higher level number = lower in hierarchy)
        # For an H2 section, look for H3 or deeper
        pattern = rf"^#{{{section.level + 1},6}}\s+"

        match = re.search(pattern, content, re.MULTILINE)
        if match:
            return content[: match.start()]
        return content

    def _create_chunk(
        self,
        content: str,
        title: str,
        source_path: Path,
        chunk_index: int,
        total_chunks: int,
        header_level: int | None,
        method: str,
    ) -> Chunk:
        """Create a Chunk object with metadata."""
        return Chunk(
            content=content,
            metadata=ChunkMetadata(
                title=title,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                character_count=len(content),
                estimated_tokens=estimate_tokens(content),
                source_file=source_path.name,
                source_path=str(source_path),
                header_level=header_level,
                chunking_method=method,
            ),
        )
