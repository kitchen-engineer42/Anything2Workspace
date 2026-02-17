"""Tests for Glossary schema: merging, provenance, aliases."""

from chunks2skus.schemas.sku import Glossary, GlossaryEntry


def test_add_new_entry():
    """New entries are added to the glossary."""
    g = Glossary()
    entry = GlossaryEntry(
        term="Credit Risk",
        definition="Risk of loss from borrower default",
        source_chunk="chunk_001",
    )
    g.add_or_update(entry)
    assert len(g.entries) == 1
    assert g.entries[0].term == "Credit Risk"


def test_update_accumulates_source_chunks():
    """Updating a term accumulates source_chunks rather than overwriting."""
    g = Glossary()
    e1 = GlossaryEntry(
        term="Credit Risk",
        definition="Risk of loss",
        source_chunk="chunk_001",
    )
    g.add_or_update(e1)

    e2 = GlossaryEntry(
        term="Credit Risk",
        definition="Risk of loss from borrower default or deterioration",
        source_chunk="chunk_005",
    )
    g.add_or_update(e2)

    assert len(g.entries) == 1
    result = g.entries[0]
    assert "chunk_001" in result.source_chunks
    assert "chunk_005" in result.source_chunks
    assert len(result.source_chunks) == 2


def test_update_keeps_longer_definition():
    """On update, the longer (richer) definition wins."""
    g = Glossary()
    e1 = GlossaryEntry(
        term="G-SIB",
        definition="A very long and detailed definition of global systemically important banks",
        source_chunk="chunk_001",
    )
    g.add_or_update(e1)

    # Shorter definition should NOT overwrite
    e2 = GlossaryEntry(
        term="G-SIB",
        definition="Important banks",
        source_chunk="chunk_002",
    )
    g.add_or_update(e2)

    assert "very long and detailed" in g.entries[0].definition


def test_update_replaces_with_longer_definition():
    """On update, a longer new definition replaces the shorter old one."""
    g = Glossary()
    e1 = GlossaryEntry(
        term="G-SIB",
        definition="Important banks",
        source_chunk="chunk_001",
    )
    g.add_or_update(e1)

    e2 = GlossaryEntry(
        term="G-SIB",
        definition="A very long and detailed definition of global systemically important banks",
        source_chunk="chunk_002",
    )
    g.add_or_update(e2)

    assert "very long and detailed" in g.entries[0].definition


def test_alias_matching():
    """get_entry matches by alias as well as term."""
    g = Glossary()
    entry = GlossaryEntry(
        term="Global Systemically Important Banks",
        definition="Banks designated as systemically important",
        source_chunk="chunk_001",
        aliases=["G-SIB", "GSIB"],
    )
    g.add_or_update(entry)

    # Should find by canonical name
    assert g.get_entry("Global Systemically Important Banks") is not None
    # Should find by alias
    assert g.get_entry("G-SIB") is not None
    assert g.get_entry("gsib") is not None
    # Should NOT find unrelated term
    assert g.get_entry("Credit Risk") is None


def test_alias_merge_on_update():
    """Updating a term merges aliases."""
    g = Glossary()
    e1 = GlossaryEntry(
        term="G-SIB",
        definition="Important banks",
        source_chunk="chunk_001",
        aliases=["GSIB"],
    )
    g.add_or_update(e1)

    e2 = GlossaryEntry(
        term="G-SIB",
        definition="Important banks",
        source_chunk="chunk_002",
        aliases=["Global Systemically Important Banks"],
    )
    g.add_or_update(e2)

    assert len(g.entries) == 1
    assert "GSIB" in g.entries[0].aliases
    assert "Global Systemically Important Banks" in g.entries[0].aliases


def test_related_terms_merge():
    """Related terms are merged without duplicates."""
    g = Glossary()
    e1 = GlossaryEntry(
        term="Risk",
        definition="Chance of loss",
        source_chunk="chunk_001",
        related_terms=["Credit Risk", "Market Risk"],
    )
    g.add_or_update(e1)

    e2 = GlossaryEntry(
        term="Risk",
        definition="Chance of loss",
        source_chunk="chunk_002",
        related_terms=["Market Risk", "Operational Risk"],
    )
    g.add_or_update(e2)

    assert len(g.entries) == 1
    assert set(g.entries[0].related_terms) == {"Credit Risk", "Market Risk", "Operational Risk"}


def test_labels_merge():
    """Labels are merged without duplicates."""
    g = Glossary()
    e1 = GlossaryEntry(
        term="Risk",
        definition="Chance of loss",
        source_chunk="chunk_001",
        labels=["Finance"],
    )
    g.add_or_update(e1)

    e2 = GlossaryEntry(
        term="Risk",
        definition="Chance of loss",
        source_chunk="chunk_002",
        labels=["Finance", "Banking"],
    )
    g.add_or_update(e2)

    assert set(g.entries[0].labels) == {"Finance", "Banking"}


def test_get_terms_by_label():
    """get_terms_by_label filters correctly."""
    g = Glossary()
    g.add_or_update(GlossaryEntry(
        term="A", definition="def A", source_chunk="c1", labels=["Finance"]
    ))
    g.add_or_update(GlossaryEntry(
        term="B", definition="def B", source_chunk="c1", labels=["Technology"]
    ))
    g.add_or_update(GlossaryEntry(
        term="C", definition="def C", source_chunk="c1", labels=["Finance", "Technology"]
    ))

    finance_terms = g.get_terms_by_label("Finance")
    assert len(finance_terms) == 2
    assert {e.term for e in finance_terms} == {"A", "C"}
