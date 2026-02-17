"""SKU (Standard Knowledge Unit) schemas."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SKUType(str, Enum):
    """Classification of knowledge types."""

    FACTUAL = "factual"
    RELATIONAL = "relational"
    PROCEDURAL = "procedural"
    META = "meta"


class SKUHeader(BaseModel):
    """Minimal metadata for an SKU (stored in header.md)."""

    name: str = Field(..., description="SKU name/identifier")
    classification: SKUType = Field(..., description="Type of knowledge")
    character_count: int = Field(..., description="Total characters in content")
    source_chunk: str = Field(..., description="Source chunk ID, e.g., 'document_chunk_003'")
    description: str = Field(..., description="One-line description of the SKU")
    confidence: Optional[float] = Field(
        default=None, description="Proofreading confidence score (0.0-1.0)"
    )
    related_skus: list[str] = Field(
        default_factory=list,
        description="IDs of related SKUs (cross-links for navigation)",
    )

    def to_markdown(self) -> str:
        """Render header as markdown."""
        lines = [
            f"# {self.name}",
            "",
            f"- **Classification**: {self.classification.value}",
            f"- **Source**: {self.source_chunk}",
            f"- **Characters**: {self.character_count:,}",
        ]
        if self.confidence is not None:
            lines.append(f"- **Confidence**: {self.confidence:.2f}")
        if self.related_skus:
            lines.append(f"- **Related SKUs**: {', '.join(self.related_skus)}")
        lines.append("")
        lines.append(self.description)
        lines.append("")
        return "\n".join(lines)


# --- Relational Knowledge Schemas ---


class LabelNode(BaseModel):
    """A node in the label tree hierarchy."""

    name: str = Field(..., description="Label name")
    children: list[LabelNode] = Field(default_factory=list, description="Child labels")

    def find_or_create_child(self, name: str) -> LabelNode:
        """Find existing child or create new one."""
        for child in self.children:
            if child.name.lower() == name.lower():
                return child
        new_child = LabelNode(name=name)
        self.children.append(new_child)
        return new_child


class LabelTree(BaseModel):
    """Multi-level label hierarchy for categorizing knowledge."""

    roots: list[LabelNode] = Field(default_factory=list, description="Top-level labels")

    def add_path(self, path: list[str]) -> None:
        """
        Add a label path like ["Finance", "Risk", "Credit Risk"].
        Creates nodes as needed.
        """
        if not path:
            return

        # Find or create root
        root_name = path[0]
        root = None
        for r in self.roots:
            if r.name.lower() == root_name.lower():
                root = r
                break
        if root is None:
            root = LabelNode(name=root_name)
            self.roots.append(root)

        # Traverse/create remaining path
        current = root
        for label_name in path[1:]:
            current = current.find_or_create_child(label_name)

    def get_all_paths(self) -> list[list[str]]:
        """Get all label paths as flat list."""
        paths = []

        def traverse(node: LabelNode, current_path: list[str]) -> None:
            current_path = current_path + [node.name]
            if not node.children:
                paths.append(current_path)
            else:
                for child in node.children:
                    traverse(child, current_path)

        for root in self.roots:
            traverse(root, [])
        return paths


class RelationType(str, Enum):
    """Types of relationships between concepts."""

    IS_A = "is-a"
    HAS_A = "has-a"
    PART_OF = "part-of"
    CAUSES = "causes"
    CAUSED_BY = "caused-by"
    REQUIRES = "requires"
    ENABLES = "enables"
    CONTRADICTS = "contradicts"
    RELATED_TO = "related-to"
    DEPENDS_ON = "depends-on"
    REGULATES = "regulates"
    IMPLEMENTS = "implements"
    EXAMPLE_OF = "example-of"


class Relationship(BaseModel):
    """A typed relationship between two concepts."""

    subject: str = Field(..., description="Source concept/entity")
    predicate: RelationType = Field(..., description="Type of relationship")
    object: str = Field(..., description="Target concept/entity")
    source_chunks: list[str] = Field(
        default_factory=list,
        description="Chunks where this relationship was found",
    )
    confidence: Optional[float] = Field(
        default=None, description="Extraction confidence (0.0-1.0)"
    )


class Relationships(BaseModel):
    """Collection of typed relationships extracted from the corpus."""

    entries: list[Relationship] = Field(default_factory=list)

    def add(self, rel: Relationship) -> None:
        """Add a relationship, deduplicating by (subject, predicate, object)."""
        for existing in self.entries:
            if (
                existing.subject.lower() == rel.subject.lower()
                and existing.predicate == rel.predicate
                and existing.object.lower() == rel.object.lower()
            ):
                # Merge source chunks
                for sc in rel.source_chunks:
                    if sc not in existing.source_chunks:
                        existing.source_chunks.append(sc)
                return
        self.entries.append(rel)

    def get_by_subject(self, subject: str) -> list[Relationship]:
        """Get all relationships for a given subject."""
        return [r for r in self.entries if r.subject.lower() == subject.lower()]

    def get_by_object(self, obj: str) -> list[Relationship]:
        """Get all relationships targeting a given object."""
        return [r for r in self.entries if r.object.lower() == obj.lower()]

    def get_by_type(self, rel_type: RelationType) -> list[Relationship]:
        """Get all relationships of a given type."""
        return [r for r in self.entries if r.predicate == rel_type]


class GlossaryEntry(BaseModel):
    """A term definition in the glossary."""

    term: str = Field(..., description="The term being defined")
    definition: str = Field(..., description="Definition of the term")
    labels: list[str] = Field(
        default_factory=list,
        description="Label path(s) this term belongs to, e.g., ['Finance', 'Risk']",
    )
    source_chunks: list[str] = Field(
        default_factory=list,
        description="All chunks where this term was found or enriched",
    )
    # Keep source_chunk as a computed property for backward compatibility
    source_chunk: str = Field(
        default="",
        description="Deprecated: use source_chunks. First chunk where term was found.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternative names for this term (e.g., abbreviations, full forms)",
    )
    related_terms: list[str] = Field(
        default_factory=list,
        description="Other terms related to this one",
    )


class Glossary(BaseModel):
    """Collection of term definitions."""

    entries: list[GlossaryEntry] = Field(default_factory=list)

    def get_entry(self, term: str) -> Optional[GlossaryEntry]:
        """Find entry by term or alias (case-insensitive)."""
        term_lower = term.lower()
        for entry in self.entries:
            if entry.term.lower() == term_lower:
                return entry
            if any(a.lower() == term_lower for a in entry.aliases):
                return entry
        return None

    def add_or_update(self, entry: GlossaryEntry) -> None:
        """Add new entry or update existing by term."""
        existing = self.get_entry(entry.term)
        if existing:
            # Merge definition: keep longer one (richer) rather than blindly overwriting
            if len(entry.definition) > len(existing.definition):
                existing.definition = entry.definition
            # Accumulate source chunks
            for sc in entry.source_chunks:
                if sc and sc not in existing.source_chunks:
                    existing.source_chunks.append(sc)
            # Backward compat: also check the deprecated source_chunk field
            if entry.source_chunk and entry.source_chunk not in existing.source_chunks:
                existing.source_chunks.append(entry.source_chunk)
            # Merge labels (deduplicate)
            for label in entry.labels:
                if label not in existing.labels:
                    existing.labels.append(label)
            # Merge related terms
            for rt in entry.related_terms:
                if rt not in existing.related_terms:
                    existing.related_terms.append(rt)
            # Merge aliases
            for alias in entry.aliases:
                if alias and alias.lower() != existing.term.lower():
                    if not any(a.lower() == alias.lower() for a in existing.aliases):
                        existing.aliases.append(alias)
        else:
            # Ensure source_chunks is populated from source_chunk for new entries
            if entry.source_chunk and entry.source_chunk not in entry.source_chunks:
                entry.source_chunks.append(entry.source_chunk)
            self.entries.append(entry)

    def get_terms_by_label(self, label: str) -> list[GlossaryEntry]:
        """Find all entries with a given label."""
        label_lower = label.lower()
        return [
            e for e in self.entries
            if any(l.lower() == label_lower for l in e.labels)
        ]
