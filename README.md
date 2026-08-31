# headwater

> Formerly published as **d4-pageindex**.

Vectorless RAG via markdown header parsing.

Zero external dependencies. Optional `d4-eventbus` integration.

## Install

```bash
pip install headwater
# with event bus support:
pip install "headwater[eventbus]"
```

## Quickstart

```python
from headwater import VaultPageIndexer

indexer = VaultPageIndexer()
chunks = indexer.chunk_for_extraction(markdown_text)
for chunk in chunks:
    print(chunk.path_string(), "—", len(chunk.text), "chars")
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
