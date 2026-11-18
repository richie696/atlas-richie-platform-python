# atlas-richie-document-parser

Document format detection, streaming parse events, an SSRF fetch policy and a
pluggable parser router. Ported from the Java `atlas-richie-document-parser`.

**Zero runtime dependencies.** Pairs with `atlas-richie-chunking-core` to form the
RAG preprocessing chain: parse into segments, then chunk.

## Usage

```python
from atlas_richie.document_parser import ParserRouter, ParserContext
from atlas_richie.chunking_core import ChunkingRule, DefaultChunkingService

router = ParserRouter()
segments = [e.segment.text for e in router.parse_file("notes.md") if hasattr(e, "segment")]

service = DefaultChunkingService()
chunks = service.chunk("\n\n".join(segments), ChunkingRule.recursive_defaults(800, 80))
```

## What is ported

- **Format detection** with the Java decision order: content sniffing first,
  extension as fallback. Magic bytes are checked with the standard library instead
  of Tika. MIME→Format and extension→Format mappings match Java exactly.
- **Parse events**: `Streaming` (text segment), `ImageStreaming` (embedded image
  bytes), `Finished` (summary + counts), `Failed`. Segments carry
  `/{name}/Paragraph[{n}]` section paths and `order`/`format` metadata, as in Java.
- **Text/Markdown fast path**: genuinely streaming — a segment is emitted as soon
  as a blank-line paragraph boundary is reached, not after buffering the document.
  `max_segment_length` forces splits mid-paragraph.
- **`UrlFetchPolicy`**: defaults deny plain HTTP and private/loopback/link-local
  addresses, cap downloads at 200 MB, 5s connect / 60s read timeouts.
- **`ParserRouter`**: a registry rather than Java's hard-wired Tika/Fesod pair.

## Deliberate deviations

- **`CidrBlock.contains` actually works.** Java's is a Phase-1 placeholder that
  always returns `False`, so an explicitly configured allowlist silently never
  matches. This implements real IPv4/IPv6 CIDR matching. An allowlist entry
  overrides the private-IP denial but never the plain-HTTP denial.
- **ZIP-container detection is a heuristic** over the 8 KiB sniff buffer (member
  names such as `word/`, `xl/`, `ppt/`, ODF `mimetype`), not a full ZIP parse — the
  buffer may be truncated. Legacy OLE2 files cannot be split into DOC/XLS/PPT from
  magic bytes alone, so they map to UNKNOWN and the extension fallback decides.
- **No PDF/Office parser in the core.** Those need heavy libraries; register an
  adapter via `router.register(Format.PDF, parser)` from an optional extra. Routing
  to an unregistered format raises `FormatNotSupportedException` naming the format.

## Not ported

`TikaDocumentParser` (320 lines), `FesodDocumentParser`, `UrlFetcher` (399 lines of
HTTP download plumbing), and the Spring auto-configuration. The fetch *policy* is
ported; the fetcher itself belongs with an HTTP adapter.
