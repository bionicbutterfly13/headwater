"""Tests for d4_pageindex.indexer — VaultPageIndexer."""

from __future__ import annotations

import pytest

from d4_pageindex.indexer import VaultPageIndexer, _extract_raw_nodes, _build_tree
from d4_pageindex.models import SectionChunk, TreeNode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_MD = """\
# Title

Intro paragraph.

## Section A

Content of A.

## Section B

Content of B.

### Section B1

Leaf content.
"""

FLAT_MD = """\
No headers here.
Just plain text.
"""

CODE_BLOCK_MD = """\
# Real Header

```python
# Not a header
## Also not a header
```

## After Code Block

Real section.
"""

DEEP_NESTING_MD = """\
# Level 1

## Level 2

### Level 3

#### Level 4

Deep content.
"""

EMPTY_MD = ""

MULTI_ROOT_MD = """\
# Root One

Content one.

# Root Two

Content two.
"""


@pytest.fixture
def indexer() -> VaultPageIndexer:
    return VaultPageIndexer()


# ---------------------------------------------------------------------------
# build_tree
# ---------------------------------------------------------------------------


class TestBuildTree:
    def test_empty_document_returns_empty_tuple(self, indexer: VaultPageIndexer) -> None:
        result = indexer.build_tree(EMPTY_MD)
        assert result == ()

    def test_flat_document_no_headers_returns_empty_tuple(self, indexer: VaultPageIndexer) -> None:
        result = indexer.build_tree(FLAT_MD)
        assert result == ()

    def test_simple_document_has_correct_root_count(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        assert len(roots) == 1
        assert roots[0].title == "Title"

    def test_root_has_two_children(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        assert len(roots[0].children) == 2

    def test_children_titles(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        titles = [c.title for c in roots[0].children]
        assert titles == ["Section A", "Section B"]

    def test_leaf_detection(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        section_a = roots[0].children[0]
        assert section_a.is_leaf()

    def test_parent_not_leaf(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        section_b = roots[0].children[1]
        assert not section_b.is_leaf()

    def test_section_b1_is_leaf(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        section_b1 = roots[0].children[1].children[0]
        assert section_b1.title == "Section B1"
        assert section_b1.is_leaf()

    def test_node_id_sequential(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        # Root is 0001
        assert roots[0].node_id == "0001"
        # Section A is 0002
        assert roots[0].children[0].node_id == "0002"

    def test_node_id_zero_padded(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        assert roots[0].node_id == "0001"

    def test_level_attribute(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        assert roots[0].level == 1
        assert roots[0].children[0].level == 2

    def test_line_num_is_one_based(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        # "# Title" is on line 1
        assert roots[0].line_num == 1

    def test_code_block_headers_not_parsed(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(CODE_BLOCK_MD)
        assert len(roots) == 1
        assert roots[0].title == "Real Header"
        assert len(roots[0].children) == 1
        assert roots[0].children[0].title == "After Code Block"

    def test_deep_nesting(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(DEEP_NESTING_MD)
        assert len(roots) == 1
        l2 = roots[0].children[0]
        l3 = l2.children[0]
        l4 = l3.children[0]
        assert l4.title == "Level 4"
        assert l4.is_leaf()

    def test_multi_root_document(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(MULTI_ROOT_MD)
        assert len(roots) == 2
        assert roots[0].title == "Root One"
        assert roots[1].title == "Root Two"

    def test_tree_nodes_are_frozen(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        with pytest.raises((AttributeError, TypeError)):
            roots[0].title = "mutated"  # type: ignore[misc]

    def test_text_contains_section_content(self, indexer: VaultPageIndexer) -> None:
        roots = indexer.build_tree(SIMPLE_MD)
        section_a = roots[0].children[0]
        assert "Content of A." in section_a.text


# ---------------------------------------------------------------------------
# chunk_for_extraction
# ---------------------------------------------------------------------------


class TestChunkForExtraction:
    def test_flat_document_returns_single_chunk(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(FLAT_MD)
        assert len(chunks) == 1
        assert chunks[0].title == "(untitled)"
        assert chunks[0].node_id == "0001"

    def test_flat_document_path_is_untitled(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(FLAT_MD)
        assert chunks[0].path == ("(untitled)",)

    def test_empty_document_returns_single_chunk(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(EMPTY_MD)
        assert len(chunks) == 1

    def test_structured_document_chunk_count(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(SIMPLE_MD)
        # Section A leaf, Section B1 leaf; Section B has intro text but
        # only if it has content before its first child.  Section B body
        # does have "Content of B." so an intro chunk is emitted too.
        titles = [c.title for c in chunks]
        assert "Section A" in titles
        assert "Section B1" in titles

    def test_chunk_path_breadcrumb(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(SIMPLE_MD)
        b1_chunks = [c for c in chunks if c.title == "Section B1"]
        assert len(b1_chunks) == 1
        assert b1_chunks[0].path == ("Title", "Section B", "Section B1")

    def test_max_chars_truncates_text(self, indexer: VaultPageIndexer) -> None:
        long_md = "# Section\n\n" + "x" * 1000
        chunks = indexer.chunk_for_extraction(long_md, max_chars=100)
        assert len(chunks[0].text) <= 100

    def test_chunk_is_frozen(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(FLAT_MD)
        with pytest.raises((AttributeError, TypeError)):
            chunks[0].title = "mutated"  # type: ignore[misc]

    def test_chunk_path_string(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(SIMPLE_MD)
        b1_chunks = [c for c in chunks if c.title == "Section B1"]
        assert b1_chunks[0].path_string() == "Title > Section B > Section B1"

    def test_multi_root_chunks_have_correct_paths(self, indexer: VaultPageIndexer) -> None:
        chunks = indexer.chunk_for_extraction(MULTI_ROOT_MD)
        paths = [c.path for c in chunks]
        assert ("Root One",) in paths
        assert ("Root Two",) in paths

    def test_intro_chunk_suffix(self, indexer: VaultPageIndexer) -> None:
        md = """\
# Parent

Intro text here, enough to pass the 20 char threshold.

## Child

Child content.
"""
        chunks = indexer.chunk_for_extraction(md)
        titles = [c.title for c in chunks]
        assert "Parent (intro)" in titles

    def test_intro_not_emitted_when_body_too_short(self, indexer: VaultPageIndexer) -> None:
        md = """\
# Parent

## Child

Child content.
"""
        chunks = indexer.chunk_for_extraction(md)
        titles = [c.title for c in chunks]
        assert "Parent (intro)" not in titles


# ---------------------------------------------------------------------------
# merge_extraction_results
# ---------------------------------------------------------------------------


class TestMergeExtractionResults:
    def test_empty_input(self, indexer: VaultPageIndexer) -> None:
        result = indexer.merge_extraction_results([])
        assert result == {"entities": [], "relationships": [], "facts": []}

    def test_entity_deduplication(self, indexer: VaultPageIndexer) -> None:
        results = [
            {"entities": [{"name": "Alice", "type": "person"}], "relationships": [], "facts": []},
            {"entities": [{"name": "alice", "type": "person"}], "relationships": [], "facts": []},
        ]
        merged = indexer.merge_extraction_results(results)
        assert len(merged["entities"]) == 1

    def test_relationship_deduplication(self, indexer: VaultPageIndexer) -> None:
        rel = {"source": "Alice", "target": "Bob", "type": "knows"}
        results = [
            {"entities": [], "relationships": [rel], "facts": []},
            {"entities": [], "relationships": [rel], "facts": []},
        ]
        merged = indexer.merge_extraction_results(results)
        assert len(merged["relationships"]) == 1

    def test_facts_are_combined(self, indexer: VaultPageIndexer) -> None:
        results = [
            {"entities": [], "relationships": [], "facts": ["fact1"]},
            {"entities": [], "relationships": [], "facts": ["fact2"]},
        ]
        merged = indexer.merge_extraction_results(results)
        assert len(merged["facts"]) == 2

    def test_missing_keys_tolerated(self, indexer: VaultPageIndexer) -> None:
        results = [{}]
        merged = indexer.merge_extraction_results(results)
        assert merged["entities"] == []


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class TestGetIntroText:
    """Cover _get_intro_text break path (child header stops scanning)."""

    def test_intro_text_stops_at_child_header(self, indexer: VaultPageIndexer) -> None:
        md = """\
# Parent

This is the intro paragraph that is long enough to pass the threshold.

## Child Section

Child content lives here.
"""
        chunks = indexer.chunk_for_extraction(md)
        intro_chunks = [c for c in chunks if "(intro)" in c.title]
        assert len(intro_chunks) == 1
        # The intro text should NOT contain the child header
        assert "## Child Section" not in intro_chunks[0].text


class TestExtractRawNodes:
    def test_returns_empty_for_flat_content(self) -> None:
        assert _extract_raw_nodes(FLAT_MD) == []

    def test_returns_headers_with_levels(self) -> None:
        nodes = _extract_raw_nodes(SIMPLE_MD)
        levels = [n["level"] for n in nodes]
        assert levels == [1, 2, 2, 3]

    def test_code_block_skipped(self) -> None:
        nodes = _extract_raw_nodes(CODE_BLOCK_MD)
        titles = [n["title"] for n in nodes]
        assert "Not a header" not in titles
        assert "Also not a header" not in titles
        assert "Real Header" in titles
        assert "After Code Block" in titles


class TestBuildTreeHelper:
    def test_empty_input_returns_empty_tuple(self) -> None:
        result = _build_tree([])
        assert result == ()
