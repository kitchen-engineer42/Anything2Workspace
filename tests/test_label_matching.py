"""Tests for label assignment word-boundary matching (C3 fix)."""

from chunks2skus.postprocessors.bucketing import BucketingPostprocessor
from chunks2skus.schemas.postprocessing import BucketEntry
from chunks2skus.schemas.sku import LabelTree


def _make_entry(name: str, desc: str) -> BucketEntry:
    return BucketEntry(
        sku_id="test",
        name=name,
        description=desc,
        classification="factual",
        token_count=100,
    )


class TestWordBoundaryMatch:
    """Test the word-boundary matching used in label assignment."""

    def test_exact_word_matches(self):
        assert BucketingPostprocessor._word_boundary_match("risk", "credit risk management")

    def test_substring_does_not_match(self):
        """'risk' should NOT match 'asterisk'."""
        assert not BucketingPostprocessor._word_boundary_match("risk", "asterisk in text")

    def test_case_insensitive(self):
        assert BucketingPostprocessor._word_boundary_match("Risk", "credit risk management")

    def test_hyphenated_word(self):
        assert BucketingPostprocessor._word_boundary_match("credit", "credit-risk management")

    def test_start_of_string(self):
        assert BucketingPostprocessor._word_boundary_match("risk", "risk management")

    def test_end_of_string(self):
        assert BucketingPostprocessor._word_boundary_match("risk", "credit risk")

    def test_no_match(self):
        assert not BucketingPostprocessor._word_boundary_match("quantum", "credit risk")


class TestAssignLabels:
    """Test _assign_labels uses word-boundary matching properly."""

    def test_assign_labels_no_false_positives(self):
        """Ensure 'risk' label doesn't match 'asterisk' in description."""
        tree = LabelTree()
        tree.add_path(["Finance", "Risk"])

        entries = [
            _make_entry("asterisk-usage", "How to use asterisk in documents"),
        ]

        # Create a bucketing postprocessor with mocked dirs
        bp = object.__new__(BucketingPostprocessor)
        result = bp._assign_labels(entries, tree)

        # Should get empty path (no match) since 'risk' shouldn't match 'asterisk'
        assert result[0] == []

    def test_assign_labels_correct_match(self):
        """'risk' label should match 'credit risk management'."""
        tree = LabelTree()
        tree.add_path(["Finance", "Risk"])

        entries = [
            _make_entry("credit-risk-overview", "Overview of credit risk management"),
        ]

        bp = object.__new__(BucketingPostprocessor)
        result = bp._assign_labels(entries, tree)

        # Should match ["Finance", "Risk"] since "risk" is a whole word in the text
        assert len(result[0]) > 0
        assert "Risk" in result[0]
