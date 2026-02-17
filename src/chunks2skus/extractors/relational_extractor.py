"""Relational knowledge extractor - read-and-update mode."""

import json
from pathlib import Path
from typing import Any

import structlog

from chunks2skus.schemas.sku import (
    Glossary,
    GlossaryEntry,
    LabelTree,
    Relationship,
    RelationType,
    Relationships,
    SKUHeader,
    SKUType,
)
from chunks2skus.utils.llm_client import call_llm_json

from .base import BaseExtractor

logger = structlog.get_logger(__name__)


RELATIONAL_PROMPT = '''You are building a domain knowledge base by extracting relational knowledge.

Relational knowledge includes:
- Relationships between concepts (A causes B, X is part of Y)
- Hierarchical categorizations (topics, subtopics)
- Causal and contextual knowledge (why, because, but, if-then)
- Domain terminology and definitions
- Aliases and alternative names for the same concept

EXISTING LABEL TREE:
{label_tree}

EXISTING GLOSSARY (excerpt, {glossary_count} total entries):
{glossary}

NEW CHUNK CONTENT:
{content}

TASK:
Update the knowledge base with new relational knowledge from this chunk.

1. ADD new labels to the tree hierarchy (preserve all existing labels)
2. ADD new glossary entries or UPDATE existing ones with richer definitions
3. Link glossary terms to relevant labels
4. Extract TYPED RELATIONSHIPS between concepts
5. Extract ALIASES (abbreviations, acronyms, alternative names)

Output ONLY valid JSON:
{{
  "label_tree": {{
    "roots": [
      {{
        "name": "Category Name",
        "children": [
          {{"name": "Subcategory", "children": []}}
        ]
      }}
    ]
  }},
  "glossary": {{
    "entries": [
      {{
        "term": "Term Name",
        "definition": "Clear definition of the term",
        "labels": ["Category", "Subcategory"],
        "source_chunks": ["{chunk_id}"],
        "aliases": ["Abbreviation", "Alternative Name"],
        "related_terms": ["OtherTerm1", "OtherTerm2"]
      }}
    ]
  }},
  "relationships": [
    {{
      "subject": "Concept A",
      "predicate": "causes",
      "object": "Concept B",
      "source_chunks": ["{chunk_id}"]
    }}
  ]
}}

Valid predicates: "is-a", "has-a", "part-of", "causes", "caused-by", "requires", "enables", "contradicts", "related-to", "depends-on", "regulates", "implements", "example-of"

Guidelines:
- Preserve ALL existing labels and glossary entries
- Add new entries, don't delete existing ones
- Keep definitions concise but complete
- Use consistent naming for labels (Title Case)
- For aliases: include abbreviations (e.g., "G-SIB" for "Global Systemically Important Banks")
- For relationships: only extract clearly stated relationships, not speculative ones
'''


class RelationalExtractor(BaseExtractor):
    """
    Extracts relational knowledge from chunks.

    Operates in read-and-update mode:
    - Reads existing label_tree.json and glossary.json
    - Updates them with new knowledge from each chunk
    - Provides context for Meta extractor
    """

    extractor_name = "relational"
    sku_type = SKUType.RELATIONAL

    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self.label_tree_path = self.type_dir / "label_tree.json"
        self.glossary_path = self.type_dir / "glossary.json"
        self.relationships_path = self.type_dir / "relationships.json"
        self.header_path = self.type_dir / "header.md"

        # Load or initialize data structures
        self.label_tree = self._load_label_tree()
        self.glossary = self._load_glossary()
        self.relationships = self._load_relationships()

        # Create header.md on first run
        if not self.header_path.exists():
            self._create_header()

    def _load_label_tree(self) -> LabelTree:
        """Load existing label tree or create empty one."""
        if self.label_tree_path.exists():
            try:
                data = json.loads(self.label_tree_path.read_text(encoding="utf-8"))
                return LabelTree.model_validate(data)
            except Exception as e:
                logger.warning("Failed to load label tree", error=str(e))
        return LabelTree()

    def _load_glossary(self) -> Glossary:
        """Load existing glossary or create empty one."""
        if self.glossary_path.exists():
            try:
                data = json.loads(self.glossary_path.read_text(encoding="utf-8"))
                return Glossary.model_validate(data)
            except Exception as e:
                logger.warning("Failed to load glossary", error=str(e))
        return Glossary()

    def _load_relationships(self) -> Relationships:
        """Load existing relationships or create empty collection."""
        if self.relationships_path.exists():
            try:
                data = json.loads(self.relationships_path.read_text(encoding="utf-8"))
                return Relationships.model_validate(data)
            except Exception as e:
                logger.warning("Failed to load relationships", error=str(e))
        return Relationships()

    def _create_header(self) -> None:
        """Create header.md for relational knowledge."""
        header = SKUHeader(
            name="relational-knowledge-base",
            classification=SKUType.RELATIONAL,
            character_count=0,  # Updated on save
            source_chunk="aggregated",
            description="Domain label hierarchy and terminology glossary",
        )
        self.header_path.write_text(header.to_markdown(), encoding="utf-8")

    def _save_data(self) -> None:
        """Save label tree, glossary, and relationships to disk."""
        # Save label tree
        self.label_tree_path.write_text(
            self.label_tree.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # Save glossary
        self.glossary_path.write_text(
            self.glossary.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # Save relationships
        self.relationships_path.write_text(
            self.relationships.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # Update header with character count
        total_chars = self._get_total_chars()
        header = SKUHeader(
            name="relational-knowledge-base",
            classification=SKUType.RELATIONAL,
            character_count=total_chars,
            source_chunk="aggregated",
            description="Domain label hierarchy, terminology glossary, and typed relationships",
        )
        self.header_path.write_text(header.to_markdown(), encoding="utf-8")

    def extract(
        self,
        content: str,
        chunk_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Update relational knowledge from content.

        Args:
            content: Chunk content to process
            chunk_id: Identifier of the source chunk
            context: Optional context from factual extractor

        Returns:
            List with single SKU info dict (the relational knowledge base)
        """
        logger.info("Extracting relational knowledge", chunk_id=chunk_id)

        # Prepare current state as context for LLM
        current_tree = self.label_tree.model_dump_json(indent=2)
        # Truncate glossary for large corpora to avoid token overflow
        glossary_count = len(self.glossary.entries)
        glossary_json = self.glossary.model_dump_json(indent=2)
        if len(glossary_json) > 6000:
            # Show only first 20 entries + note that there are more
            truncated = Glossary(entries=self.glossary.entries[:20])
            glossary_json = truncated.model_dump_json(indent=2)

        # Call LLM for extraction with structured output + retry
        prompt = RELATIONAL_PROMPT.format(
            label_tree=current_tree,
            glossary=glossary_json,
            glossary_count=glossary_count,
            content=content,
            chunk_id=chunk_id,
        )
        parsed = call_llm_json(prompt, max_tokens=8000)

        if not parsed:
            logger.warning("Failed to get relational extraction response", chunk_id=chunk_id)
            return []

        # Update label tree
        if "label_tree" in parsed:
            try:
                new_tree = LabelTree.model_validate(parsed["label_tree"])
                self._merge_label_tree(new_tree)
            except Exception as e:
                logger.warning("Failed to parse new label tree", error=str(e))

        # Update glossary
        if "glossary" in parsed:
            try:
                new_glossary = Glossary.model_validate(parsed["glossary"])
                self._merge_glossary(new_glossary)
            except Exception as e:
                logger.warning("Failed to parse new glossary", error=str(e))

        # Update relationships
        if "relationships" in parsed:
            try:
                for rel_data in parsed["relationships"]:
                    predicate_str = rel_data.get("predicate", "related-to")
                    try:
                        predicate = RelationType(predicate_str)
                    except ValueError:
                        predicate = RelationType.RELATED_TO
                    rel = Relationship(
                        subject=rel_data["subject"],
                        predicate=predicate,
                        object=rel_data["object"],
                        source_chunks=rel_data.get("source_chunks", [chunk_id]),
                    )
                    self.relationships.add(rel)
            except Exception as e:
                logger.warning("Failed to parse relationships", error=str(e))

        # Save updated data
        self._save_data()

        logger.info(
            "Relational extraction complete",
            chunk_id=chunk_id,
            labels=len(self.label_tree.roots),
            terms=len(self.glossary.entries),
            relationships=len(self.relationships.entries),
        )

        return [
            {
                "sku_id": "relational-knowledge-base",
                "name": "relational-knowledge-base",
                "classification": SKUType.RELATIONAL,
                "path": str(self.type_dir),
                "source_chunk": "aggregated",
                "character_count": self._get_total_chars(),
                "description": "Domain label hierarchy and terminology glossary",
            }
        ]

    def _merge_label_tree(self, new_tree: LabelTree) -> None:
        """Merge new labels into existing tree."""
        for new_root in new_tree.roots:
            self._merge_node(self.label_tree.roots, new_root)

    def _merge_node(self, existing_list: list, new_node) -> None:
        """Recursively merge a node into an existing list."""
        # Check if node with same name exists
        existing = None
        for node in existing_list:
            if node.name.lower() == new_node.name.lower():
                existing = node
                break

        if existing:
            # Merge children
            for child in new_node.children:
                self._merge_node(existing.children, child)
        else:
            # Add new node
            existing_list.append(new_node)

    def _merge_glossary(self, new_glossary: Glossary) -> None:
        """Merge new glossary entries into existing glossary."""
        for entry in new_glossary.entries:
            self.glossary.add_or_update(entry)

    def _get_total_chars(self) -> int:
        """Get total character count of relational knowledge."""
        total = 0
        for path in [self.label_tree_path, self.glossary_path, self.relationships_path]:
            if path.exists():
                total += len(path.read_text(encoding="utf-8"))
        return total

    def get_context_for_next(self) -> dict[str, Any]:
        """Provide label tree, glossary, and relationships to next extractors."""
        return {
            "label_tree": self.label_tree,
            "glossary": self.glossary,
            "relationships": self.relationships,
        }
