"""Procedural knowledge extractor - isolated processing, creates skill folders."""

from pathlib import Path
from typing import Any

import structlog

from chunks2skus.schemas.sku import SKUHeader, SKUType
from chunks2skus.utils.llm_client import call_llm_json

from .base import BaseExtractor

logger = structlog.get_logger(__name__)


PROCEDURAL_PROMPT = '''You are extracting procedural knowledge from a document chunk.

Procedural knowledge includes:
- Workflows and step-by-step processes
- Analytical frameworks and methods
- Decision-making procedures
- Best practices and guidelines
- Actionable skills and techniques

CHUNK CONTENT:
{content}

TASK:
Extract distinct procedural knowledge units. Each should be a complete, actionable procedure.
Format each as a Claude Code compatible skill.

Output ONLY valid JSON:
{{
  "procedures": [
    {{
      "name": "skill-name-in-hyphen-case",
      "description": "When to use this skill (max 200 chars, no angle brackets)",
      "body": "Full markdown instructions including:\\n- Overview\\n- Steps (numbered or bulleted)\\n- Decision points (if any)\\n- Expected outcomes",
      "has_scripts": false,
      "scripts": [],
      "has_references": false,
      "references": []
    }}
  ]
}}

Skill Format Guidelines:
- name: lowercase, hyphen-separated, max 64 chars (e.g., "risk-assessment-workflow")
- description: Plain text, explains WHEN to use, no angle brackets
- body: Markdown format with clear structure
- scripts: Optional Python/Bash code for deterministic operations
- references: Optional supporting documentation

If no procedural knowledge is found, return: {{"procedures": []}}
'''


class ProceduralExtractor(BaseExtractor):
    """
    Extracts procedural knowledge from chunks.

    Creates isolated skill folders with SKILL.md (Claude Code format).
    Does NOT reference previous chunks (isolated processing).
    """

    extractor_name = "procedural"
    sku_type = SKUType.PROCEDURAL

    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self._skill_counter = self._get_next_skill_number()

    def _get_next_skill_number(self) -> int:
        """Find the next available skill number."""
        existing = list(self.type_dir.glob("skill_*"))
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
        Extract procedural knowledge from content.

        Args:
            content: Chunk content to process
            chunk_id: Identifier of the source chunk
            context: Optional context (not used for isolated processing)

        Returns:
            List of created SKU info dicts
        """
        logger.info("Extracting procedural knowledge", chunk_id=chunk_id)

        # Call LLM for extraction with structured output + retry
        prompt = PROCEDURAL_PROMPT.format(content=content)
        parsed = call_llm_json(prompt, max_tokens=6000)

        if not parsed or "procedures" not in parsed:
            logger.warning("Failed to get procedural extraction response", chunk_id=chunk_id)
            return []

        procedures = parsed.get("procedures", [])
        if not procedures:
            logger.info("No procedural knowledge found in chunk", chunk_id=chunk_id)
            return []

        # Create skill folders
        created_skus = []
        for procedure in procedures:
            sku_info = self._create_skill(procedure, chunk_id)
            if sku_info:
                created_skus.append(sku_info)

        logger.info(
            "Procedural extraction complete",
            chunk_id=chunk_id,
            skills_created=len(created_skus),
        )

        return created_skus

    def _create_skill(self, procedure: dict[str, Any], chunk_id: str) -> dict[str, Any] | None:
        """
        Create a skill folder with SKILL.md (Claude Code format).

        Args:
            procedure: Extracted procedure dict from LLM
            chunk_id: Source chunk ID

        Returns:
            SKU info dict, or None on failure
        """
        # Extract fields
        name = procedure.get("name", f"skill-{self._skill_counter}")
        # Ensure hyphen-case
        name = self._to_hyphen_case(name)

        description = procedure.get("description", "")
        # Sanitize description (no angle brackets, max 200 chars)
        description = description.replace("<", "").replace(">", "")[:200]

        body = procedure.get("body", "")
        has_scripts = procedure.get("has_scripts", False)
        scripts = procedure.get("scripts", [])
        has_references = procedure.get("has_references", False)
        references = procedure.get("references", [])

        # Create skill folder
        skill_id = f"skill_{self._skill_counter:03d}"
        skill_dir = self.type_dir / skill_id
        skill_dir.mkdir(exist_ok=True)

        # Create SKILL.md with YAML frontmatter
        skill_content = self._format_skill_md(name, description, body)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(skill_content, encoding="utf-8")

        char_count = len(skill_content)

        # Create scripts directory if needed
        if has_scripts and scripts:
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(exist_ok=True)
            for i, script in enumerate(scripts):
                script_name = script.get("name", f"script_{i}.py")
                script_content = script.get("content", "")
                (scripts_dir / script_name).write_text(script_content, encoding="utf-8")
                char_count += len(script_content)

        # Create references directory if needed
        if has_references and references:
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(exist_ok=True)
            for i, ref in enumerate(references):
                ref_name = ref.get("name", f"reference_{i}.md")
                ref_content = ref.get("content", "")
                (refs_dir / ref_name).write_text(ref_content, encoding="utf-8")
                char_count += len(ref_content)

        # Create header.md
        header = SKUHeader(
            name=name,
            classification=SKUType.PROCEDURAL,
            character_count=char_count,
            source_chunk=chunk_id,
            description=description[:100] if len(description) > 100 else description,
        )
        (skill_dir / "header.md").write_text(header.to_markdown(), encoding="utf-8")

        self._skill_counter += 1

        logger.debug("Created procedural SKU", skill_id=skill_id, name=name)

        return {
            "sku_id": skill_id,
            "name": name,
            "classification": SKUType.PROCEDURAL,
            "path": str(skill_dir),
            "source_chunk": chunk_id,
            "character_count": char_count,
            "description": description,
        }

    def _to_hyphen_case(self, text: str) -> str:
        """Convert text to hyphen-case."""
        import re

        # Replace spaces and underscores with hyphens
        result = re.sub(r"[\s_]+", "-", text.lower())
        # Remove non-alphanumeric except hyphens
        result = re.sub(r"[^a-z0-9-]", "", result)
        # Remove leading/trailing hyphens and double hyphens
        result = re.sub(r"-+", "-", result).strip("-")
        # Max 64 chars
        return result[:64]

    def _format_skill_md(self, name: str, description: str, body: str) -> str:
        """
        Format SKILL.md with YAML frontmatter (Claude Code skill format).

        Args:
            name: Skill name (hyphen-case)
            description: When to use this skill
            body: Markdown instructions

        Returns:
            Formatted SKILL.md content
        """
        return f'''---
name: {name}
description: {description}
---

{body}
'''
