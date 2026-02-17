"""Tests for dedup action schema (C1, C2 fixes)."""

from chunks2skus.schemas.postprocessing import DedupAction, DedupReport


def test_dedup_action_rewrite_has_content_field():
    """DedupAction should carry new_content for rewrite actions."""
    action = DedupAction(
        sku_a="sku_001",
        sku_b="sku_002",
        action="rewrite",
        detail="Removing overlap between the two SKUs",
        rewritten_skus=["sku_001"],
        new_content="This is the rewritten content with overlap removed.",
    )
    assert action.new_content is not None
    assert "rewritten content" in action.new_content


def test_dedup_action_merge_has_content_field():
    """DedupAction should carry merged_content for merge actions."""
    action = DedupAction(
        sku_a="sku_001",
        sku_b="sku_002",
        action="merge",
        detail="Combining content from both SKUs",
        deleted_skus=["sku_002"],
        merged_content="Combined content from both SKUs.",
    )
    assert action.merged_content is not None
    assert action.deleted_skus == ["sku_002"]


def test_dedup_action_keep_no_content():
    """Keep action doesn't need content fields."""
    action = DedupAction(
        sku_a="sku_001",
        sku_b="sku_002",
        action="keep",
        detail="Both are distinct",
    )
    assert action.new_content is None
    assert action.merged_content is None


def test_dedup_action_contradiction():
    """Contradiction action type is valid."""
    action = DedupAction(
        sku_a="sku_001",
        sku_b="sku_002",
        action="contradiction",
        detail="SKUs state contradictory things about credit risk thresholds",
    )
    assert action.action == "contradiction"


def test_dedup_report_tracks_contradictions():
    """DedupReport should track contradictions separately."""
    report = DedupReport()
    report.total_contradictions = 2
    contradiction = DedupAction(
        sku_a="sku_001",
        sku_b="sku_002",
        action="contradiction",
        detail="Conflicting credit risk thresholds",
    )
    report.contradictions.append(contradiction)

    assert report.total_contradictions == 2
    assert len(report.contradictions) == 1
    assert report.contradictions[0].action == "contradiction"
