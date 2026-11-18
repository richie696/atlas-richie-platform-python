# atlas-richie-chunking-core

Framework-neutral document chunking: immutable rules, nine strategies, and
diagnostics. Ported from the Java `atlas-richie-document-chunking-core`.

**Zero runtime dependencies.** Tokenizer and semantic-boundary implementations
are injected through SPIs, so this package never pulls a model SDK.

## Usage

```python
from atlas_richie.chunking_core import ChunkingRule, DefaultChunkingService, Strategy

service = DefaultChunkingService()                     # RECURSIVE, max=1600, overlap=160
result = service.chunk(text)
for chunk in result.chunks:
    print(chunk.ordinal, chunk.char_start, chunk.char_end, chunk.text)

rule = ChunkingRule("kb-v1", "1", Strategy.MARKDOWN, 800, 80)
result = service.chunk(text, rule)
```

## Strategies

| Strategy | Boundary source |
| --- | --- |
| `FIXED` | pure character window, no separator lookup |
| `RECURSIVE` | caller-declared separator precedence (default) |
| `TOKEN` | binary search against an injected `TokenCounter` |
| `PARAGRAPH` | `\n\n`, `\n` |
| `SENTENCE` | `。！？` and `. ! ? ` |
| `MARKDOWN` | heading prefixes, fenced blocks, then newlines |
| `HTML` | common closing tags (does not parse a DOM) |
| `PAGE` | `\f`, `\n\n` (page numbers are the caller's concern) |
| `SEMANTIC` | injected `SemanticBoundaryAdvisor`, RECURSIVE length control |

## Contracts worth knowing

- `Chunk` intervals are half-open `[char_start, char_end)` and always relative to
  the **original** input, so chunks map back to the source document unambiguously.
- `ChunkingRule` is an immutable snapshot. Persist `rule_id` + `version` alongside
  your vectors to reproduce a historical cut instead of re-guessing configuration.
- `overlap_characters` must be `< max_characters`, guaranteeing forward progress.
- A separator match only has to *start* at or before the cap, so a boundary can
  extend past `max_characters`. This matches the Java implementation.
- Small-tail merging re-slices the original content, keeping the whitespace that
  sat between the merged pieces.
- Whitespace classification follows Java's `Character.isWhitespace`, which
  **excludes** non-breaking spaces — unlike Python's `str.isspace()`. This matters
  for HTML-derived text containing U+00A0.

## Semantic failure handling

`SemanticChunkingOptions` defaults to `FAIL_FAST`: an advisor exception surfaces
as `SemanticBoundaryException` for the orchestration layer to retry or alert on.
Opt into `FALLBACK_TO_DETERMINISTIC` to degrade to RECURSIVE with a
`SEMANTIC_FALLBACK` signal recorded in diagnostics. An advisor returning only
out-of-range offsets yields `INVALID_SEMANTIC_BOUNDARY`; returning nothing means
"no opinion" and falls back without a signal.

## Streaming sessions

`StreamingChunker` ports the Java incremental session API and reuses the batch
strategies' `boundary_at_or_before`, so no strategy changes were needed.

```python
from atlas_richie.chunking_core import ChunkingRule, DefaultChunkingService, StreamingChunker

chunker = StreamingChunker(DefaultChunkingService(), ChunkingRule.recursive_defaults(800, 80))
for section in upstream_sections:
    for chunk in chunker.accept(section):   # emits only determined boundaries
        index(chunk)
for chunk in chunker.finish():              # flush the tail; idempotent
    index(chunk)
```

- `accept` on a finished session raises; `finish()` is idempotent; `abort()`
  discards the unemitted tail and closes the session.
- `SEMANTIC` is rejected — semantic boundaries need the whole document. Without an
  advisor the strategy factory rejects it first; with one, the streaming check does.
- **Coordinate contract**: `accept` inserts a `'\n'` between sections when the
  buffer is non-empty, and that separator **counts toward global offsets**. Chunk
  coordinates are relative to the text the session saw, not to a naive
  concatenation of your sections. With `max=5, overlap=2` and sections `"abcde"`
  then `"fghij"`, the chunks are `[0,5)`, `[3,8)`, `[6,11)` — ending at 11, not 10.
- **Overlap correctness**: each drain consumes only `end - overlap`, leaving the
  tail buffered as the next chunk's prefix, so adjacent chunks intersect by exactly
  the configured overlap.
- `max_pending_characters` defaults to `max_characters + overlap_characters` and
  must be `>= max_characters`. The overflow guard inherited from Java is defensive
  rather than reachable: the drain loop always reduces the buffer below
  `max_characters`, so it cannot exceed a limit that is at least that large.
- Java's int32 offset overflow guard is not reproduced — Python ints are unbounded.

## Scope

Batch and streaming chunking are both complete. The Spring auto-configuration and
properties classes are intentionally absent — construct the service explicitly.
`StreamingChunkerFactory` is not ported; the constructor already supplies the
default pending limit.

## Verification

Both layers are pinned by randomised differential runs against the compiled Java
core: 400 batch cases and 120 streaming sessions (including a double-`finish()`
idempotence probe), all byte-identical.
