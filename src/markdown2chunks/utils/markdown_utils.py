"""Markdown parsing utilities for header-based chunking."""

import re
from dataclasses import dataclass

import structlog

from .token_estimator import estimate_tokens

logger = structlog.get_logger(__name__)


@dataclass
class MarkdownSection:
    """A section of markdown content with its header info."""

    level: int  # Header level (1-6), 0 for content without header
    title: str  # Header text (empty if level=0)
    content: str  # Full content including header
    start_pos: int  # Character position in original text
    end_pos: int  # End position (exclusive)
    token_count: int  # Estimated tokens

    @property
    def is_header_section(self) -> bool:
        """Check if this section has a header."""
        return self.level > 0


def parse_headers(text: str) -> list[MarkdownSection]:
    """
    Parse markdown text into sections based on headers.

    Args:
        text: Full markdown text

    Returns:
        List of MarkdownSection objects
    """
    if not text.strip():
        return []

    # Pattern to match markdown headers (# to ######)
    header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    sections = []
    matches = list(header_pattern.finditer(text))

    if not matches:
        # No headers found - return entire text as one section
        return [
            MarkdownSection(
                level=0,
                title="",
                content=text,
                start_pos=0,
                end_pos=len(text),
                token_count=estimate_tokens(text),
            )
        ]

    # Handle content before first header (if any)
    if matches[0].start() > 0:
        pre_content = text[: matches[0].start()]
        if pre_content.strip():
            sections.append(
                MarkdownSection(
                    level=0,
                    title="",
                    content=pre_content,
                    start_pos=0,
                    end_pos=matches[0].start(),
                    token_count=estimate_tokens(pre_content),
                )
            )

    # Process each header and its content
    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        start_pos = match.start()

        # End is either next header or end of text
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            end_pos = len(text)

        content = text[start_pos:end_pos]

        sections.append(
            MarkdownSection(
                level=level,
                title=title,
                content=content,
                start_pos=start_pos,
                end_pos=end_pos,
                token_count=estimate_tokens(content),
            )
        )

    logger.debug("Parsed markdown sections", count=len(sections))
    return sections


def extract_section(text: str, start: int, end: int) -> str:
    """
    Extract a section of text with clean boundaries.

    Args:
        text: Full text
        start: Start character position
        end: End character position

    Returns:
        Extracted text with trimmed whitespace
    """
    return text[start:end].strip()


def build_section_tree(sections: list[MarkdownSection]) -> list[dict]:
    """
    Build a hierarchical tree from flat section list.

    Args:
        sections: List of MarkdownSection objects

    Returns:
        List of tree nodes with 'section' and 'children' keys
    """
    if not sections:
        return []

    tree = []
    stack = []  # Stack of (level, node) for tracking hierarchy

    for section in sections:
        node = {"section": section, "children": []}

        if section.level == 0:
            # Non-header content goes at root
            tree.append(node)
            continue

        # Pop stack until we find a parent with lower level
        while stack and stack[-1][0] >= section.level:
            stack.pop()

        if stack:
            # Add as child of parent
            stack[-1][1]["children"].append(node)
        else:
            # Root level header
            tree.append(node)

        stack.append((section.level, node))

    return tree


def get_section_with_children(
    node: dict, max_tokens: int
) -> tuple[str, int, list[MarkdownSection]]:
    """
    Get a section's content including children if within token limit.

    Args:
        node: Tree node from build_section_tree
        max_tokens: Maximum tokens allowed

    Returns:
        Tuple of (combined content, total tokens, list of included sections)
    """
    section = node["section"]
    children = node.get("children", [])

    # Start with just this section's content
    combined = section.content
    total_tokens = section.token_count
    included = [section]

    # Try to include children
    for child_node in children:
        child_content, child_tokens, child_sections = get_section_with_children(
            child_node, max_tokens - total_tokens
        )

        if total_tokens + child_tokens <= max_tokens:
            # Can include this child (content already included in parent)
            total_tokens += child_tokens
            included.extend(child_sections)
        else:
            # Cannot include - stop here
            break

    return combined, total_tokens, included
