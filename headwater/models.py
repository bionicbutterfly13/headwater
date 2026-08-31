"""
headwater.models
===================
Immutable data structures for headwater.

All entities are frozen dataclasses — no mutation anywhere.

TreeNode
    One node in the parsed markdown header tree.  Nesting is captured via
    the ``children`` tuple so the full document hierarchy is traversable.

SectionChunk
    A section of markdown ready for downstream processing (LLM extraction,
    keyword search, etc.).  ``path`` is the breadcrumb list of ancestor
    titles from root to this node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TreeNode:
    """One node in a markdown header tree.

    Attributes:
        node_id:   Zero-padded integer string (e.g. ``"0003"``).
        title:     Header text with leading ``#`` stripped.
        text:      Full raw text of this section, including the header line
                   and all body content down to (but not including) the next
                   header of equal or higher weight.
        line_num:  1-based source line number of the header.
        level:     Header depth: 1 for ``#``, 2 for ``##``, … 6 for ``######``.
        children:  Immediate child nodes (empty tuple for leaf nodes).

    Example::

        node = TreeNode(
            node_id="0001",
            title="Architecture",
            text="# Architecture\\n\\nOverview text.",
            line_num=3,
            level=1,
            children=(),
        )
    """

    node_id: str
    title: str
    text: str
    line_num: int
    level: int
    children: tuple[TreeNode, ...] = field(default_factory=tuple)

    def is_leaf(self) -> bool:
        """Return True when this node has no children."""
        return len(self.children) == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (JSON-compatible, children recurse).

        Example::

            d = node.to_dict()
            json.dumps(d)  # safe
        """
        base: dict[str, Any] = {
            "node_id": self.node_id,
            "title": self.title,
            "text": self.text,
            "line_num": self.line_num,
            "level": self.level,
        }
        if self.children:
            base["children"] = [c.to_dict() for c in self.children]
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TreeNode":
        """Deserialise from a plain dict produced by :meth:`to_dict`.

        Example::

            node = TreeNode.from_dict(json.loads(json_string))
        """
        children = tuple(
            cls.from_dict(c) for c in data.get("children", [])
        )
        return cls(
            node_id=data["node_id"],
            title=data["title"],
            text=data["text"],
            line_num=data["line_num"],
            level=data["level"],
            children=children,
        )


@dataclass(frozen=True)
class SectionChunk:
    """A section of markdown ready for downstream processing.

    Attributes:
        node_id: Corresponds to the :class:`TreeNode` this chunk was derived
                 from.
        title:   Section title (may include ``" (intro)"`` suffix for parent
                 sections whose body precedes their first child).
        text:    Section body text, truncated to ``max_chars`` if needed.
        path:    Ordered breadcrumb list from root to this section.
                 E.g. ``["Architecture", "Database Layer"]``.

    Example::

        chunk = SectionChunk(
            node_id="0003",
            title="Database Layer",
            text="PostgreSQL is used for persistent storage.",
            path=["Architecture", "Database Layer"],
        )
        label = " > ".join(chunk.path)  # "Architecture > Database Layer"
    """

    node_id: str
    title: str
    text: str
    path: tuple[str, ...]

    def path_string(self, separator: str = " > ") -> str:
        """Return the breadcrumb path as a single string.

        Args:
            separator: Delimiter between path segments.

        Returns:
            E.g. ``"Architecture > Database Layer"``.
        """
        return separator.join(self.path)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (JSON-compatible).

        Example::

            json.dumps(chunk.to_dict())
        """
        return {
            "node_id": self.node_id,
            "title": self.title,
            "text": self.text,
            "path": list(self.path),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionChunk":
        """Deserialise from a plain dict produced by :meth:`to_dict`.

        Example::

            chunk = SectionChunk.from_dict(d)
        """
        return cls(
            node_id=data["node_id"],
            title=data["title"],
            text=data["text"],
            path=tuple(data["path"]),
        )
