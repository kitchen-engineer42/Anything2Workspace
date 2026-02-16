"""Factual knowledge extractor - isolated processing, creates new SKUs."""

import json
from pathlib import Path
from typing import Any

import structlog

from chunks2skus.schemas.sku import SKUHeader, SKUType
from chunks2skus.utils.llm_client import call_llm, parse_json_response

from .base import BaseExtractor

logger = structlog.get_logger(__name__)


FACTUAL_PROMPT = '''You are extracting factual knowledge from a document chunk.

Factual knowledge includes:
- Basic facts, definitions, and data points
- Statistics and measurements
- "What is what" information
- Descriptive details

CHUNK CONTENT:
{content}

TASK:
Extract distinct factual knowledge units. Each unit should be self-contained.
For structured/tabular data, use JSON format. For narrative facts, use markdown.

Follow the MECE principle (Mutually Exclusive, Collectively Exhaustive):
- Facts should not overlap
- Cover all factual content in the chunk

Output ONLY valid JSON:
{{
  "facts": [
    {{
      "name": "short-identifier-name",
      "description": "One-line summary of this factual unit",
      "content_type": "markdown" or "json",
      "content": "The actual factual content (string for markdown, object/array for json)"
    }}
  ]
}}

If no factual knowledge is found, return: {{"facts": []}}
'''


class FactualExtractor(BaseExtractor):
    """
    Extracts factual knowledge from chunks.

    Creates isolated SKU folders with header.md + content.md/json.
    Does NOT reference previous chunks (isolated processing).
    """

    extractor_name = "factual"
    sku_type = SKUType.FACTUAL

    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self._sku_counter = self._get_next_sku_number()

    def _get_next_sku_number(self) -> int:
        """Find the next available SKU number."""
        existing = list(self.type_dir.glob("sku_*"))
        if not existing:
            return 1
        numbers = []
        for d in existing:
            try:
                num = int(d.name.split("_")[1])
                numbers.append(num)
            except (IndexError, ValueError):
                pass
        return max(numbers, default=0) + 1

    def extract(
        self,
        content: str,
        chunk_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Extract factual knowledge from content.

        Args:
            content: Chunk content to process
            chunk_id: Identifier of the source chunk
            context: Ignored (isolated processing)

        Returns:
            List of created SKU info dicts
        """
        logger.info("Extracting factual knowledge", chunk_id=chunk_id)

        # Call LLM for extraction
        prompt = FACTUAL_PROMPT.format(content=content)
        response = call_llm(prompt)

        if not response:
            logger.warning("LLM returned no response for factual extraction")
            return []

        # Parse response
        parsed = parse_json_response(response)
        if not parsed or "facts" not in parsed:
            logger.warning("Failed to parse factual extraction response")
            return []

        facts = parsed.get("facts", [])
        if not facts:
            logger.info("No factual knowledge found in chunk", chunk_id=chunk_id)
            return []

        # Create SKU folders
        created_skus = []
        for fact in facts:
            sku_info = self._create_sku(fact, chunk_id)
            if sku_info:
                created_skus.append(sku_info)

        logger.info(
            "Factual extraction complete",
            chunk_id=chunk_id,
            skus_created=len(created_skus),
        )

        return created_skus

    def _create_sku(self, fact: dict[str, Any], chunk_id: str) -> dict[str, Any] | None:
        """
        Create an SKU folder with header.md and content file.

        Args:
            fact: Extracted fact dict from LLM
            chunk_id: Source chunk ID

        Returns:
            SKU info dict, or None on failure
        """
        name = fact.get("name", f"fact_{self._sku_counter}")
        description = fact.get("description", "")
        content_type = fact.get("content_type", "markdown")
        content = fact.get("content", "")

        # Create SKU folder
        sku_id = f"sku_{self._sku_counter:03d}"
        sku_dir = self.type_dir / sku_id
        sku_dir.mkdir(exist_ok=True)

        # Determine content and character count
        if content_type == "json" and isinstance(content, (dict, list)):
            content_str = json.dumps(content, ensure_ascii=False, indent=2)
            content_file = sku_dir / "content.json"
        else:
            content_str = str(content)
            content_file = sku_dir / "content.md"

        char_count = len(content_str)

        # Create header.md
        header = SKUHeader(
            name=name,
            classification=SKUType.FACTUAL,
            character_count=char_count,
            source_chunk=chunk_id,
            description=description,
        )

        header_path = sku_dir / "header.md"
        header_path.write_text(header.to_markdown(), encoding="utf-8")

        # Create content file
        content_file.write_text(content_str, encoding="utf-8")

        self._sku_counter += 1

        logger.debug("Created factual SKU", sku_id=sku_id, name=name)

        return {
            "sku_id": sku_id,
            "name": name,
            "classification": SKUType.FACTUAL,
            "path": str(sku_dir),
            "source_chunk": chunk_id,
            "character_count": char_count,
            "description": description,
        }
