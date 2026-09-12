"""KMIP response parser tests — status / mismatched-op / ambiguous batch。

中文
----
对位 Java `KmipTtlvTest.parsesOnlySuccessfulMatchingEncryptBatchData` +
`rejectsFailedMismatchedAndAmbiguousResponses`。验证:

- successful Encrypt batch 解析
- result status != 0 → `SEC-PROVIDER-001`
- response operation 不匹配 request → `SEC-PROVIDER-001`
- ambiguous (两个 Batch Item) → `SEC-PROVIDER-001`

English
--------
Tests for the response parser. 1:1 with Java
`KmipTtlvTest.parsesOnlySuccessfulMatchingEncryptBatchData`
+ `rejectsFailedMismatchedAndAmbiguousResponses`.
"""

from __future__ import annotations

import struct

import pytest

from atlas_richie.secret.errors import SecretCryptoException
from atlas_richie.secret_kmip import ttlv
from atlas_richie.secret_kmip.client import _parse_response


_TAG_RESPONSE_MESSAGE = 0x42007B
_TAG_BATCH_ITEM = 0x42000F
_TAG_OPERATION = 0x42005C
_TAG_RESULT_STATUS = 0x42007F
_TAG_RESPONSE_PAYLOAD = 0x42007C
_TAG_DATA = 0x4200C2


def _batch(operation: int, status: int, data: bytes) -> bytes:
    return ttlv.structure(
        _TAG_BATCH_ITEM,
        ttlv.enumeration(_TAG_OPERATION, operation),
        ttlv.enumeration(_TAG_RESULT_STATUS, status),
        ttlv.structure(
            _TAG_RESPONSE_PAYLOAD,
            ttlv.bytes_(_TAG_DATA, data),
        ),
    )


def _response(operation: int, status: int, data: bytes) -> bytes:
    return ttlv.structure(_TAG_RESPONSE_MESSAGE, _batch(operation, status, data))


class TestKmipResponseParser:
    def test_parses_successful_encrypt_response(self) -> None:
        response = _response(31, 0, b"ciphertext")
        assert _parse_response(31, response) == b"ciphertext"

    def test_parses_successful_decrypt_response(self) -> None:
        response = _response(32, 0, b"plaintext-32bytes!!")
        assert _parse_response(32, response) == b"plaintext-32bytes!!"

    def test_rejects_non_zero_result_status(self) -> None:
        response = _response(31, 1, b"untrusted")
        with pytest.raises(SecretCryptoException) as info:
            _parse_response(31, response)
        assert "result status 1" in str(info.value)
        assert "SEC-PROVIDER-001" in str(info.value)

    def test_rejects_mismatched_operation(self) -> None:
        # response says operation=32 but request was 31
        response = _response(32, 0, b"plaintext")
        with pytest.raises(SecretCryptoException) as info:
            _parse_response(31, response)
        assert "does not match" in str(info.value)

    def test_rejects_ambiguous_batch_items(self) -> None:
        first = _batch(31, 0, b"first")
        second = _batch(31, 0, b"second")
        response = ttlv.structure(_TAG_RESPONSE_MESSAGE, first, second)
        with pytest.raises(SecretCryptoException) as info:
            _parse_response(31, response)
        assert "multiple Batch Item" in str(info.value)

    def test_rejects_missing_data(self) -> None:
        # Build a response without DATA element
        response = ttlv.structure(
            _TAG_RESPONSE_MESSAGE,
            ttlv.structure(
                _TAG_BATCH_ITEM,
                ttlv.enumeration(_TAG_OPERATION, 31),
                ttlv.enumeration(_TAG_RESULT_STATUS, 0),
                ttlv.structure(_TAG_RESPONSE_PAYLOAD),
            ),
        )
        with pytest.raises(SecretCryptoException) as info:
            _parse_response(31, response)
        assert "Data" in str(info.value)


__all__ = []
