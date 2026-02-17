"""Tests for LabelTree operations."""

from chunks2skus.schemas.sku import LabelTree


def test_add_path_creates_hierarchy():
    tree = LabelTree()
    tree.add_path(["Finance", "Risk", "Credit Risk"])

    assert len(tree.roots) == 1
    assert tree.roots[0].name == "Finance"
    assert len(tree.roots[0].children) == 1
    assert tree.roots[0].children[0].name == "Risk"
    assert tree.roots[0].children[0].children[0].name == "Credit Risk"


def test_add_path_merges_existing():
    """Adding overlapping paths doesn't create duplicates."""
    tree = LabelTree()
    tree.add_path(["Finance", "Risk", "Credit Risk"])
    tree.add_path(["Finance", "Risk", "Market Risk"])

    assert len(tree.roots) == 1
    risk_node = tree.roots[0].children[0]
    assert len(risk_node.children) == 2
    child_names = {c.name for c in risk_node.children}
    assert child_names == {"Credit Risk", "Market Risk"}


def test_add_path_case_insensitive():
    """Merging is case-insensitive."""
    tree = LabelTree()
    tree.add_path(["Finance", "Risk"])
    tree.add_path(["finance", "risk", "Credit Risk"])

    assert len(tree.roots) == 1  # Not 2
    assert len(tree.roots[0].children) == 1
    assert len(tree.roots[0].children[0].children) == 1


def test_get_all_paths_leaf_only():
    """get_all_paths returns only leaf paths."""
    tree = LabelTree()
    tree.add_path(["A", "B", "C"])
    tree.add_path(["A", "B", "D"])
    tree.add_path(["X", "Y"])

    paths = tree.get_all_paths()
    assert len(paths) == 3
    assert ["A", "B", "C"] in paths
    assert ["A", "B", "D"] in paths
    assert ["X", "Y"] in paths


def test_empty_tree():
    tree = LabelTree()
    assert tree.get_all_paths() == []


def test_add_empty_path():
    tree = LabelTree()
    tree.add_path([])
    assert len(tree.roots) == 0


def test_multiple_roots():
    tree = LabelTree()
    tree.add_path(["Finance"])
    tree.add_path(["Technology"])
    tree.add_path(["Legal"])

    assert len(tree.roots) == 3
    root_names = {r.name for r in tree.roots}
    assert root_names == {"Finance", "Technology", "Legal"}
