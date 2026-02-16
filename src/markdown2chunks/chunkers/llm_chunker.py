"""LLM-based chunker - the 'Driving Wedges' strategy with Rolling Context Window."""

import json
import re
from pathlib import Path

import structlog
from openai import OpenAI

from ..config import settings
from ..schemas.chunk import Chunk, ChunkMetadata
from ..utils.levenshtein import find_cut_position
from ..utils.token_estimator import estimate_tokens, get_token_limit, truncate_to_tokens
from .base import BaseChunker

logger = structlog.get_logger(__name__)


CHUNKING_PROMPT = '''You are analyzing a document section to find logical break points.

CONTENT:
{content}

TASK:
Find 1-3 natural break points where this text could be split into separate chunks.
For each break point, provide:
1. The exact ~{k} tokens BEFORE the break point (copy exact text)
2. The exact ~{k} tokens AFTER the break point (copy exact text)
3. A short title (5-10 words) for the chunk that would END at this break

Output ONLY valid JSON (no markdown, no explanation):
{{
  "cut_points": [
    {{
      "tokens_before": "...exact text before cut...",
      "tokens_after": "...exact text after cut...",
      "chunk_title": "Title for preceding chunk"
    }}
  ]
}}

Guidelines:
- Cut at paragraph boundaries when possible
- Keep related concepts together
- Prefer cuts between major topics or ideas
- First cut_point is your most recommended
- Copy text EXACTLY as it appears'''


class LLMChunker(BaseChunker):
    """
    LLM-based chunker using 'Driving Wedges' strategy.

    For plain text or oversized sections without headers:
    1. Send content window to LLM
    2. LLM identifies cut points with K tokens before/after
    3. Use Levenshtein distance to locate exact cut positions
    4. Rolling Context Window slides through document
    """

    chunker_name = "llm"

    def __init__(self):
        self.max_tokens = get_token_limit()  # Max tokens and Rolling Context Window
        self.k_tokens = settings.k_nearest_tokens

        # Initialize OpenAI client for SiliconFlow
        self.client = None
        if settings.siliconflow_api_key:
            self.client = OpenAI(
                api_key=settings.siliconflow_api_key,
                base_url=settings.siliconflow_base_url,
            )

    def can_handle(self, content: str) -> bool:
        """
        LLM chunker is a fallback - always can handle.

        Args:
            content: Any content

        Returns:
            True (fallback handler)
        """
        return True

    def chunk(self, content: str, source_path: Path) -> list[Chunk]:
        """
        Split content using LLM-identified cut points.

        Uses Rolling Context Window to process long documents.

        Args:
            content: Full text content
            source_path: Path to source file

        Returns:
            List of Chunk objects
        """
        if not self.client:
            logger.error("SiliconFlow API key not configured")
            # Fallback: return as single oversized chunk
            return [
                self._create_chunk(
                    content=content,
                    title=source_path.stem,
                    source_path=source_path,
                    chunk_index=0,
                    total_chunks=1,
                )
            ]

        total_tokens = estimate_tokens(content)

        # If within limit, return as single chunk
        if total_tokens <= self.max_tokens:
            return [
                self._create_chunk(
                    content=content,
                    title=source_path.stem,
                    source_path=source_path,
                    chunk_index=0,
                    total_chunks=1,
                )
            ]

        # Process with Rolling Context Window
        chunks = []
        remaining_text = content
        chunk_index = 0

        while remaining_text:
            remaining_tokens = estimate_tokens(remaining_text)

            if remaining_tokens <= self.max_tokens:
                # Final chunk
                title = f"Part {chunk_index + 1}" if chunk_index > 0 else source_path.stem
                chunks.append(
                    self._create_chunk(
                        content=remaining_text,
                        title=title,
                        source_path=source_path,
                        chunk_index=chunk_index,
                        total_chunks=0,  # Updated later
                    )
                )
                break

            # Get window for LLM (limited by LLM's context window)
            window_text = truncate_to_tokens(remaining_text, self.max_tokens)

            # Ask LLM for cut points
            cut_info = self._get_cut_points(window_text)

            if not cut_info:
                # LLM failed - force split at paragraph boundary
                cut_pos = self._find_paragraph_boundary(remaining_text, self.max_tokens)
                chunk_content = remaining_text[:cut_pos]
                remaining_text = remaining_text[cut_pos:].lstrip()
                title = f"Part {chunk_index + 1}"
            else:
                # Use first cut point
                cut = cut_info[0]
                cut_pos = find_cut_position(
                    cut["tokens_before"],
                    cut["tokens_after"],
                    remaining_text,
                )

                if cut_pos is None or cut_pos < 100:
                    # Fallback to paragraph boundary
                    cut_pos = self._find_paragraph_boundary(remaining_text, self.max_tokens)
                    title = f"Part {chunk_index + 1}"
                else:
                    title = cut.get("chunk_title", f"Part {chunk_index + 1}")

                chunk_content = remaining_text[:cut_pos].rstrip()
                remaining_text = remaining_text[cut_pos:].lstrip()

            chunks.append(
                self._create_chunk(
                    content=chunk_content,
                    title=title,
                    source_path=source_path,
                    chunk_index=chunk_index,
                    total_chunks=0,
                )
            )

            chunk_index += 1
            logger.info(
                "Created chunk",
                index=chunk_index,
                chars=len(chunk_content),
                remaining=len(remaining_text),
            )

        # Update total_chunks
        for chunk in chunks:
            chunk.metadata.total_chunks = len(chunks)

        logger.info(
            "LLM chunking complete",
            input_tokens=total_tokens,
            chunks=len(chunks),
        )

        return chunks

    def _get_cut_points(self, content: str) -> list[dict] | None:
        """
        Call LLM to get suggested cut points.

        Args:
            content: Text window to analyze

        Returns:
            List of cut point dicts, or None on failure
        """
        try:
            prompt = CHUNKING_PROMPT.format(content=content, k=self.k_tokens)

            response = self.client.chat.completions.create(
                model=settings.chunking_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a document analyst. Output ONLY valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )

            result_text = response.choices[0].message.content.strip()

            # Clean up response (remove markdown code blocks if present)
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                result_text = "\n".join(lines[1:-1])

            # Try parsing with fallback for malformed JSON
            cut_points = self._parse_llm_response(result_text)

            if cut_points:
                logger.debug("LLM returned cut points", count=len(cut_points))
            return cut_points

        except Exception as e:
            logger.error("LLM call failed", error=str(e))
            return None

    def _parse_llm_response(self, text: str) -> list[dict] | None:
        """
        Parse LLM response with fallback for malformed JSON.

        First tries standard JSON parsing. If that fails, uses regex
        to extract values between entry names.

        Args:
            text: Raw LLM response text

        Returns:
            List of cut point dicts, or None on failure
        """
        # Try standard JSON first
        try:
            result = json.loads(text)
            return result.get("cut_points", [])
        except json.JSONDecodeError:
            pass

        # Fallback: extract using regex patterns
        logger.debug("JSON parse failed, trying regex extraction")

        cut_points = []

        # Pattern to find cut_point blocks (handles both quoted and unquoted keys)
        # Look for tokens_before, tokens_after, chunk_title patterns
        block_pattern = re.compile(
            r'["\']?tokens_before["\']?\s*:\s*["\'](.+?)["\']'
            r'.*?["\']?tokens_after["\']?\s*:\s*["\'](.+?)["\']'
            r'.*?["\']?chunk_title["\']?\s*:\s*["\'](.+?)["\']',
            re.DOTALL
        )

        matches = block_pattern.findall(text)

        if matches:
            for tokens_before, tokens_after, chunk_title in matches:
                # Clean up extracted values (unescape if needed)
                cut_points.append({
                    "tokens_before": tokens_before.replace('\\"', '"').replace("\\'", "'"),
                    "tokens_after": tokens_after.replace('\\"', '"').replace("\\'", "'"),
                    "chunk_title": chunk_title.replace('\\"', '"').replace("\\'", "'"),
                })
            logger.debug("Regex extraction succeeded", count=len(cut_points))
            return cut_points

        # Try alternative pattern (entries in different order)
        alt_pattern = re.compile(
            r'["\']?chunk_title["\']?\s*:\s*["\'](.+?)["\']'
            r'.*?["\']?tokens_before["\']?\s*:\s*["\'](.+?)["\']'
            r'.*?["\']?tokens_after["\']?\s*:\s*["\'](.+?)["\']',
            re.DOTALL
        )

        matches = alt_pattern.findall(text)

        if matches:
            for chunk_title, tokens_before, tokens_after in matches:
                cut_points.append({
                    "tokens_before": tokens_before.replace('\\"', '"').replace("\\'", "'"),
                    "tokens_after": tokens_after.replace('\\"', '"').replace("\\'", "'"),
                    "chunk_title": chunk_title.replace('\\"', '"').replace("\\'", "'"),
                })
            logger.debug("Regex extraction (alt pattern) succeeded", count=len(cut_points))
            return cut_points

        logger.warning("Failed to extract cut points from LLM response")
        return None

    def _find_paragraph_boundary(self, text: str, max_tokens: int) -> int:
        """
        Find a paragraph boundary within token limit.

        Args:
            text: Text to search
            max_tokens: Maximum tokens for chunk

        Returns:
            Character position for cut
        """
        # Get text within token limit
        limited_text = truncate_to_tokens(text, max_tokens)
        min_pos = 100  # Minimum position to avoid degenerate cuts

        # Find last paragraph break
        last_para = limited_text.rfind("\n\n")
        if last_para > min_pos:
            return last_para + 2  # Include newlines

        # Find last single newline
        last_newline = limited_text.rfind("\n")
        if last_newline > min_pos:
            return last_newline + 1

        # Find last sentence boundary
        for sep in [". ", "! ", "? "]:
            last_sent = limited_text.rfind(sep)
            if last_sent > min_pos:
                return last_sent + len(sep)

        # Fallback: just use the token limit
        return len(limited_text)

    def _create_chunk(
        self,
        content: str,
        title: str,
        source_path: Path,
        chunk_index: int,
        total_chunks: int,
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
                header_level=None,
                chunking_method="llm",
            ),
        )
