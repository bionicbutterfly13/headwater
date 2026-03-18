# d4-pageindex

Vectorless RAG via markdown header parsing for Dionysus 4.

Zero external dependencies. Optional `d4-eventbus` integration.

## Install

```bash
pip install d4-pageindex
# with event bus support:
pip install "d4-pageindex[eventbus]"
```

## Quickstart

```python
from d4_pageindex import VaultPageIndexer

indexer = VaultPageIndexer()
chunks = indexer.chunk_for_extraction(markdown_text)
for chunk in chunks:
    print(chunk.path_string(), "—", len(chunk.text), "chars")
```
