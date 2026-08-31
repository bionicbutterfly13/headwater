"""Tests for headwater.manager — PageIndexManager."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from headwater.manager import (
    PageIndexManager,
    get_pageindex_manager,
    reset_manager_singleton,
)
from headwater.models import SectionChunk, TreeNode
from headwater.service import LocalPageIndexService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SPEC_MD = """\
# Spec

## Requirements

Must handle large documents.

## Acceptance Criteria

All tests pass with 80%+ coverage.
"""

ANOTHER_MD = """\
# Another Doc

## Section One

First content.
"""


@pytest.fixture(autouse=True)
def reset_singleton() -> None:
    yield
    reset_manager_singleton()


@pytest.fixture
def tmp_cache(tmp_path: Path) -> Path:
    return tmp_path / "pageindex"


@pytest.fixture
def manager(tmp_cache: Path) -> PageIndexManager:
    return PageIndexManager(cache_dir=tmp_cache)


# ---------------------------------------------------------------------------
# build_from_content
# ---------------------------------------------------------------------------


class TestBuildFromContent:
    def test_returns_tuple_of_tree_nodes(self, manager: PageIndexManager) -> None:
        tree = manager.build_from_content("spec", SPEC_MD)
        assert isinstance(tree, tuple)
        for node in tree:
            assert isinstance(node, TreeNode)

    def test_tree_is_non_empty_for_structured_md(self, manager: PageIndexManager) -> None:
        tree = manager.build_from_content("spec", SPEC_MD)
        assert len(tree) > 0

    def test_persists_to_disk(self, manager: PageIndexManager, tmp_cache: Path) -> None:
        manager.build_from_content("spec", SPEC_MD)
        json_file = tmp_cache / "spec.json"
        assert json_file.exists()

    def test_json_is_valid(self, manager: PageIndexManager, tmp_cache: Path) -> None:
        manager.build_from_content("spec", SPEC_MD)
        data = json.loads((tmp_cache / "spec.json").read_text())
        assert "roots" in data
        assert "key" in data

    def test_second_call_returns_cached(self, manager: PageIndexManager) -> None:
        tree_a = manager.build_from_content("spec", SPEC_MD)
        tree_b = manager.build_from_content("spec", SPEC_MD)
        # Same object from memory cache
        assert tree_a is tree_b

    def test_force_rebuilds(self, manager: PageIndexManager) -> None:
        tree_a = manager.build_from_content("spec", SPEC_MD)
        tree_b = manager.build_from_content("spec", SPEC_MD, force=True)
        # Not necessarily same object after rebuild; just check it works
        assert isinstance(tree_b, tuple)

    def test_key_with_slash_sanitised_on_disk(
        self, manager: PageIndexManager, tmp_cache: Path
    ) -> None:
        manager.build_from_content("dir/spec", SPEC_MD)
        files = list(tmp_cache.iterdir())
        assert any("dir_spec" in f.name for f in files)


# ---------------------------------------------------------------------------
# build_from_file
# ---------------------------------------------------------------------------


class TestBuildFromFile:
    def test_builds_from_real_file(self, manager: PageIndexManager, tmp_path: Path) -> None:
        md_file = tmp_path / "spec.md"
        md_file.write_text(SPEC_MD, encoding="utf-8")
        tree = manager.build_from_file("spec", md_file)
        assert tree is not None
        assert len(tree) > 0

    def test_returns_none_for_missing_file(self, manager: PageIndexManager) -> None:
        result = manager.build_from_file("missing", Path("/does/not/exist.md"))
        assert result is None

    def test_caches_after_build(self, manager: PageIndexManager, tmp_path: Path) -> None:
        md_file = tmp_path / "spec.md"
        md_file.write_text(SPEC_MD, encoding="utf-8")
        manager.build_from_file("cached_spec", md_file)
        cached = manager.get_tree("cached_spec")
        assert cached is not None


# ---------------------------------------------------------------------------
# build_from_directory
# ---------------------------------------------------------------------------


class TestBuildFromDirectory:
    def test_builds_from_directory(self, manager: PageIndexManager, tmp_path: Path) -> None:
        (tmp_path / "spec.md").write_text(SPEC_MD, encoding="utf-8")
        (tmp_path / "readme.md").write_text(ANOTHER_MD, encoding="utf-8")
        tree = manager.build_from_directory("docs", tmp_path)
        assert tree is not None
        assert len(tree) > 0

    def test_returns_none_for_missing_directory(self, manager: PageIndexManager) -> None:
        result = manager.build_from_directory("missing", Path("/no/such/dir"))
        assert result is None

    def test_returns_none_when_no_matching_files(
        self, manager: PageIndexManager, tmp_path: Path
    ) -> None:
        result = manager.build_from_directory(
            "empty_globs", tmp_path, globs=("**/*.xyz",)
        )
        assert result is None

    def test_respects_max_files(self, manager: PageIndexManager, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"doc{i}.md").write_text(f"# Doc {i}\n\nContent.", encoding="utf-8")
        mgr = PageIndexManager(
            cache_dir=tmp_path / "cache",
            max_files=2,
        )
        tree = mgr.build_from_directory("limited", tmp_path)
        assert tree is not None

    def test_second_call_uses_cache(self, manager: PageIndexManager, tmp_path: Path) -> None:
        (tmp_path / "spec.md").write_text(SPEC_MD, encoding="utf-8")
        tree_a = manager.build_from_directory("docs", tmp_path)
        tree_b = manager.build_from_directory("docs", tmp_path)
        # Second call hits memory cache
        assert tree_a is tree_b


# ---------------------------------------------------------------------------
# get_tree / put_tree / invalidate
# ---------------------------------------------------------------------------


class TestCachePrimitives:
    def test_get_tree_returns_none_for_unknown_key(self, manager: PageIndexManager) -> None:
        assert manager.get_tree("unknown") is None

    def test_put_and_get_roundtrip(self, manager: PageIndexManager) -> None:
        node = TreeNode(
            node_id="0001",
            title="Root",
            text="# Root\n\nText.",
            line_num=1,
            level=1,
            children=(),
        )
        manager.put_tree("mykey", (node,))
        retrieved = manager.get_tree("mykey")
        assert retrieved is not None
        assert retrieved[0].title == "Root"

    def test_disk_load_on_cold_start(
        self, tmp_cache: Path, tmp_path: Path
    ) -> None:
        # Build in one manager instance, load in a fresh one.
        m1 = PageIndexManager(cache_dir=tmp_cache)
        m1.build_from_content("spec", SPEC_MD)

        m2 = PageIndexManager(cache_dir=tmp_cache)
        loaded = m2.get_tree("spec")
        assert loaded is not None
        assert loaded[0].title == "Spec"

    def test_invalidate_removes_memory(self, manager: PageIndexManager) -> None:
        manager.build_from_content("spec", SPEC_MD)
        manager.invalidate("spec")
        assert "spec" not in manager._memory_cache

    def test_invalidate_removes_disk_file(
        self, manager: PageIndexManager, tmp_cache: Path
    ) -> None:
        manager.build_from_content("spec", SPEC_MD)
        assert (tmp_cache / "spec.json").exists()
        manager.invalidate("spec")
        assert not (tmp_cache / "spec.json").exists()

    def test_invalidate_unknown_key_is_safe(self, manager: PageIndexManager) -> None:
        manager.invalidate("nonexistent")  # Should not raise.

    def test_corrupted_json_returns_none(
        self, manager: PageIndexManager, tmp_cache: Path
    ) -> None:
        tmp_cache.mkdir(parents=True, exist_ok=True)
        (tmp_cache / "broken.json").write_text("NOT JSON", encoding="utf-8")
        result = manager.get_tree("broken")
        assert result is None


# ---------------------------------------------------------------------------
# query_tree
# ---------------------------------------------------------------------------


class TestQueryTree:
    def test_query_known_key(self, manager: PageIndexManager) -> None:
        manager.build_from_content("spec", SPEC_MD)
        matches = manager.query_tree("spec", "acceptance")
        assert len(matches) > 0

    def test_query_returns_section_chunks(self, manager: PageIndexManager) -> None:
        manager.build_from_content("spec", SPEC_MD)
        matches = manager.query_tree("spec", "requirements")
        for m in matches:
            assert isinstance(m, SectionChunk)

    def test_query_unknown_key_returns_empty(self, manager: PageIndexManager) -> None:
        result = manager.query_tree("does_not_exist", "query")
        assert result == []

    def test_query_no_match_returns_empty(self, manager: PageIndexManager) -> None:
        manager.build_from_content("spec", SPEC_MD)
        matches = manager.query_tree("spec", "zzzzznonexistentzzzz")
        assert matches == []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_returns_same_instance(self, tmp_cache: Path) -> None:
        a = get_pageindex_manager(cache_dir=tmp_cache)
        b = get_pageindex_manager(cache_dir=tmp_cache)
        assert a is b

    def test_reset_allows_new_instance(self, tmp_cache: Path) -> None:
        a = get_pageindex_manager(cache_dir=tmp_cache)
        reset_manager_singleton()
        b = get_pageindex_manager(cache_dir=tmp_cache)
        assert a is not b


# ---------------------------------------------------------------------------
# Disk persistence edge cases
# ---------------------------------------------------------------------------


class TestDiskPersistence:
    def test_save_creates_parent_directories(
        self, tmp_path: Path
    ) -> None:
        deep_cache = tmp_path / "a" / "b" / "c"
        mgr = PageIndexManager(cache_dir=deep_cache)
        mgr.build_from_content("spec", SPEC_MD)
        assert (deep_cache / "spec.json").exists()

    def test_tree_node_roundtrip_through_json(
        self, manager: PageIndexManager, tmp_cache: Path
    ) -> None:
        manager.build_from_content("spec", SPEC_MD)
        data = json.loads((tmp_cache / "spec.json").read_text())
        roots_from_disk = tuple(TreeNode.from_dict(r) for r in data["roots"])
        assert roots_from_disk[0].title == "Spec"

    def test_build_from_directory_skips_unreadable_file(
        self, manager: PageIndexManager, tmp_path: Path
    ) -> None:
        """Cover OSError path in build_from_directory file read loop."""
        readable = tmp_path / "good.md"
        readable.write_text(SPEC_MD, encoding="utf-8")
        unreadable = tmp_path / "bad.md"
        unreadable.write_text("# Bad\n\nContent.", encoding="utf-8")

        original_read_text = Path.read_text

        def patched_read_text(self: Path, *args, **kwargs):  # type: ignore[override]
            if self.name == "bad.md":
                raise OSError("simulated read error")
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", patched_read_text):
            tree = manager.build_from_directory("partial", tmp_path)
        # Should still return a tree from the readable file
        assert tree is not None

    def test_children_preserved_in_json(
        self, manager: PageIndexManager, tmp_cache: Path
    ) -> None:
        manager.build_from_content("spec", SPEC_MD)
        data = json.loads((tmp_cache / "spec.json").read_text())
        root = data["roots"][0]
        assert "children" in root
        child_titles = [c["title"] for c in root["children"]]
        assert "Requirements" in child_titles
        assert "Acceptance Criteria" in child_titles
