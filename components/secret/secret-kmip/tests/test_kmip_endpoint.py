"""KMIP endpoint parser + retry policy tests.

中文
----
对位 Java `KmipTransportPolicyTest`:
- `appliesConfiguredConnectAndReadTimeoutsBeforeHandshake`
  → endpoint 解析(host + port + 5696 default)
- `retriesOnlyTransientIoFailuresWithinTheConfiguredBudget`
  → retry policy 对 transient `OSError` 重试,SSL error 不重试

English
--------
Tests endpoint parsing + retry policy. 1:1 with Java
`KmipTransportPolicyTest`.
"""

from __future__ import annotations

import ssl
from unittest.mock import MagicMock

import pytest

from atlas_richie.secret.errors import SecretCryptoException
from atlas_richie.secret_kmip.client import _parse_endpoint, _retry_io


class TestKmipEndpointParser:
    def test_default_port_when_unspecified(self) -> None:
        endpoint = _parse_endpoint("kmips://kmip.example")
        assert endpoint.host == "kmip.example"
        assert endpoint.port == 5696

    def test_explicit_port(self) -> None:
        endpoint = _parse_endpoint("kmips://kmip.example:5697")
        assert endpoint.host == "kmip.example"
        assert endpoint.port == 5697

    def test_ipv4_address(self) -> None:
        endpoint = _parse_endpoint("kmips://10.0.0.5:5696")
        assert endpoint.host == "10.0.0.5"
        assert endpoint.port == 5696

    def test_ipv6_literal(self) -> None:
        endpoint = _parse_endpoint("kmips://[::1]:5696")
        assert endpoint.host == "::1"
        assert endpoint.port == 5696

    def test_https_scheme(self) -> None:
        endpoint = _parse_endpoint("https://kmip.example:5696")
        assert endpoint.host == "kmip.example"

    def test_missing_scheme_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_endpoint("kmip.example:5696")


class TestKmipRetryPolicy:
    def test_retries_transient_io_failure(self) -> None:
        attempts = []

        def op() -> bytes:
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("temporary")
            return b"ok"

        result = _retry_io(3, op)
        assert result == b"ok"
        assert len(attempts) == 3

    def test_succeeds_on_first_attempt(self) -> None:
        attempts = []

        def op() -> bytes:
            attempts.append(1)
            return b"ok"

        result = _retry_io(3, op)
        assert result == b"ok"
        assert len(attempts) == 1

    def test_raises_after_max_attempts(self) -> None:
        attempts = []

        def op() -> bytes:
            attempts.append(1)
            raise OSError("permanent failure")

        with pytest.raises(OSError) as info:
            _retry_io(3, op)
        assert "permanent failure" in str(info.value)
        assert len(attempts) == 3

    def test_does_not_retry_ssl_error(self) -> None:
        attempts = []

        def op() -> bytes:
            attempts.append(1)
            raise ssl.SSLError("untrusted")

        with pytest.raises(ssl.SSLError):
            _retry_io(3, op)
        assert len(attempts) == 1

    def test_max_attempts_at_least_one(self) -> None:
        attempts = []

        def op() -> bytes:
            attempts.append(1)
            return b"ok"

        result = _retry_io(0, op)  # 0 → 1 attempt minimum
        assert result == b"ok"
        assert len(attempts) == 1


__all__ = []
