"""SEN-CB-001 (part: http) — OutcomeClassifier full coverage (M4.4).

中文
----
PLANNING §M4.4 要求:把连接错误 / 超时 / 5xx / 4xx / 2xx / 取消分别
映射 Outcome;**HTTPX 5xx 不会自动抛** ``HTTPStatusError``,
Classifier 必须**显式**读 ``response.status_code``。

本文件覆盖:

- 6 种 outcome 各自测试(2xx / 4xx / 5xx / ConnectError /
  TimeoutException / CancelledError)
- 显式 ``httpx.Response(503)`` 构造,断言 Classifier 读
  status_code,不走 ``raise_for_status`` 路径
- 4xx 默认**不**计为下游失败
- 自定义 Classifier 注入
- DefaultClassifier 的边界 case(response 是 None / None 状态码 /
  非 httpx 异常 / RequestError 子类)

English
--------
SEN-CB-001 (part: http) — OutcomeClassifier full coverage (M4.4).

PLANNING §M4.4 requires: classify connect errors / timeouts / 5xx / 4xx
/ 2xx / cancel into outcomes. **HTTPX 5xx does not auto-raise**
``HTTPStatusError``; Classifier must explicitly read
``response.status_code``.

This file covers:

- 6 outcome paths (2xx / 4xx / 5xx / ConnectError / TimeoutException /
  CancelledError).
- Explicit ``httpx.Response(503)`` construction asserting Classifier
  reads status_code (not the ``raise_for_status`` path).
- 4xx default is **not** downstream failure.
- Custom classifier injection.
- DefaultClassifier edge cases (response is None / None status_code /
  non-httpx exception / RequestError subclasses).
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

import httpx

from atlas_richie.sentinel.model.outcome import OutcomeKind
from atlas_richie.sentinel_adapter_httpx import (
    DefaultOutcomeClassifier,
    OutcomeClassifier,
    classify_outcome,
)


# ---------------------------------------------------------------------------
# DefaultOutcomeClassifier — full 6-path coverage
# ---------------------------------------------------------------------------


class DefaultClassifierHappyPathTest(unittest.TestCase):
    def test_2xx_is_succeeded(self) -> None:
        for code in (200, 201, 204, 299):
            response = httpx.Response(code, request=httpx.Request("GET", "http://x/"))
            self.assertEqual(
                DefaultOutcomeClassifier().classify(response),
                OutcomeKind.SUCCEEDED,
                f"code={code}",
            )

    def test_4xx_default_is_succeeded_not_failed(self) -> None:
        # Per PLANNING §M4.4: 4xx is business error, NOT downstream
        # failure → must NOT trigger circuit breaker.
        for code in (400, 401, 403, 404, 409, 422, 429):
            response = httpx.Response(code, request=httpx.Request("GET", "http://x/"))
            self.assertEqual(
                DefaultOutcomeClassifier().classify(response),
                OutcomeKind.SUCCEEDED,
                f"code={code}",
            )

    def test_5xx_is_failed(self) -> None:
        for code in (500, 502, 503, 504, 599):
            response = httpx.Response(code, request=httpx.Request("GET", "http://x/"))
            self.assertEqual(
                DefaultOutcomeClassifier().classify(response),
                OutcomeKind.FAILED,
                f"code={code}",
            )

    def test_3xx_is_succeeded_by_default(self) -> None:
        # Redirects are not failures; 304 Not Modified is success.
        # HTTPX may auto-follow, but at the classifier level, 3xx
        # is not failure.
        for code in (301, 302, 304, 307, 308):
            response = httpx.Response(code, request=httpx.Request("GET", "http://x/"))
            self.assertEqual(
                DefaultOutcomeClassifier().classify(response),
                OutcomeKind.SUCCEEDED,
                f"code={code}",
            )


class DefaultClassifierNetworkErrorTest(unittest.TestCase):
    def test_connect_error_is_failed(self) -> None:
        exc = httpx.ConnectError("connection refused")
        self.assertEqual(
            DefaultOutcomeClassifier().classify(exc),
            OutcomeKind.FAILED,
        )

    def test_timeout_exception_is_failed(self) -> None:
        exc = httpx.TimeoutException("timed out")
        self.assertEqual(
            DefaultOutcomeClassifier().classify(exc),
            OutcomeKind.FAILED,
        )

    def test_connect_timeout_is_failed(self) -> None:
        exc = httpx.ConnectTimeout("connect timed out")
        self.assertEqual(
            DefaultOutcomeClassifier().classify(exc),
            OutcomeKind.FAILED,
        )

    def test_read_timeout_is_failed(self) -> None:
        exc = httpx.ReadTimeout("read timed out")
        self.assertEqual(
            DefaultOutcomeClassifier().classify(exc),
            OutcomeKind.FAILED,
        )

    def test_remote_protocol_error_is_failed(self) -> None:
        exc = httpx.RemoteProtocolError("protocol error")
        self.assertEqual(
            DefaultOutcomeClassifier().classify(exc),
            OutcomeKind.FAILED,
        )

    def test_request_error_is_failed(self) -> None:
        # Generic httpx.RequestError parent covers any HTTPX request error.
        exc = httpx.RequestError("generic")
        self.assertEqual(
            DefaultOutcomeClassifier().classify(exc),
            OutcomeKind.FAILED,
        )


class DefaultClassifierCancelTest(unittest.TestCase):
    def test_cancelled_error_is_cancelled(self) -> None:
        exc = asyncio.CancelledError("user cancelled")
        self.assertEqual(
            DefaultOutcomeClassifier().classify(exc),
            OutcomeKind.CANCELLED,
        )


# ---------------------------------------------------------------------------
# HTTPX 5xx explicit: response.status_code is read, NOT raise_for_status
# ---------------------------------------------------------------------------


class HttpX5xxExplicitReadTest(unittest.TestCase):
    """Per PLANNING §M4.4: HTTPX 5xx does NOT auto-raise HTTPStatusError.
    Classifier must read response.status_code directly."""

    def test_response_503_has_no_raised_exception(self) -> None:
        # Sanity: httpx.Response(503) does not raise on construction.
        response = httpx.Response(503, request=httpx.Request("GET", "http://x/"))
        # No exception raised.
        self.assertEqual(response.status_code, 503)
        # And we can read it directly.
        result = DefaultOutcomeClassifier().classify(response)
        self.assertEqual(result, OutcomeKind.FAILED)

    def test_classifier_does_not_call_raise_for_status(self) -> None:
        # Build a mock that records whether raise_for_status was called.
        from unittest.mock import MagicMock
        response = MagicMock(spec=httpx.Response)
        response.status_code = 503
        result = DefaultOutcomeClassifier().classify(response)
        self.assertEqual(result, OutcomeKind.FAILED)
        response.raise_for_status.assert_not_called()

    def test_classifier_4xx_503_misclassification(self) -> None:
        # Defensive: a 4xx code (e.g. 404) must NOT be classified as
        # FAILED, even though raise_for_status() would also raise.
        response = httpx.Response(404, request=httpx.Request("GET", "http://x/"))
        result = DefaultOutcomeClassifier().classify(response)
        self.assertEqual(result, OutcomeKind.SUCCEEDED)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class DefaultClassifierEdgeCasesTest(unittest.TestCase):
    def test_response_with_none_status_code(self) -> None:
        # Defensive: a malformed response might have status_code = None.
        response = httpx.Response(200, request=httpx.Request("GET", "http://x/"))
        response.status_code = None  # type: ignore[assignment]
        # Classifier should not crash; treat as FAILED (unknown).
        result = DefaultOutcomeClassifier().classify(response)
        self.assertEqual(result, OutcomeKind.FAILED)

    def test_non_httpx_exception(self) -> None:
        # A plain RuntimeError (not httpx) is still classified as FAILED.
        exc = RuntimeError("downstream boom")
        result = DefaultOutcomeClassifier().classify(exc)
        self.assertEqual(result, OutcomeKind.FAILED)

    def test_plain_exception_subclass(self) -> None:
        # Custom exception from the user's code.
        class MyError(Exception):
            pass

        result = DefaultOutcomeClassifier().classify(MyError("custom"))
        self.assertEqual(result, OutcomeKind.FAILED)

    def test_base_exception_not_swallowed(self) -> None:
        # KeyboardInterrupt and SystemExit are BaseException subclasses
        # (not Exception). The classifier receives the exception and
        # must return FAILED. The CALLER is responsible for not
        # swallowing these upstream.
        result = DefaultOutcomeClassifier().classify(KeyboardInterrupt())
        self.assertEqual(result, OutcomeKind.FAILED)


# ---------------------------------------------------------------------------
# Custom classifier injection
# ---------------------------------------------------------------------------


class CustomClassifierTest(unittest.TestCase):
    def test_custom_classifier_called(self) -> None:
        calls: list[Any] = []

        class CustomClassifier:
            def classify(self, response_or_exc: Any) -> OutcomeKind:
                calls.append(response_or_exc)
                # Custom rule: 429 is FAILED.
                if isinstance(response_or_exc, httpx.Response):
                    if response_or_exc.status_code == 429:
                        return OutcomeKind.FAILED
                return OutcomeKind.SUCCEEDED

        clf = CustomClassifier()
        response = httpx.Response(429, request=httpx.Request("GET", "http://x/"))
        result = clf.classify(response)
        self.assertEqual(result, OutcomeKind.FAILED)
        self.assertEqual(len(calls), 1)

    def test_custom_classifier_can_treat_5xx_as_success(self) -> None:
        # A user might want 5xx to be SUCCESS (e.g. graceful degradation
        # from upstream). The classifier is a Strategy; default is
        # overridable.
        class LenientClassifier:
            def classify(self, response_or_exc: Any) -> OutcomeKind:
                if isinstance(response_or_exc, Exception):
                    return OutcomeKind.FAILED
                if response_or_exc.status_code >= 500:
                    return OutcomeKind.SUCCEEDED  # treat 5xx as success
                return OutcomeKind.SUCCEEDED

        response = httpx.Response(503, request=httpx.Request("GET", "http://x/"))
        result = LenientClassifier().classify(response)
        self.assertEqual(result, OutcomeKind.SUCCEEDED)

    def test_default_classifier_satisfies_protocol(self) -> None:
        # DefaultOutcomeClassifier is a runtime-checkable implementation
        # of OutcomeClassifier Protocol.
        clf = DefaultOutcomeClassifier()
        self.assertIsInstance(clf, OutcomeClassifier)


# ---------------------------------------------------------------------------
# Backward-compat shim: classify_outcome()
# ---------------------------------------------------------------------------


class ClassifyOutcomeCompatTest(unittest.TestCase):
    """The module-level ``classify_outcome(response)`` is the historical
    convenience helper; it must stay available and behave identically
    to ``DefaultOutcomeClassifier().classify(response)``."""

    def test_2xx(self) -> None:
        r = httpx.Response(200, request=httpx.Request("GET", "http://x/"))
        self.assertEqual(classify_outcome(r), "succeeded")

    def test_4xx(self) -> None:
        r = httpx.Response(404, request=httpx.Request("GET", "http://x/"))
        self.assertEqual(classify_outcome(r), "succeeded")

    def test_5xx(self) -> None:
        r = httpx.Response(503, request=httpx.Request("GET", "http://x/"))
        self.assertEqual(classify_outcome(r), "failed")

    def test_exception(self) -> None:
        self.assertEqual(
            classify_outcome(httpx.ConnectError("x")), "failed"
        )

    def test_5xx_uses_status_code_not_raise_for_status(self) -> None:
        # Verify the compat shim does NOT call raise_for_status either.
        from unittest.mock import MagicMock
        response = MagicMock(spec=httpx.Response)
        response.status_code = 503
        self.assertEqual(classify_outcome(response), "failed")
        response.raise_for_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
