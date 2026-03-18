"""
d4_pageindex.service
====================
LocalPageIndexService — synchronous query + chunk interface.

Adapted from D3 ``api/services/pageindex_service.py`` (LocalPageIndexService,
lines 338-454).

Changes from D3:
    - No Pydantic, no D3 ``api.*`` imports.
    - EventBus integration is optional: if ``d4-eventbus`` is installed *and*
      a bus instance is injected, events are emitted.  Otherwise the service
      works identically without them.
    - Event types used: ``PAGEINDEX_TREE_BUILT``, ``PAGEINDEX_QUERY_COMPLETE``.
      ``PAGEINDEX_QUERY_COMPLETE`` is not yet in d4-eventbus's EventType enum;
      this service falls back to a string literal when the enum member is absent.
    - ``index_content()`` is synchronous (no async).
    - Singleton accessor ``get_local_pageindex_service()`` provided.

IO Map:
    Inlet:  ``index_content(content, max_chars)`` direct call.
    Processing: ``VaultPageIndexer.build_tree()`` + ``chunk_for_extraction()``.
    Outlet: ``IndexResult`` dict  |  optional bus events.
    Host:   :class:`~d4_pageindex.manager.PageIndexManager`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from d4_pageindex.indexer import VaultPageIndexer
from d4_pageindex.models import SectionChunk, TreeNode

if TYPE_CHECKING:
    # Imported only for type annotations — not a hard dependency.
    from d4_eventbus import AgentEvent, EventBus, EventType  # noqa: F401

logger = logging.getLogger("d4_pageindex.service")

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

_EVT_TREE_BUILT = "pageindex_tree_built"
_EVT_QUERY_COMPLETE = "pageindex_query_complete"


def _resolve_event_type(name: str) -> Any:
    """Return the d4-eventbus EventType member if available, else a string.

    This avoids a hard import failure when d4-eventbus is not installed.
    """
    try:
        from d4_eventbus import EventType  # type: ignore[import]
        return EventType(name)  # pragma: no cover
    except (ImportError, ValueError):
        return name


def _make_agent_event(  # pragma: no cover
    event_type: Any,
    payload: dict[str, Any],
    source: str,
    correlation_id: str,
) -> Any | None:
    """Construct an AgentEvent if d4-eventbus is available, else return None.

    Separated into a module-level function so tests can patch it without
    requiring d4-eventbus to be installed.
    """
    try:
        from d4_eventbus import AgentEvent  # type: ignore[import]
        return AgentEvent(
            event_type=event_type,
            payload=payload,
            source=source,
            correlation_id=correlation_id,
        )
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Result type alias (plain dict — no Pydantic)
# ---------------------------------------------------------------------------

# IndexResult keys:
#   tree:          tuple[TreeNode, ...] — the parsed tree roots
#   chunks:        list[SectionChunk]
#   section_count: int
IndexResult = dict[str, Any]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LocalPageIndexService:
    """Synchronous document structural indexing using local markdown parsing.

    No API key, no LLM, no network calls required for indexing.

    EventBus is completely optional.  Inject a bus instance at construction
    time to enable event emission.  When no bus is provided the service
    behaves identically except no events are fired.

    Args:
        bus: Optional ``d4_eventbus.EventBus`` instance.  Pass ``None``
             (default) to run without event emission.

    Example::

        service = LocalPageIndexService()
        result = service.index_content(markdown_text)
        for chunk in result["chunks"]:
            print(chunk.path_string(), "—", len(chunk.text), "chars")

    With event bus::

        from d4_eventbus import get_event_bus
        service = LocalPageIndexService(bus=get_event_bus())
        result = service.index_content(markdown_text, source_id="spec.md")
    """

    def __init__(self, bus: Any = None) -> None:
        self._indexer = VaultPageIndexer()
        self._bus: Any = bus

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_content(
        self,
        content: str,
        max_chars: int = 32_000,
        source_id: str = "unknown",
    ) -> IndexResult:
        """Parse and chunk a markdown document.

        Args:
            content:   Raw markdown string.
            max_chars: Character limit per chunk (default 32 000 ≈ 8 000 tokens).
            source_id: Identifier for the source document (used in events and
                       log messages).

        Returns:
            Dict with keys:
                ``tree``          — ``tuple[TreeNode, ...]``
                ``chunks``        — ``list[SectionChunk]``
                ``section_count`` — ``int``

        Example::

            result = service.index_content(text, source_id="architecture.md")
            print(result["section_count"], "sections")
        """
        tree = self._indexer.build_tree(content)
        chunks = self._indexer.chunk_for_extraction(content, max_chars=max_chars)

        result: IndexResult = {
            "tree": tree,
            "chunks": chunks,
            "section_count": len(chunks),
        }

        self._maybe_emit_tree_built(source_id, tree, chunks)
        logger.debug(
            "d4_pageindex: indexed %s — %d sections", source_id, len(chunks)
        )
        return result

    def query(
        self,
        tree: tuple[TreeNode, ...],
        query: str,
        source_id: str = "unknown",
    ) -> list[SectionChunk]:
        """Search a pre-built tree for sections whose text matches *query*.

        Case-insensitive substring match.  Every matching node is returned
        as a :class:`~d4_pageindex.models.SectionChunk`, with breadcrumb path
        preserved.

        Args:
            tree:      Root nodes from :meth:`index_content` or
                       :meth:`~d4_pageindex.manager.PageIndexManager.get_tree`.
            query:     Search string (case-insensitive).
            source_id: Identifier passed through to events.

        Returns:
            List of :class:`~d4_pageindex.models.SectionChunk` whose text or
            title contains *query*.

        Example::

            chunks = service.query(tree, "database")
            for c in chunks:
                print(c.path_string())
        """
        matches: list[SectionChunk] = []
        _search_nodes(list(tree), query.lower(), path=(), out=matches)

        self._maybe_emit_query_complete(source_id, query, matches)
        return matches

    def merge_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Delegate to :meth:`~d4_pageindex.indexer.VaultPageIndexer.merge_extraction_results`.

        Convenience pass-through so callers need only import this service.
        """
        return self._indexer.merge_extraction_results(results)

    # ------------------------------------------------------------------
    # Private event helpers
    # ------------------------------------------------------------------

    def _maybe_emit_tree_built(
        self,
        source_id: str,
        tree: tuple[TreeNode, ...],
        chunks: list[SectionChunk],
    ) -> None:
        if self._bus is None:
            return
        event = _make_agent_event(
            event_type=_resolve_event_type(_EVT_TREE_BUILT),
            payload={
                "source_id": source_id,
                "section_count": len(chunks),
                "root_count": len(tree),
            },
            source="d4_pageindex.service",
            correlation_id=source_id,
        )
        if event is not None:
            self._bus.publish_sync(event)

    def _maybe_emit_query_complete(
        self,
        source_id: str,
        query: str,
        matches: list[SectionChunk],
    ) -> None:
        if self._bus is None:
            return
        event = _make_agent_event(
            event_type=_resolve_event_type(_EVT_QUERY_COMPLETE),
            payload={
                "source_id": source_id,
                "query": query,
                "match_count": len(matches),
            },
            source="d4_pageindex.service",
            correlation_id=source_id,
        )
        if event is not None:
            self._bus.publish_sync(event)


# ---------------------------------------------------------------------------
# Private search helper
# ---------------------------------------------------------------------------


def _search_nodes(
    nodes: list[TreeNode],
    query_lower: str,
    path: tuple[str, ...],
    out: list[SectionChunk],
) -> None:
    """Recursively search *nodes* for sections matching *query_lower*."""
    for node in nodes:
        current_path = path + (node.title,)
        if query_lower in node.title.lower() or query_lower in node.text.lower():
            out.append(
                SectionChunk(
                    node_id=node.node_id,
                    title=node.title,
                    text=node.text,
                    path=current_path,
                )
            )
        if node.children:
            _search_nodes(list(node.children), query_lower, current_path, out)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_service_instance: LocalPageIndexService | None = None


def get_local_pageindex_service(bus: Any = None) -> LocalPageIndexService:
    """Return the module-level singleton :class:`LocalPageIndexService`.

    The singleton is created on first call.  If *bus* is supplied on first
    call it is attached; subsequent calls ignore the *bus* argument.

    Args:
        bus: Optional ``d4_eventbus.EventBus`` to attach.

    Returns:
        The singleton :class:`LocalPageIndexService` instance.

    Example::

        svc = get_local_pageindex_service()
        result = svc.index_content(text)
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = LocalPageIndexService(bus=bus)
    return _service_instance


def reset_service_singleton() -> None:
    """Reset the singleton — intended for tests only."""
    global _service_instance
    _service_instance = None
