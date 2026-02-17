"""Meta knowledge extractor - read-and-update mode for mapping.md and eureka.md."""

from pathlib import Path
from typing import Any

import structlog

from chunks2skus.schemas.sku import SKUHeader, SKUType
from chunks2skus.utils.llm_client import call_llm_json

from .base import BaseExtractor

logger = structlog.get_logger(__name__)


# Prompt for mapping.md - ACCURACY focused
MAPPING_PROMPT = '''You are updating a precise routing document for a knowledge workspace.

Your task is to maintain mapping.md - a ROUTER that helps agents find the right SKUs.

REQUIREMENTS:
- Be ACCURATE and PRECISE - no hallucination
- Only include SKUs that actually exist (listed below)
- Describe EXACTLY when to use each SKU
- Group related SKUs logically
- Use clear, unambiguous language

CURRENT SKUs (these are the ONLY SKUs that exist):
{sku_list}

EXISTING MAPPING.md:
{mapping}

NEW CHUNK BEING PROCESSED:
{chunk_id}

TASK:
Update mapping.md to include any new SKUs from this chunk.
- Add new SKUs to appropriate sections
- Update groupings if needed
- Keep descriptions factual and precise
- Do NOT invent SKUs that don't exist

Output ONLY valid JSON:
{{
  "mapping_content": "Full markdown content for mapping.md"
}}
'''


# Prompt for eureka.md - CREATIVITY focused, READ-AND-UPDATE mode
EUREKA_PROMPT = '''You are a creative analyst maintaining a concise document of cross-cutting insights.

EXISTING EUREKA NOTES:
{existing_eureka}

NEW CHUNK BEING PROCESSED:
Chunk ID: {chunk_id}
Content (excerpt):
{content}

TASK:
Review the new chunk and decide whether it contributes any GENUINELY NOVEL insight
not already captured in the existing eureka notes. Most chunks will NOT warrant an
update — that is expected and correct.

An insight qualifies ONLY if it:
1. Identifies a cross-cutting PATTERN that spans multiple domains or concepts
2. Reveals a surprising CONNECTION between seemingly unrelated areas
3. Suggests a non-obvious DESIGN PRINCIPLE or reusable mechanism
4. Raises a fundamental QUESTION that reframes understanding

An insight does NOT qualify if it:
- Is a straightforward application of the content ("this data could power a dashboard")
- Repeats a pattern already captured under a different name
- Is domain-specific rather than cross-cutting
- Is a feature suggestion without deeper structural insight

RULES:
- Return the COMPLETE updated eureka.md content (not just additions)
- Organize by THEME (## headers), not by source chunk
- Append source chunk IDs as inline citations: [chunk_001, chunk_005]
- When a new insight strengthens an existing bullet, MERGE and update citations
- When an existing bullet is made redundant by a better formulation, REMOVE it
- Maximum 20 bullets across all themes
- If no update is needed, return the existing content UNCHANGED
- Use concise, precise language — one sentence per bullet

Output ONLY valid JSON:
{{
  "updated": true,
  "eureka_content": "Full markdown content for eureka.md"
}}

If no novel insight is found, return:
{{
  "updated": false,
  "eureka_content": ""
}}
'''


class MetaExtractor(BaseExtractor):
    """
    Extracts meta knowledge - mapping.md and eureka.md.

    Operates in read-and-update mode with TWO SEPARATE LLM calls:
    - mapping.md: Low temperature (0.2) for accuracy
    - eureka.md: High temperature (0.7) for creativity
    """

    extractor_name = "meta"
    sku_type = SKUType.META

    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self.mapping_path = self.type_dir / "mapping.md"
        self.eureka_path = self.type_dir / "eureka.md"
        self.header_path = self.type_dir / "header.md"

        # Initialize files if they don't exist
        self._init_files()

    def _init_files(self) -> None:
        """Initialize mapping.md, eureka.md, and header.md if they don't exist."""
        if not self.mapping_path.exists():
            self.mapping_path.write_text(
                "# SKU Mapping\n\n"
                "This file maps all Standard Knowledge Units (SKUs) to their use cases.\n\n"
                "---\n\n"
                "*No SKUs mapped yet.*\n",
                encoding="utf-8",
            )

        if not self.eureka_path.exists():
            self.eureka_path.write_text(
                "# Eureka Notes\n\n"
                "Cross-cutting insights and creative ideas discovered during knowledge extraction.\n\n"
                "---\n\n"
                "*No insights yet.*\n",
                encoding="utf-8",
            )

        if not self.header_path.exists():
            header = SKUHeader(
                name="meta-knowledge",
                classification=SKUType.META,
                character_count=0,
                source_chunk="aggregated",
                description="SKU routing (mapping.md) and creative insights (eureka.md)",
            )
            self.header_path.write_text(header.to_markdown(), encoding="utf-8")

    def extract(
        self,
        content: str,
        chunk_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Update meta knowledge from content using two separate LLM calls.

        Args:
            content: Chunk content to process
            chunk_id: Identifier of the source chunk
            context: Context containing all current SKUs

        Returns:
            List with single SKU info dict (the meta knowledge)
        """
        logger.info("Extracting meta knowledge", chunk_id=chunk_id)

        # Step 1: Update mapping.md (ACCURACY - low temperature)
        self._update_mapping(chunk_id, context)

        # Step 2: Update eureka.md (CREATIVITY - high temperature)
        self._update_eureka(content, chunk_id)

        # Update header with character count
        self._update_header()

        logger.info(
            "Meta extraction complete",
            chunk_id=chunk_id,
            mapping_chars=len(self.mapping_path.read_text(encoding="utf-8")),
            eureka_chars=len(self.eureka_path.read_text(encoding="utf-8")),
        )

        return [
            {
                "sku_id": "meta-knowledge",
                "name": "meta-knowledge",
                "classification": SKUType.META,
                "path": str(self.type_dir),
                "source_chunk": "aggregated",
                "character_count": self._get_total_chars(),
                "description": "SKU routing (mapping.md) and creative insights (eureka.md)",
            }
        ]

    def _update_mapping(self, chunk_id: str, context: dict[str, Any] | None) -> None:
        """
        Update mapping.md with accurate SKU routing information.
        Uses LOW temperature (0.2) for precision.
        """
        logger.debug("Updating mapping.md", chunk_id=chunk_id)

        sku_list = self._format_sku_list(context)
        current_mapping = self.mapping_path.read_text(encoding="utf-8")

        prompt = MAPPING_PROMPT.format(
            sku_list=sku_list,
            mapping=current_mapping,
            chunk_id=chunk_id,
        )

        # Low temperature for accuracy, with structured output + retry
        parsed = call_llm_json(
            prompt,
            system_prompt="You are a precise documentation assistant. Be accurate and factual. Never invent or hallucinate information.",
            temperature=0.2,
            max_tokens=8000,
        )

        if not parsed:
            logger.warning("Failed to get mapping response", chunk_id=chunk_id)
            return

        if "mapping_content" in parsed:
            new_mapping = parsed["mapping_content"]
            if new_mapping and isinstance(new_mapping, str):
                self.mapping_path.write_text(new_mapping, encoding="utf-8")
                logger.debug("Updated mapping.md")

    def _update_eureka(self, content: str, chunk_id: str) -> None:
        """
        Update eureka.md with genuinely novel cross-cutting insights.

        Uses read-and-update pattern (same as mapping.md): reads full existing
        eureka.md, LLM decides whether chunk adds novel insight, returns complete
        replacement or signals no update needed.

        Temperature 0.7 for creative latitude; the prompt enforces quality.
        """
        logger.debug("Evaluating eureka update", chunk_id=chunk_id)

        current_eureka = self.eureka_path.read_text(encoding="utf-8")

        prompt = EUREKA_PROMPT.format(
            existing_eureka=current_eureka,
            chunk_id=chunk_id,
            content=content[:8000],  # Limit content to avoid token overflow
        )

        parsed = call_llm_json(
            prompt,
            system_prompt=(
                "You are a creative visionary with high standards. "
                "Surface only insights that reveal structural patterns, surprising "
                "connections, or reusable design principles. Most chunks will not "
                "warrant an update. Quality over quantity."
            ),
            temperature=0.7,
            max_tokens=3000,
        )

        if not parsed:
            logger.warning("Failed to get eureka response", chunk_id=chunk_id)
            return

        was_updated = parsed.get("updated", False)
        new_content = parsed.get("eureka_content")

        if was_updated and new_content and isinstance(new_content, str):
            # Shrinkage guard: reject if content shrank by >50% (unless initial)
            if len(new_content) >= len(current_eureka) * 0.5 or len(current_eureka) < 100:
                self.eureka_path.write_text(new_content, encoding="utf-8")
                logger.info("Updated eureka.md", chunk_id=chunk_id)
            else:
                logger.warning(
                    "Rejected eureka update: content shrank by more than 50%",
                    old_len=len(current_eureka),
                    new_len=len(new_content),
                )
        else:
            logger.debug("No eureka update needed", chunk_id=chunk_id)

    def _format_sku_list(self, context: dict[str, Any] | None) -> str:
        """Format the current SKU list for the prompt."""
        if not context or "all_skus" not in context:
            return "*No SKUs extracted yet.*"

        skus = context["all_skus"]
        if not skus:
            return "*No SKUs extracted yet.*"

        lines = []
        for sku in skus:
            classification = sku.get("classification", "unknown")
            if hasattr(classification, "value"):
                classification = classification.value
            lines.append(
                f"- [{classification}] "
                f"{sku.get('path', 'unknown')}: {sku.get('description', 'No description')}"
            )

        return "\n".join(lines)

    def _update_header(self) -> None:
        """Update header.md with current character count."""
        header = SKUHeader(
            name="meta-knowledge",
            classification=SKUType.META,
            character_count=self._get_total_chars(),
            source_chunk="aggregated",
            description="SKU routing (mapping.md) and creative insights (eureka.md)",
        )
        self.header_path.write_text(header.to_markdown(), encoding="utf-8")

    def _get_total_chars(self) -> int:
        """Get total character count of meta knowledge."""
        total = 0
        if self.mapping_path.exists():
            total += len(self.mapping_path.read_text(encoding="utf-8"))
        if self.eureka_path.exists():
            total += len(self.eureka_path.read_text(encoding="utf-8"))
        return total
