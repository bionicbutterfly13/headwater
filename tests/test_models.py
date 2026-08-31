"""Tests for headwater.models — TreeNode and SectionChunk."""

from __future__ import annotations

import pytest

from headwater.models import SectionChunk, TreeNode


# ---------------------------------------------------------------------------
# TreeNode
# ---------------------------------------------------------------------------


class TestTreeNode:
    def test_frozen(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="Root",
            text="# Root",
            line_num=1,
            level=1,
        )
        with pytest.raises((AttributeError, TypeError)):
            node.title = "mutated"  # type: ignore[misc]

    def test_is_leaf_true_when_no_children(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="Leaf",
            text="text",
            line_num=1,
            level=1,
        )
        assert node.is_leaf()

    def test_is_leaf_false_when_has_children(self) -> None:
        child = TreeNode(
            node_id="0002",
            title="Child",
            text="child text",
            line_num=3,
            level=2,
        )
        parent = TreeNode(
            node_id="0001",
            title="Parent",
            text="parent text",
            line_num=1,
            level=1,
            children=(child,),
        )
        assert not parent.is_leaf()

    def test_to_dict_no_children(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="Root",
            text="# Root\n\nBody.",
            line_num=1,
            level=1,
        )
        d = node.to_dict()
        assert d["node_id"] == "0001"
        assert d["title"] == "Root"
        assert "children" not in d

    def test_to_dict_with_children(self) -> None:
        child = TreeNode(
            node_id="0002",
            title="Child",
            text="child",
            line_num=3,
            level=2,
        )
        parent = TreeNode(
            node_id="0001",
            title="Parent",
            text="parent",
            line_num=1,
            level=1,
            children=(child,),
        )
        d = parent.to_dict()
        assert "children" in d
        assert d["children"][0]["title"] == "Child"

    def test_from_dict_roundtrip_leaf(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="Root",
            text="# Root\n\nBody.",
            line_num=1,
            level=1,
        )
        restored = TreeNode.from_dict(node.to_dict())
        assert restored == node

    def test_from_dict_roundtrip_with_children(self) -> None:
        child = TreeNode(
            node_id="0002",
            title="Child",
            text="child",
            line_num=3,
            level=2,
        )
        parent = TreeNode(
            node_id="0001",
            title="Parent",
            text="parent",
            line_num=1,
            level=1,
            children=(child,),
        )
        restored = TreeNode.from_dict(parent.to_dict())
        assert restored == parent
        assert restored.children[0].title == "Child"

    def test_default_children_empty_tuple(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="X",
            text="x",
            line_num=1,
            level=1,
        )
        assert node.children == ()


# ---------------------------------------------------------------------------
# SectionChunk
# ---------------------------------------------------------------------------


class TestSectionChunk:
    def test_frozen(self) -> None:
        chunk = SectionChunk(
            node_id="0001",
            title="Title",
            text="text",
            path=("Root", "Title"),
        )
        with pytest.raises((AttributeError, TypeError)):
            chunk.title = "mutated"  # type: ignore[misc]

    def test_path_string_default_separator(self) -> None:
        chunk = SectionChunk(
            node_id="0001",
            title="Database",
            text="content",
            path=("Architecture", "Database"),
        )
        assert chunk.path_string() == "Architecture > Database"

    def test_path_string_custom_separator(self) -> None:
        chunk = SectionChunk(
            node_id="0001",
            title="DB",
            text="content",
            path=("A", "B", "C"),
        )
        assert chunk.path_string(" / ") == "A / B / C"

    def test_path_string_single_item(self) -> None:
        chunk = SectionChunk(
            node_id="0001",
            title="Root",
            text="text",
            path=("Root",),
        )
        assert chunk.path_string() == "Root"

    def test_to_dict(self) -> None:
        chunk = SectionChunk(
            node_id="0001",
            title="Title",
            text="body",
            path=("A", "B"),
        )
        d = chunk.to_dict()
        assert d["node_id"] == "0001"
        assert d["title"] == "Title"
        assert d["text"] == "body"
        assert d["path"] == ["A", "B"]

    def test_from_dict_roundtrip(self) -> None:
        chunk = SectionChunk(
            node_id="0002",
            title="Section",
            text="some text",
            path=("Root", "Section"),
        )
        restored = SectionChunk.from_dict(chunk.to_dict())
        assert restored == chunk

    def test_path_is_tuple(self) -> None:
        chunk = SectionChunk(
            node_id="0001",
            title="X",
            text="x",
            path=("A", "B"),
        )
        assert isinstance(chunk.path, tuple)
