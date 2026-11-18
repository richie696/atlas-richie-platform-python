# atlas-richie-chunking-parser-adapter

把 `document-parser` 的事件流接成带**溯源区间**的 chunk 流。

对位 Java `atlas-richie-document-chunking-parser-adapter`。这是
parse → chunk → vector 链路中唯一的桥：两个 core 互不依赖，由本包连接。

只依赖 `chunking-core` + `document-parser`，两者均为零第三方依赖，
因此本包也不引入任何外部驱动。

## 用法

```python
from atlas_richie.document_parser import ParserRouter, BytesSource
from atlas_richie.chunking_parser_adapter import ParserChunkingAdapter, Section, Finished

adapter = ParserChunkingAdapter()
events = ParserRouter().parse(BytesSource(b"# Title\n\nbody text", name="doc.md"))

for event in adapter.chunk_events(events):
    if isinstance(event, Section):
        for chunk, span in zip(event.value.result.chunks, event.value.source_spans):
            print(chunk.ordinal, span.section_index, span.char_start, span.char_end)
    elif isinstance(event, Finished):
        print(event.total_sections, event.emitted_chunks)
```

## 契约

- 每个 chunk 对应一个 `SourceSpan`，记住它来自哪个 section 的哪段字符区间，
  RAG 引用/回链据此定位原文。
- 输出流**恒以恰好一个终态事件结束**（`Finished` 或 `Failed`）。上游提前截断
  且未给终态时，适配器补一个 `Finished`，避免消费方悬挂。
- `ImageStreaming` 不参与文本切分，图片计数由上游 `Finished` 携带。