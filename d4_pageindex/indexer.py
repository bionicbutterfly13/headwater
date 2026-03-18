"""
d4_pageindex.indexer
====================
VaultPageIndexer — markdown header tree builder.

Adapted from D3 ``api/services/vault_pageindex.py``.

Changes from D3:
    - Returns :class:`~d4_pageindex.models.TreeNode` frozen dataclasses
      instead of raw mutable dicts.
    - Returns :class:`~d4_pageindex.models.SectionChunk` with ``path`` as
      ``tuple[str, ...]`` instead of ``list[str]``.
    - No Pydantic, no D3 service imports.
    - ``merge_extraction_results`` kept for callers that post-process
      per-chunk LLM outputs (entities / relationships / facts).

IO Map:
    Inlet:  Raw markdown string.
    Processing: Regex header parse → tree build → leaf chunking.
    Outlet: ``tuple[TreeNode, ...]`` tree  |  ``list[SectionChunk]`` chunks.
    Host:   :class:`~d4_pageindex.service.LocalPageIndexService`.
"""

from __future__ import annotations

import re
from typing import Any

from d4_pageindex.models import SectionChunk, TreeNode


# ---------------------------------------------------------------------------
# Compiled regexes
# ---------------------------------------------------------------------------

_HEADER_RE: re.Pattern[str] = re.compile(r"^(#{1,6})\s+(.+)$")
_CODE_FENCE_RE: re.Pattern[str] = re.compile(r"^```")


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class VaultPageIndexer:
    """Build structural indexes from markdown and chunk for downstream use.

    Uses header-based parsing (no LLM required for indexing). The tree is
    built from markdown headers (``#`` through ``######``) and each section
    can be retrieved as a :class:`~d4_pageindex.models.SectionChunk`.

    Example::

        indexer = VaultPageIndexer()
        roots = indexer.build_tree(markdown_text)
        chunks = indexer.chunk_for_extraction(markdown_text, max_chars=32_000)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_tree(self, markdown_content: str) -> tuple[TreeNode, ...]:
        """Build a tree of :class:`~d4_pageindex.models.TreeNode` from markdown.

        Respects fenced code blocks — headers inside triple-backtick blocks
        are not treated as structural headers.

        Args:
            markdown_content: Raw markdown string.

        Returns:
            Tuple of root-level :class:`~d4_pageindex.models.TreeNode` objects.
            Empty tuple when the document has no headers.

        Example::

            roots = indexer.build_tree("# Title\\n\\nBody text.")
            assert roots[0].title == "Title"
        """
        raw_nodes = _extract_raw_nodes(markdown_content)
        if not raw_nodes:
            return ()
        return _build_tree(raw_nodes)

    def chunk_for_extraction(
        self,
        markdown_content: str,
        max_chars: int = 32_000,
    ) -> list[SectionChunk]:
        """Split markdown into extraction-ready chunks based on structure.

        For documents with headers: yields leaf sections plus intro text
        of parent sections that have their own body content before the
        first child header.

        For flat documents (no headers): returns the entire content as a
        single chunk with title ``"(untitled)"``.

        Args:
            markdown_content: Raw markdown text.
            max_chars: Character limit per chunk.  Default 32 000 chars
                       (~8 000 tokens at the 4-chars-per-token heuristic).

        Returns:
            List of :class:`~d4_pageindex.models.SectionChunk`.

        Example::

            chunks = indexer.chunk_for_extraction(text, max_chars=32_000)
            for c in chunks:
                print(c.path_string(), "—", len(c.text), "chars")
        """
        roots = self.build_tree(markdown_content)

        if not roots:
            return [
                SectionChunk(
                    node_id="0001",
                    title="(untitled)",
                    text=markdown_content.strip()[:max_chars],
                    path=("(untitled)",),
                )
            ]

        chunks: list[SectionChunk] = []
        _collect_chunks(list(roots), path=(), max_chars=max_chars, out=chunks)

        if not chunks:  # pragma: no cover
            # Edge case: headers present but zero extractable body text.
            return [
                SectionChunk(
                    node_id="0001",
                    title="(untitled)",
                    text=markdown_content.strip()[:max_chars],
                    path=("(untitled)",),
                )
            ]

        return chunks

    def merge_extraction_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge per-chunk LLM extraction results into a single deduplicated output.

        Deduplicates entities by lowercase name, deduplicates relationships
        by ``(source, target, type)`` triple.

        Args:
            results: List of dicts with ``entities``, ``relationships``,
                     ``facts`` keys (as returned by an LLM extraction step).

        Returns:
            Merged dict with the same three keys.

        Example::

            merged = indexer.merge_extraction_results(per_chunk_results)
            print(merged["entities"])
        """
        if not results:
            return {"entities": [], "relationships": [], "facts": []}

        seen_entities: dict[str, dict[str, Any]] = {}
        all_relationships: list[dict[str, Any]] = []
        all_facts: list[dict[str, Any]] = []

        for result in results:
            for entity in result.get("entities", []):
                key = entity.get("name", "").lower()
                if key and key not in seen_entities:
                    seen_entities[key] = entity

            all_relationships.extend(result.get("relationships", []))
            all_facts.extend(result.get("facts", []))

        # Deduplicate relationships by (source, target, type).
        seen_rel_keys: set[tuple[str, str, str]] = set()
        unique_rels: list[dict[str, Any]] = []
        for rel in all_relationships:
            key = (
                rel.get("source", "").lower(),
                rel.get("target", "").lower(),
                rel.get("type", "").lower(),
            )
            if key not in seen_rel_keys:
                seen_rel_keys.add(key)
                unique_rels.append(rel)

        return {
            "entities": list(seen_entities.values()),
            "relationships": unique_rels,
            "facts": all_facts,
        }


# ---------------------------------------------------------------------------
# Private parsing helpers
# ---------------------------------------------------------------------------


def _extract_raw_nodes(markdown_content: str) -> list[dict[str, Any]]:
    """Extract header nodes from markdown, skipping fenced code blocks.

    Returns a flat list of dicts with keys:
        title    — header text
        line_num — 1-based line number
        level    — header depth (1–6)
        text     — full raw text from this header to the next header
    """
    lines = markdown_content.split("\n")
    flat: list[dict[str, Any]] = []
    in_code_block = False

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if _CODE_FENCE_RE.match(stripped):
            in_code_block = not in_code_block
            continue
        if not in_code_block and stripped:
            m = _HEADER_RE.match(stripped)
            if m:
                flat.append({
                    "title": m.group(2).strip(),
                    "line_num": line_num,
                    "level": len(m.group(1)),
                })

    # Attach text: from each header line to (but not including) the next.
    for i, node in enumerate(flat):
        start = node["line_num"] - 1  # 0-based
        end = flat[i + 1]["line_num"] - 1 if i + 1 < len(flat) else len(lines)
        node["text"] = "\n".join(lines[start:end]).strip()

    return flat


def _build_tree(raw_nodes: list[dict[str, Any]]) -> tuple[TreeNode, ...]:
    """Convert a flat list of raw header dicts into a nested TreeNode tree."""
    # Stack entries: (mutable_children_list, level)
    # We build children as lists first, then convert to tuples at the end.
    stack: list[tuple[list[Any], int]] = []
    root_children: list[Any] = []
    counter = 1

    for raw in raw_nodes:
        level = raw["level"]

        # Pop stack entries that are at the same or deeper level.
        while stack and stack[-1][1] >= level:
            stack.pop()

        parent_children = stack[-1][0] if stack else root_children

        node_data = {
            "node_id": str(counter).zfill(4),
            "title": raw["title"],
            "text": raw["text"],
            "line_num": raw["line_num"],
            "level": level,
            "mutable_children": [],
        }
        counter += 1
        parent_children.append(node_data)
        stack.append((node_data["mutable_children"], level))

    return tuple(_materialise(c) for c in root_children)


def _materialise(data: dict[str, Any]) -> TreeNode:
    """Recursively convert a mutable node dict into a frozen TreeNode."""
    children = tuple(_materialise(c) for c in data["mutable_children"])
    return TreeNode(
        node_id=data["node_id"],
        title=data["title"],
        text=data["text"],
        line_num=data["line_num"],
        level=data["level"],
        children=children,
    )


def _get_intro_text(node: TreeNode, max_chars: int) -> str:
    """Return body text that precedes the first child header.

    For a parent node, ``node.text`` contains the full raw text including
    all descendant headers.  This function strips out everything from the
    first child header onward so that only the *intro* paragraph(s) remain.
    """
    lines = node.text.split("\n")
    intro: list[str] = []
    header_seen = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") and not header_seen:
            # This is the node's own header line — keep it.
            intro.append(line)
            header_seen = True
            continue
        if stripped.startswith("#") and header_seen:  # pragma: no cover
            # This is a child's header — stop.
            # Note: node.text is sliced before the next sibling header by
            # _extract_raw_nodes, so this guard is defensive only.
            break
        intro.append(line)

    return "\n".join(intro).strip()[:max_chars]


def _collect_chunks(
    nodes: list[TreeNode],
    path: tuple[str, ...],
    max_chars: int,
    out: list[SectionChunk],
) -> None:
    """Recursively walk the tree and append SectionChunk to *out*."""
    for node in nodes:
        current_path = path + (node.title,)

        if node.children:
            # Parent node: emit intro text if substantial.
            intro = _get_intro_text(node, max_chars)
            if len(intro.strip()) > 20:
                out.append(
                    SectionChunk(
                        node_id=node.node_id,
                        title=node.title + " (intro)",
                        text=intro,
                        path=current_path,
                    )
                )
            _collect_chunks(list(node.children), current_path, max_chars, out)
        else:
            # Leaf node: emit full text.
            text = node.text.strip()
            if text:
                out.append(
                    SectionChunk(
                        node_id=node.node_id,
                        title=node.title,
                        text=text[:max_chars],
                        path=current_path,
                    )
                )
