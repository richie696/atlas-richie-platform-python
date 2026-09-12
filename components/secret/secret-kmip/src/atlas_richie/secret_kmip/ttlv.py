"""KMIP 2.1 TTLV codec — minimal Type-Length-Value 编码 / 解码。

中文
----
对位 Java `cn.richie696.component.secret.provider.kmip.KmipTtlv`
(60 行,1:1 翻译)。只覆盖 wrap / unwrap 路径需要的子集:

| Type    | Code | Value layout           |
|---------|------|------------------------|
| STRUCTURE    | `0x01` | 嵌套子元素(8-byte 对齐)|
| INTEGER      | `0x02` | 4-byte big-endian      |
| ENUMERATION  | `0x05` | 4-byte big-endian      |
| TEXT         | `0x07` | UTF-8 bytes            |
| BYTE_STRING  | `0x08` | 原始 bytes             |

每个 element 在 wire 上是:
```
[3 bytes: tag] [1 byte: type] [4 bytes: length] [length bytes: value] [pad to 8-byte]
```
对位 Java `KmipTtlv.element(...)`。Padding 用 `(8 - (length % 8)) % 8`,
零长度 value 仍有 0 bytes padding。

English
--------
Minimal KMIP 2.1 Type-Length-Value codec. Mirrors Java
`KmipTtlv.java` 1:1. Covers only the subset of types
(STRUCTURE / INTEGER / ENUMERATION / TEXT / BYTE_STRING)
needed by the wrap / unwrap operations. Decoder
recursively walks structures via `children()`. 1:1 with
Java's tag-style + type-byte + 4-byte big-endian length +
8-byte-aligned padding layout.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple


class Element(NamedTuple):
    """A single TTLV element. 1:1 with Java's `KmipTtlv.Element` record.

    Attributes:
        tag: 24-bit KMIP tag.
        type: 1-byte type code (STRUCTURE / INTEGER / etc.).
        value: Raw value bytes (for STRUCTURE, the concatenated
            children; for INTEGER/ENUMERATION, the 4-byte
            big-endian encoding; for TEXT, the UTF-8 bytes;
            for BYTE_STRING, the raw bytes).
    """

    tag: int
    type: int
    value: bytes


# Type codes (1:1 with Java's constants)
STRUCTURE = 0x01
INTEGER = 0x02
ENUMERATION = 0x05
TEXT = 0x07
BYTE_STRING = 0x08


def _align8(length: int) -> int:
    """Pad `length` up to the next 8-byte boundary."""
    return length + ((8 - (length % 8)) % 8)


def element(tag: int, type_code: int, value: bytes) -> bytes:
    """Encode a single TTLV element on the wire.

    Wire layout (24 bytes max overhead):
    ```
    [tag byte 0] [tag byte 1] [tag byte 2] [type] [len high] [len low-2] [len low-1] [len low 0] [value...] [pad...]
    ```
    """
    if not 0 <= tag <= 0xFFFFFF:
        raise ValueError(f"TTLV tag must fit in 24 bits: {tag:#x}")
    if not 0 <= type_code <= 0xFF:
        raise ValueError(f"TTLV type must fit in 8 bits: {type_code:#x}")
    tag_bytes = bytes(((tag >> 16) & 0xFF, (tag >> 8) & 0xFF, tag & 0xFF))
    header = tag_bytes + bytes((type_code,)) + struct.pack(">I", len(value))
    padding = b"\x00" * (_align8(len(value)) - len(value))
    return header + value + padding


def structure(tag: int, *children: bytes) -> bytes:
    """Encode a STRUCTURE element with concatenated children."""
    return element(tag, STRUCTURE, b"".join(children))


def integer(tag: int, value: int) -> bytes:
    """Encode an INTEGER element (4-byte big-endian)."""
    return element(tag, INTEGER, struct.pack(">i", value))


def enumeration(tag: int, value: int) -> bytes:
    """Encode an ENUMERATION element (4-byte big-endian)."""
    return element(tag, ENUMERATION, struct.pack(">i", value))


def text(tag: int, value: str) -> bytes:
    """Encode a TEXT element (UTF-8)."""
    return element(tag, TEXT, value.encode("utf-8"))


def bytes_(tag: int, value: bytes | bytearray | memoryview) -> bytes:
    """Encode a BYTE_STRING element.

    Defensively copies the input buffer to avoid aliasing
    surprises (matches Java's `KmipTtlv.bytes` which calls
    `value.clone()`).
    """
    payload = bytes(value) if not isinstance(value, bytes) else value
    return element(tag, BYTE_STRING, payload)


def children(buffer: bytes, *, offset: int = 0, end: int | None = None) -> list[Element]:
    """Recursively parse a TTLV byte stream into a list of elements.

    Mirrors Java's `KmipTtlv.children(bytes)` and
    `children(bytes, start, end)` overload. Validates
    8-byte alignment and rejects truncated / over-long
    elements with `ValueError`.
    """
    if end is None:
        end = len(buffer)
    if offset < 0 or end > len(buffer) or offset > end:
        raise ValueError("TTLV children: invalid range")
    result: list[Element] = []
    cursor = offset
    while cursor + 8 <= end:
        tag = (buffer[cursor] << 16) | (buffer[cursor + 1] << 8) | buffer[cursor + 2]
        type_code = buffer[cursor + 3]
        length = struct.unpack(">I", buffer[cursor + 4 : cursor + 8])[0]
        if length < 0:
            raise ValueError(f"TTLV element length is negative: {length}")
        body_end = cursor + 8 + length
        if body_end > end:
            raise ValueError("TTLV element extends past the parent boundary")
        value = bytes(buffer[cursor + 8 : body_end])
        result.append(Element(tag=tag, type=type_code, value=value))
        cursor = body_end + ((8 - (length % 8)) % 8)
    if cursor != end:
        raise ValueError("TTLV stream has trailing bytes / bad padding")
    return result


def first(elements: Iterable[Element], tag: int, type_code: int) -> bytes | None:
    """Return the value of the first matching element, or `None`.

    Recursively walks STRUCTURE children. Mirrors Java's
    `KmipTtlv.first(elements, tag, type)`.
    """
    for element_ in elements:
        if element_.tag == tag and element_.type == type_code:
            return element_.value
        if element_.type == STRUCTURE:
            nested = first(children(element_.value), tag, type_code)
            if nested is not None:
                return nested
    return None


__all__ = [
    "Element",
    "STRUCTURE",
    "INTEGER",
    "ENUMERATION",
    "TEXT",
    "BYTE_STRING",
    "element",
    "structure",
    "integer",
    "enumeration",
    "text",
    "bytes_",
    "children",
    "first",
]
