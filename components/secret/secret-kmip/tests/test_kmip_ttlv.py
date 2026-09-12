"""KMIP TTLV codec tests — round-trip + edge cases.

中文
----
验证 `KmipTtlv` codec 的全部 5 种类型 + 嵌套 + 错误路径,
对应 Java `KmipTtlvTest.encodesAndParsesNestedTtlvWithoutPlaintextTransformation`。

English
--------
Unit tests for the KMIP TTLV codec. Verifies
encode/decode round-trip for all 5 types (STRUCTURE /
INTEGER / ENUMERATION / TEXT / BYTE_STRING), nested
structures, and error paths. 1:1 with Java
`KmipTtlvTest`.
"""

from __future__ import annotations

import struct

import pytest

from atlas_richie.secret_kmip import ttlv


class TestKmipTtlvElement:
    def test_integer_round_trip(self) -> None:
        encoded = ttlv.integer(0x42006A, 5)
        elements = ttlv.children(encoded)
        assert len(elements) == 1
        assert elements[0].tag == 0x42006A
        assert elements[0].type == ttlv.INTEGER
        assert struct.unpack(">i", elements[0].value)[0] == 5

    def test_enumeration_round_trip(self) -> None:
        encoded = ttlv.enumeration(0x42005C, 31)
        elements = ttlv.children(encoded)
        assert len(elements) == 1
        assert elements[0].type == ttlv.ENUMERATION
        assert struct.unpack(">i", elements[0].value)[0] == 31

    def test_text_round_trip(self) -> None:
        encoded = ttlv.text(0x420094, "key-1")
        elements = ttlv.children(encoded)
        assert len(elements) == 1
        assert elements[0].type == ttlv.TEXT
        assert elements[0].value.decode("utf-8") == "key-1"

    def test_byte_string_round_trip(self) -> None:
        encoded = ttlv.bytes_(0x4200C2, b"\x00\x01\x02\x03")
        elements = ttlv.children(encoded)
        assert elements[0].type == ttlv.BYTE_STRING
        assert elements[0].value == b"\x00\x01\x02\x03"

    def test_zero_length_byte_string_pads_correctly(self) -> None:
        encoded = ttlv.bytes_(0x4200C2, b"")
        # 8-byte header + 0 padding = 8 bytes total
        assert len(encoded) == 8

    def test_value_padded_to_8_byte_boundary(self) -> None:
        # 1-byte value → 7 bytes padding
        encoded = ttlv.bytes_(0x4200C2, b"x")
        assert len(encoded) == 8 + 1 + 7  # header + value + pad

    def test_value_exactly_8_bytes_no_padding(self) -> None:
        encoded = ttlv.bytes_(0x4200C2, b"01234567")
        assert len(encoded) == 8 + 8  # header + value, no pad

    def test_invalid_tag_raises(self) -> None:
        with pytest.raises(ValueError):
            ttlv.element(0x1000000, ttlv.BYTE_STRING, b"x")


class TestKmipTtlvStructure:
    def test_nested_structure_round_trip(self) -> None:
        message = ttlv.structure(
            0x420078,
            ttlv.structure(
                0x420079,
                ttlv.text(0x420094, "key-1"),
                ttlv.bytes_(0x420022, b"payload"),
            ),
        )
        elements = ttlv.children(message)
        assert len(elements) == 1
        assert elements[0].tag == 0x420078
        assert elements[0].type == ttlv.STRUCTURE

        # Recursive decode
        assert ttlv.first(elements, 0x420094, ttlv.TEXT) == b"key-1"
        assert ttlv.first(elements, 0x420022, ttlv.BYTE_STRING) == b"payload"

    def test_multiple_siblings(self) -> None:
        message = ttlv.structure(
            0x42000F,
            ttlv.enumeration(0x42005C, 31),
            ttlv.enumeration(0x42007F, 0),
            ttlv.structure(
                0x42007C,
                ttlv.bytes_(0x4200C2, b"data"),
            ),
        )
        elements = ttlv.children(message)
        assert len(elements) == 1
        inner = ttlv.children(elements[0].value)
        assert len(inner) == 3
        # first() is recursive; the second OPERATION element wins
        # (only one expected). RESULT_STATUS = 0
        op = ttlv.first(elements, 0x42005C, ttlv.ENUMERATION)
        assert struct.unpack(">i", op)[0] == 31
        status = ttlv.first(elements, 0x42007F, ttlv.ENUMERATION)
        assert struct.unpack(">i", status)[0] == 0

    def test_invalid_truncated_stream_raises(self) -> None:
        # header claims 100 bytes but only 10 follow
        encoded = b"\x42\x00\x78\x08" + struct.pack(">I", 100) + b"x" * 10
        with pytest.raises(ValueError):
            ttlv.children(encoded)

    def test_invalid_negative_length_raises(self) -> None:
        encoded = b"\x42\x00\x78\x08" + struct.pack(">I", 0xFFFFFFFF) + b"x" * 8
        with pytest.raises(ValueError):
            ttlv.children(encoded)

    def test_trailing_bytes_raises(self) -> None:
        encoded = ttlv.bytes_(0x4200C2, b"x") + b"junk"
        with pytest.raises(ValueError):
            ttlv.children(encoded)


__all__ = []
