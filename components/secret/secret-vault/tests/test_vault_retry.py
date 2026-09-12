"""Unit tests for `VaultRetryExecutor` transient classification.

中文
----
覆盖 `_is_transient` 对 network 错误 / 5xx / 429 / 4xx 的判断。
不需要 Vault。

English
--------
Unit tests for transient-failure classification. No Vault
required; the test injects synthetic exceptions with
`status_code` attributes.
"""

from __future__ import annotations

import time

import hvac
import pytest
import requests

from atlas_richie.secret_vault.retry import (
    VaultRetryExecutor,
    _is_transient,
    _retry_after_seconds,
)


def test_succeeds_first_try() -> None:
    exe = VaultRetryExecutor(max_attempts=3)
    assert exe.execute(lambda: 42) == 42


def test_retries_connection_error_then_succeeds() -> None:
    exe = VaultRetryExecutor(max_attempts=3, base_backoff_seconds=0.01)
    calls = [0]

    def flaky() -> str:
        calls[0] += 1
        if calls[0] < 3:
            raise requests.exceptions.ConnectionError("net down")
        return "ok"

    start = time.time()
    assert exe.execute(flaky) == "ok"
    elapsed = time.time() - start
    assert calls[0] == 3
    # Two backoffs of at most 100ms each — well under 2 seconds.
    assert elapsed < 2.0


def test_does_not_retry_4xx() -> None:
    exe = VaultRetryExecutor(max_attempts=3, base_backoff_seconds=0.01)
    calls = [0]

    def forbidden() -> str:
        calls[0] += 1
        err = hvac.exceptions.Forbidden("denied")
        err.status_code = 403
        raise err

    with pytest.raises(hvac.exceptions.Forbidden):
        exe.execute(forbidden)
    assert calls[0] == 1


def test_retries_5xx_then_raises() -> None:
    exe = VaultRetryExecutor(max_attempts=2, base_backoff_seconds=0.01)
    calls = [0]

    def server_error() -> str:
        calls[0] += 1
        err = hvac.exceptions.InternalServerError("boom")
        err.status_code = 500
        raise err

    with pytest.raises(hvac.exceptions.InternalServerError):
        exe.execute(server_error)
    assert calls[0] == 2


def test_is_transient_classifies_hvac_status() -> None:
    err_429 = hvac.exceptions.RateLimitExceeded("slow down")
    err_429.status_code = 429
    assert _is_transient(err_429) is True

    err_500 = hvac.exceptions.InternalServerError("boom")
    err_500.status_code = 500
    assert _is_transient(err_500) is True

    err_403 = hvac.exceptions.Forbidden("no")
    err_403.status_code = 403
    assert _is_transient(err_403) is False

    err_404 = hvac.exceptions.InvalidPath("missing")
    err_404.status_code = 404
    assert _is_transient(err_404) is False


def test_is_transient_classifies_requests() -> None:
    assert _is_transient(requests.exceptions.ConnectionError("net")) is True
    assert _is_transient(requests.exceptions.Timeout("slow")) is True
    assert _is_transient(RuntimeError("other")) is False


def test_retry_after_parses_header() -> None:
    err = hvac.exceptions.InternalServerError("boom")
    err.status_code = 500

    class _Resp:
        headers = {"Retry-After": "2"}

    err.response = _Resp()  # type: ignore[attr-defined]
    assert _retry_after_seconds(err) == 2.0


def test_retry_after_missing_returns_zero() -> None:
    assert _retry_after_seconds(RuntimeError("no header")) == 0.0


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError):
        VaultRetryExecutor(max_attempts=0)
