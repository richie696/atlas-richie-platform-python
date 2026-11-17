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

## Scope

Batch chunking is complete. The Java `StreamingChunker` (incremental streaming
sessions) is **not** ported yet; strategies expose `supports_streaming` so a
future streaming layer can route correctly. `SEMANTIC` reports `False` because
semantic boundaries need the full document.

The Spring auto-configuration and properties classes are intentionally absent —
construct the service explicitly.
