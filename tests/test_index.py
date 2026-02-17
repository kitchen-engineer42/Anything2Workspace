"""Tests for SKUsIndex operations."""

from chunks2skus.schemas.index import SKUEntry, SKUsIndex
from chunks2skus.schemas.sku import SKUType


def _make_entry(sku_id: str, sku_type: SKUType = SKUType.FACTUAL) -> SKUEntry:
    return SKUEntry(
        sku_id=sku_id,
        name=f"Test {sku_id}",
        classification=sku_type,
        path=f"/output/skus/factual/{sku_id}",
        source_chunk="chunk_001",
        character_count=500,
        description=f"Test entry {sku_id}",
    )


def test_add_sku():
    """Adding an SKU updates counters correctly."""
    index = SKUsIndex()
    index.add_sku(_make_entry("sku_001"))

    assert index.total_skus == 1
    assert index.factual_count == 1
    assert index.total_characters == 500


def test_remove_sku():
    """Removing an SKU updates counters correctly."""
    index = SKUsIndex()
    index.add_sku(_make_entry("sku_001"))
    index.add_sku(_make_entry("sku_002"))

    removed = index.remove_sku("sku_001")
    assert removed is True
    assert index.total_skus == 1
    assert index.factual_count == 1
    assert index.total_characters == 500


def test_remove_nonexistent_sku():
    """Removing nonexistent SKU returns False."""
    index = SKUsIndex()
    assert index.remove_sku("nonexistent") is False


def test_mark_chunk_processed():
    """Chunk processing tracking works."""
    index = SKUsIndex()
    index.mark_chunk_processed("chunk_001")
    assert index.is_chunk_processed("chunk_001")
    assert not index.is_chunk_processed("chunk_002")


def test_mark_chunk_processed_no_duplicates():
    """Marking same chunk twice doesn't create duplicates."""
    index = SKUsIndex()
    index.mark_chunk_processed("chunk_001")
    index.mark_chunk_processed("chunk_001")
    assert len(index.chunks_processed) == 1


def test_get_skus_by_type():
    """Filtering by type works."""
    index = SKUsIndex()
    index.add_sku(_make_entry("sku_001", SKUType.FACTUAL))
    index.add_sku(_make_entry("skill_001", SKUType.PROCEDURAL))
    index.add_sku(_make_entry("sku_002", SKUType.FACTUAL))

    factuals = index.get_skus_by_type(SKUType.FACTUAL)
    assert len(factuals) == 2

    procedurals = index.get_skus_by_type(SKUType.PROCEDURAL)
    assert len(procedurals) == 1


def test_get_skus_by_source():
    """Filtering by source chunk works."""
    index = SKUsIndex()
    e1 = _make_entry("sku_001")
    e1.source_chunk = "chunk_001"
    e2 = _make_entry("sku_002")
    e2.source_chunk = "chunk_002"
    e3 = _make_entry("sku_003")
    e3.source_chunk = "chunk_001"
    index.add_sku(e1)
    index.add_sku(e2)
    index.add_sku(e3)

    results = index.get_skus_by_source("chunk_001")
    assert len(results) == 2


def test_type_counters_correct():
    """Per-type counters track adds and removes."""
    index = SKUsIndex()
    index.add_sku(_make_entry("sku_001", SKUType.FACTUAL))
    index.add_sku(_make_entry("skill_001", SKUType.PROCEDURAL))
    index.add_sku(_make_entry("sku_002", SKUType.FACTUAL))

    assert index.factual_count == 2
    assert index.procedural_count == 1

    index.remove_sku("sku_001")
    assert index.factual_count == 1
    assert index.procedural_count == 1
