"""
d4_pageindex.manager
====================
PageIndexManager — project-wide tree cache with JSON persistence.

Adapted from D3 ``api/services/pageindex_manager.py``.

Changes from D3:
    - Uses :class:`~d4_pageindex.service.LocalPageIndexService` (local parsing)
      instead of D3's cloud PageIndexService.
    - Tree persistence uses :class:`~d4_pageindex.models.TreeNode` serialisation
      to JSON — no external format.
    - All async removed; the manager is fully synchronous.
    - No Pydantic, no D3 imports.

IO Map:
    Inlet:  ``build_from_directory(path)`` or ``build_from_content(key, text)``
            direct calls.
    Processing: Reads markdown files → delegates to LocalPageIndexService.
    Outlet: ``tuple[TreeNode, ...]`` tree  |  JSON on disk.
    Host:   Any D4 module that needs structural navigation of a codebase or
            document corpus.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from d4_pageindex.models import TreeNode
from d4_pageindex.service import LocalPageIndexService, get_local_pageindex_service

logger = logging.getLogger("d4_pageindex.manager")

# Default location for persisted tree JSON files.
_DEFAULT_CACHE_DIR = Path("data/pageindex")

# Glob patterns for files considered when building a directory tree.
_MARKDOWN_GLOBS = ("**/*.md", "**/*.txt")


class PageIndexManager:
    """Orchestrate indexing of local files with in-memory and on-disk caching.

    The manager keeps a per-key tree cache in memory.  On first access for a
    given key the manager attempts to load from disk; on miss it builds and
    persists the tree.

    Args:
        cache_dir: Directory where JSON tree files are stored.  Created if it
                   does not exist.
        service:   :class:`~d4_pageindex.service.LocalPageIndexService` to use.
                   Defaults to the module-level singleton.
        max_files: Maximum number of files to include when building a tree from
                   a directory (prevents runaway builds on large repos).

    Example::

        manager = PageIndexManager(cache_dir=Path("/tmp/pageindex"))
        tree = manager.get_tree("architecture.md")
        if tree is None:
            tree = manager.build_from_file("architecture.md", Path("docs/architecture.md"))
        chunks = manager.query_tree("architecture.md", "database")
    """

    def __init__(
        self,
        cache_dir: Path = _DEFAULT_CACHE_DIR,
        service: LocalPageIndexService | None = None,
        max_files: int = 20,
    ) -> None:
        self._cache_dir = cache_dir
        self._service = service or get_local_pageindex_service()
        self._max_files = max_files
        self._memory_cache: dict[str, tuple[TreeNode, ...]] = {}

    # ------------------------------------------------------------------
    # Cache primitives
    # ------------------------------------------------------------------

    def get_tree(self, key: str) -> tuple[TreeNode, ...] | None:
        """Return a cached tree by *key*, checking memory then disk.

        Args:
            key: Unique identifier for this tree (e.g. a filename or slug).

        Returns:
            ``tuple[TreeNode, ...]`` if found, ``None`` otherwise.

        Example::

            tree = manager.get_tree("spec")
            if tree is None:
                tree = manager.build_from_file("spec", Path("spec.md"))
        """
        if key in self._memory_cache:
            return self._memory_cache[key]

        loaded = self._load_from_disk(key)
        if loaded is not None:
            self._memory_cache[key] = loaded
            return loaded

        return None

    def put_tree(self, key: str, tree: tuple[TreeNode, ...]) -> None:
        """Store *tree* in the in-memory cache and persist to disk.

        Args:
            key:  Unique identifier.
            tree: Root nodes to store.

        Example::

            manager.put_tree("spec", roots)
        """
        self._memory_cache[key] = tree
        self._save_to_disk(key, tree)

    def invalidate(self, key: str) -> None:
        """Remove *key* from memory and delete its JSON file if present.

        Args:
            key: Cache key to invalidate.

        Example::

            manager.invalidate("spec")
        """
        self._memory_cache.pop(key, None)
        json_path = self._json_path(key)
        if json_path.exists():
            json_path.unlink()
            logger.debug("d4_pageindex.manager: invalidated disk cache for %s", key)

    # ------------------------------------------------------------------
    # Build helpers
    # ------------------------------------------------------------------

    def build_from_content(
        self,
        key: str,
        content: str,
        max_chars: int = 32_000,
        force: bool = False,
    ) -> tuple[TreeNode, ...]:
        """Build and cache a tree from a raw markdown string.

        Args:
            key:       Cache key (e.g. source filename).
            content:   Raw markdown text.
            max_chars: Character limit forwarded to the indexer.
            force:     If ``True``, rebuild even when a cached copy exists.

        Returns:
            ``tuple[TreeNode, ...]``

        Example::

            roots = manager.build_from_content("readme", Path("README.md").read_text())
        """
        if not force:
            cached = self.get_tree(key)
            if cached is not None:
                return cached

        result = self._service.index_content(content, max_chars=max_chars, source_id=key)
        tree: tuple[TreeNode, ...] = result["tree"]
        self.put_tree(key, tree)
        logger.info(
            "d4_pageindex.manager: built tree for %s (%d roots, %d sections)",
            key,
            len(tree),
            result["section_count"],
        )
        return tree

    def build_from_file(
        self,
        key: str,
        file_path: Path,
        max_chars: int = 32_000,
        force: bool = False,
    ) -> tuple[TreeNode, ...] | None:
        """Build and cache a tree from a single file.

        Args:
            key:       Cache key.
            file_path: Path to the markdown file.
            max_chars: Character limit forwarded to the indexer.
            force:     Rebuild even when cached.

        Returns:
            ``tuple[TreeNode, ...]`` or ``None`` if the file cannot be read.

        Example::

            roots = manager.build_from_file("spec", Path("conductor/spec.md"))
        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("d4_pageindex.manager: cannot read %s: %s", file_path, exc)
            return None

        return self.build_from_content(key, content, max_chars=max_chars, force=force)

    def build_from_directory(
        self,
        key: str,
        directory: Path,
        globs: tuple[str, ...] = _MARKDOWN_GLOBS,
        max_chars: int = 32_000,
        force: bool = False,
    ) -> tuple[TreeNode, ...] | None:
        """Build and cache a tree from all markdown files in *directory*.

        Files are sorted for deterministic output.  At most ``max_files``
        files are included.

        Args:
            key:       Cache key.
            directory: Root directory to search.
            globs:     Glob patterns for file discovery.
            max_chars: Character limit forwarded to the indexer.
            force:     Rebuild even when cached.

        Returns:
            ``tuple[TreeNode, ...]`` or ``None`` if the directory is missing
            or contains no matching files.

        Example::

            roots = manager.build_from_directory("docs", Path("docs/"))
        """
        if not force:
            cached = self.get_tree(key)
            if cached is not None:
                return cached

        if not directory.exists():
            logger.warning(
                "d4_pageindex.manager: directory not found: %s", directory
            )
            return None

        files: list[Path] = []
        for pattern in globs:
            files.extend(directory.glob(pattern))
        files = sorted(set(files))[: self._max_files]

        if not files:
            logger.warning(
                "d4_pageindex.manager: no matching files in %s", directory
            )
            return None

        parts = [f"# Directory Index: {directory}\n"]
        for f in files:
            rel = f.relative_to(directory) if f.is_relative_to(directory) else f
            try:
                parts.append(f"\n\n--- {rel} ---\n\n{f.read_text(encoding='utf-8', errors='replace')[:4000]}")
            except OSError as exc:
                logger.debug("d4_pageindex.manager: skipping %s: %s", f, exc)

        content = "".join(parts)
        logger.info(
            "d4_pageindex.manager: building directory tree for %s (%d files)",
            key,
            len(files),
        )
        return self.build_from_content(key, content, max_chars=max_chars, force=True)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query_tree(
        self,
        key: str,
        query: str,
    ) -> list[Any]:
        """Query a cached tree by key.

        Loads from memory/disk if necessary.  Returns an empty list when the
        key is not in cache (no auto-build).

        Args:
            key:   Cache key of a previously built tree.
            query: Search string (case-insensitive substring match).

        Returns:
            List of :class:`~d4_pageindex.models.SectionChunk`.

        Example::

            matches = manager.query_tree("spec", "acceptance criteria")
        """
        tree = self.get_tree(key)
        if tree is None:
            logger.debug(
                "d4_pageindex.manager: query for unknown key '%s'", key
            )
            return []
        return self._service.query(tree, query, source_id=key)

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------

    def _json_path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace("\\", "_")
        return self._cache_dir / f"{safe_key}.json"

    def _save_to_disk(self, key: str, tree: tuple[TreeNode, ...]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "key": key,
                "roots": [node.to_dict() for node in tree],
            }
            self._json_path(key).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("d4_pageindex.manager: saved tree for %s", key)
        except OSError as exc:  # pragma: no cover
            logger.warning(
                "d4_pageindex.manager: could not persist tree for %s: %s", key, exc
            )

    def _load_from_disk(self, key: str) -> tuple[TreeNode, ...] | None:
        json_path = self._json_path(key)
        if not json_path.exists():
            return None
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            roots = tuple(TreeNode.from_dict(r) for r in raw.get("roots", []))
            logger.debug(
                "d4_pageindex.manager: loaded tree for %s from disk", key
            )
            return roots
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            logger.warning(
                "d4_pageindex.manager: could not load tree for %s: %s", key, exc
            )
            return None


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_manager_instance: PageIndexManager | None = None


def get_pageindex_manager(
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    service: LocalPageIndexService | None = None,
) -> PageIndexManager:
    """Return the module-level singleton :class:`PageIndexManager`.

    Args:
        cache_dir: Only used on first call when the singleton is created.
        service:   Only used on first call when the singleton is created.

    Returns:
        The singleton :class:`PageIndexManager` instance.

    Example::

        manager = get_pageindex_manager(cache_dir=Path("/tmp/pi"))
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PageIndexManager(cache_dir=cache_dir, service=service)
    return _manager_instance


def reset_manager_singleton() -> None:
    """Reset the singleton — intended for tests only."""
    global _manager_instance
    _manager_instance = None
