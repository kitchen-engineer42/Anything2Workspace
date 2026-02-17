"""Tests for typed relationships schema (H3 fix)."""

from chunks2skus.schemas.sku import Relationship, Relationships, RelationType


def test_add_relationship():
    """Basic relationship addition."""
    rels = Relationships()
    rel = Relationship(
        subject="Credit Risk",
        predicate=RelationType.IS_A,
        object="Risk",
        source_chunks=["chunk_001"],
    )
    rels.add(rel)
    assert len(rels.entries) == 1


def test_dedup_by_subject_predicate_object():
    """Duplicate relationships are deduplicated, source_chunks merged."""
    rels = Relationships()
    r1 = Relationship(
        subject="Credit Risk",
        predicate=RelationType.IS_A,
        object="Risk",
        source_chunks=["chunk_001"],
    )
    r2 = Relationship(
        subject="Credit Risk",
        predicate=RelationType.IS_A,
        object="Risk",
        source_chunks=["chunk_005"],
    )
    rels.add(r1)
    rels.add(r2)

    assert len(rels.entries) == 1
    assert set(rels.entries[0].source_chunks) == {"chunk_001", "chunk_005"}


def test_different_predicates_not_deduped():
    """Same subject/object with different predicates are distinct."""
    rels = Relationships()
    r1 = Relationship(
        subject="A",
        predicate=RelationType.CAUSES,
        object="B",
        source_chunks=["c1"],
    )
    r2 = Relationship(
        subject="A",
        predicate=RelationType.RELATED_TO,
        object="B",
        source_chunks=["c1"],
    )
    rels.add(r1)
    rels.add(r2)

    assert len(rels.entries) == 2


def test_get_by_subject():
    rels = Relationships()
    rels.add(Relationship(subject="A", predicate=RelationType.CAUSES, object="B", source_chunks=["c1"]))
    rels.add(Relationship(subject="A", predicate=RelationType.ENABLES, object="C", source_chunks=["c1"]))
    rels.add(Relationship(subject="X", predicate=RelationType.CAUSES, object="Y", source_chunks=["c1"]))

    results = rels.get_by_subject("A")
    assert len(results) == 2


def test_get_by_object():
    rels = Relationships()
    rels.add(Relationship(subject="A", predicate=RelationType.CAUSES, object="B", source_chunks=["c1"]))
    rels.add(Relationship(subject="C", predicate=RelationType.ENABLES, object="B", source_chunks=["c1"]))

    results = rels.get_by_object("B")
    assert len(results) == 2


def test_get_by_type():
    rels = Relationships()
    rels.add(Relationship(subject="A", predicate=RelationType.CAUSES, object="B", source_chunks=["c1"]))
    rels.add(Relationship(subject="C", predicate=RelationType.IS_A, object="D", source_chunks=["c1"]))
    rels.add(Relationship(subject="E", predicate=RelationType.CAUSES, object="F", source_chunks=["c1"]))

    results = rels.get_by_type(RelationType.CAUSES)
    assert len(results) == 2


def test_case_insensitive_dedup():
    """Dedup is case-insensitive on subject and object."""
    rels = Relationships()
    r1 = Relationship(subject="credit risk", predicate=RelationType.IS_A, object="risk", source_chunks=["c1"])
    r2 = Relationship(subject="Credit Risk", predicate=RelationType.IS_A, object="Risk", source_chunks=["c2"])
    rels.add(r1)
    rels.add(r2)

    assert len(rels.entries) == 1
