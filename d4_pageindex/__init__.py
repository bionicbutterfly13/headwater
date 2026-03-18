"""
d4_pageindex
============
Vectorless RAG via markdown header parsing for Dionysus 4.

Zero external dependencies.  Optional ``d4-eventbus`` integration for event
emission.

Public API
----------
::

    from d4_pageindex import (
        # Models
        TreeNode,
        SectionChunk,
        # Core indexer
        VaultPageIndexer,
        # Service (query + chunk)
        LocalPageIndexService,
        get_local_pageindex_service,
        reset_service_singleton,
        # Manager (project-wide cache)
        PageIndexManager,
        get_pageindex_manager,
        reset_manager_singleton,
    )

Quickstart
----------
::

    from d4_pageindex import VaultPageIndexer

    indexer = VaultPageIndexer()
    chunks = indexer.chunk_for_extraction(markdown_text)
    for chunk in chunks:
        print(chunk.path_string(), "—", len(chunk.text), "chars")

Service interface::

    from d4_pageindex import get_local_pageindex_service

    svc = get_local_pageindex_service()
    result = svc.index_content(markdown_text, source_id="spec.md")
    print(result["section_count"], "sections")

With event bus::

    from d4_eventbus import get_event_bus
    from d4_pageindex import get_local_pageindex_service

    svc = get_local_pageindex_service(bus=get_event_bus())
    result = svc.index_content(markdown_text, source_id="spec.md")

Manager (disk-cached project trees)::

    from pathlib import Path
    from d4_pageindex import get_pageindex_manager

    manager = get_pageindex_manager()
    tree = manager.build_from_file("spec", Path("conductor/spec.md"))
    matches = manager.query_tree("spec", "acceptance criteria")
"""

from d4_pageindex.indexer import VaultPageIndexer
from d4_pageindex.manager import (
    PageIndexManager,
    get_pageindex_manager,
    reset_manager_singleton,
)
from d4_pageindex.models import SectionChunk, TreeNode
from d4_pageindex.service import (
    LocalPageIndexService,
    get_local_pageindex_service,
    reset_service_singleton,
)

__all__ = [
    # Models
    "TreeNode",
    "SectionChunk",
    # Indexer
    "VaultPageIndexer",
    # Service
    "LocalPageIndexService",
    "get_local_pageindex_service",
    "reset_service_singleton",
    # Manager
    "PageIndexManager",
    "get_pageindex_manager",
    "reset_manager_singleton",
]

__version__ = "0.1.0"
