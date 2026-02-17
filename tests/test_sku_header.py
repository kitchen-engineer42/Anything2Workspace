"""Tests for SKUHeader schema (H5 fix — related_skus)."""

from chunks2skus.schemas.sku import SKUHeader, SKUType


def test_header_to_markdown_basic():
    """Basic header renders correctly."""
    header = SKUHeader(
        name="credit-risk-overview",
        classification=SKUType.FACTUAL,
        character_count=1500,
        source_chunk="chunk_003",
        description="Overview of credit risk framework",
    )
    md = header.to_markdown()
    assert "# credit-risk-overview" in md
    assert "factual" in md
    assert "chunk_003" in md
    assert "1,500" in md


def test_header_with_confidence():
    """Confidence score appears in markdown output."""
    header = SKUHeader(
        name="test",
        classification=SKUType.FACTUAL,
        character_count=100,
        source_chunk="chunk_001",
        description="Test",
        confidence=0.85,
    )
    md = header.to_markdown()
    assert "0.85" in md
    assert "Confidence" in md


def test_header_with_related_skus():
    """Related SKUs appear in markdown output."""
    header = SKUHeader(
        name="test",
        classification=SKUType.FACTUAL,
        character_count=100,
        source_chunk="chunk_001",
        description="Test",
        related_skus=["sku_010", "sku_025", "skill_003"],
    )
    md = header.to_markdown()
    assert "Related SKUs" in md
    assert "sku_010" in md
    assert "sku_025" in md
    assert "skill_003" in md


def test_header_no_related_skus_no_line():
    """When related_skus is empty, no 'Related SKUs' line appears."""
    header = SKUHeader(
        name="test",
        classification=SKUType.FACTUAL,
        character_count=100,
        source_chunk="chunk_001",
        description="Test",
    )
    md = header.to_markdown()
    assert "Related SKUs" not in md
