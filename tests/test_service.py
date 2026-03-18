"""Tests for d4_pageindex.service — LocalPageIndexService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from d4_pageindex.models import SectionChunk, TreeNode
from d4_pageindex.service import (
    LocalPageIndexService,
    _search_nodes,
    get_local_pageindex_service,
    reset_service_singleton,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STRUCTURED_MD = """\
# Architecture

Overview of the architecture.

## Database Layer

PostgreSQL is used.

## API Layer

FastAPI handles requests.

### Auth

JWT-based authentication.
"""

FLAT_MD = "No headers. Just plain prose."


@pytest.fixture(autouse=True)
def reset_singleton() -> None:
    """Ensure the singleton is reset after every test."""
    yield
    reset_service_singleton()


@pytest.fixture
def service() -> LocalPageIndexService:
    return LocalPageIndexService()


# ---------------------------------------------------------------------------
# index_content
# ---------------------------------------------------------------------------


class TestIndexContent:
    def test_returns_dict_with_required_keys(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        assert "tree" in result
        assert "chunks" in result
        assert "section_count" in result

    def test_section_count_matches_chunks(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        assert result["section_count"] == len(result["chunks"])

    def test_tree_is_tuple_of_tree_nodes(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        assert isinstance(result["tree"], tuple)
        for node in result["tree"]:
            assert isinstance(node, TreeNode)

    def test_chunks_are_section_chunks(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        for chunk in result["chunks"]:
            assert isinstance(chunk, SectionChunk)

    def test_flat_document_has_one_section(self, service: LocalPageIndexService) -> None:
        result = service.index_content(FLAT_MD)
        assert result["section_count"] == 1

    def test_max_chars_forwarded_to_indexer(self, service: LocalPageIndexService) -> None:
        long_md = "# Section\n\n" + "y" * 1000
        result = service.index_content(long_md, max_chars=50)
        for chunk in result["chunks"]:
            assert len(chunk.text) <= 50

    def test_source_id_in_log(self, service: LocalPageIndexService) -> None:
        # Should not raise; just verifies the source_id arg is accepted.
        result = service.index_content(STRUCTURED_MD, source_id="test_doc.md")
        assert result["section_count"] > 0

    def test_no_bus_no_error(self) -> None:
        svc = LocalPageIndexService(bus=None)
        result = svc.index_content(STRUCTURED_MD)
        assert result["section_count"] > 0

    def test_with_mock_bus_emits_event(self) -> None:
        mock_bus = MagicMock()
        svc = LocalPageIndexService(bus=mock_bus)
        mock_event = MagicMock()
        with patch("d4_pageindex.service._make_agent_event", return_value=mock_event):
            svc.index_content(STRUCTURED_MD, source_id="doc.md")
        # publish_sync should have been called with the mock event
        mock_bus.publish_sync.assert_called_once_with(mock_event)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_returns_matching_chunks(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        tree = result["tree"]
        matches = service.query(tree, "PostgreSQL")
        assert len(matches) > 0

    def test_query_case_insensitive(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        lower = service.query(result["tree"], "postgresql")
        upper = service.query(result["tree"], "POSTGRESQL")
        assert len(lower) == len(upper)

    def test_query_no_match_returns_empty(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        matches = service.query(result["tree"], "zzznonexistent999")
        assert matches == []

    def test_query_returns_section_chunks(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        matches = service.query(result["tree"], "jwt")
        for m in matches:
            assert isinstance(m, SectionChunk)

    def test_query_matches_title(self, service: LocalPageIndexService) -> None:
        result = service.index_content(STRUCTURED_MD)
        matches = service.query(result["tree"], "Architecture")
        titles = [m.title for m in matches]
        # Root node title "Architecture" should match
        assert any("Architecture" in t for t in titles)

    def test_query_empty_tree(self, service: LocalPageIndexService) -> None:
        matches = service.query((), "anything")
        assert matches == []

    def test_query_with_bus_emits_event(self) -> None:
        mock_bus = MagicMock()
        svc = LocalPageIndexService(bus=mock_bus)
        mock_event = MagicMock()
        with patch("d4_pageindex.service._make_agent_event", return_value=mock_event):
            result = svc.index_content(STRUCTURED_MD)
            svc.query(result["tree"], "database")
        # publish_sync called at least once (for tree_built and query_complete)
        assert mock_bus.publish_sync.call_count >= 1


# ---------------------------------------------------------------------------
# merge_results
# ---------------------------------------------------------------------------


class TestMergeResults:
    def test_delegates_to_indexer(self, service: LocalPageIndexService) -> None:
        results = [
            {"entities": [{"name": "Foo"}], "relationships": [], "facts": []},
        ]
        merged = service.merge_results(results)
        assert len(merged["entities"]) == 1


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_returns_same_instance(self) -> None:
        a = get_local_pageindex_service()
        b = get_local_pageindex_service()
        assert a is b

    def test_reset_allows_new_instance(self) -> None:
        a = get_local_pageindex_service()
        reset_service_singleton()
        b = get_local_pageindex_service()
        assert a is not b

    def test_bus_attached_on_first_call(self) -> None:
        mock_bus = MagicMock()
        svc = get_local_pageindex_service(bus=mock_bus)
        assert svc._bus is mock_bus

    def test_bus_ignored_on_second_call(self) -> None:
        svc_first = get_local_pageindex_service()
        second_bus = MagicMock()
        svc_second = get_local_pageindex_service(bus=second_bus)
        assert svc_first is svc_second
        assert svc_second._bus is None


# ---------------------------------------------------------------------------
# Private _search_nodes
# ---------------------------------------------------------------------------


class TestSearchNodes:
    def test_empty_nodes_returns_empty(self) -> None:
        out: list[SectionChunk] = []
        _search_nodes([], "query", path=(), out=out)
        assert out == []

    def test_match_by_text(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="Intro",
            text="This talks about PostgreSQL.",
            line_num=1,
            level=1,
            children=(),
        )
        out: list[SectionChunk] = []
        _search_nodes([node], "postgresql", path=(), out=out)
        assert len(out) == 1
        assert out[0].title == "Intro"

    def test_match_by_title(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="Database Layer",
            text="Some content here.",
            line_num=1,
            level=1,
            children=(),
        )
        out: list[SectionChunk] = []
        _search_nodes([node], "database", path=(), out=out)
        assert len(out) == 1

    def test_recurses_into_children(self) -> None:
        child = TreeNode(
            node_id="0002",
            title="Child Section",
            text="Relevant info.",
            line_num=5,
            level=2,
            children=(),
        )
        parent = TreeNode(
            node_id="0001",
            title="Parent",
            text="Parent text.",
            line_num=1,
            level=1,
            children=(child,),
        )
        out: list[SectionChunk] = []
        _search_nodes([parent], "relevant", path=(), out=out)
        assert len(out) == 1
        assert out[0].title == "Child Section"

    def test_path_preserved_in_match(self) -> None:
        node = TreeNode(
            node_id="0001",
            title="Leaf",
            text="matching text",
            line_num=1,
            level=1,
            children=(),
        )
        out: list[SectionChunk] = []
        _search_nodes([node], "matching", path=("Root",), out=out)
        assert out[0].path == ("Root", "Leaf")
