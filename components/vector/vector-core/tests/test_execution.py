"""执行守卫：并发许可、超时、取消、异常回传。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError
from datetime import timedelta

import pytest

from atlas_richie.vector_core import (
    DEFAULT_MAX_CONCURRENT,
    VectorQueryErrorCode,
    VectorQueryExecutionGuard,
    VectorQueryValidationException,
)


class TestAdmission:
    def test_default_concurrency(self) -> None:
        assert VectorQueryExecutionGuard().max_concurrent == DEFAULT_MAX_CONCURRENT

    @pytest.mark.parametrize("value", [0, -1, 1025])
    def test_invalid_concurrency(self, value) -> None:
        with pytest.raises(ValueError):
            VectorQueryExecutionGuard(value)

    def test_returns_action_value(self) -> None:
        assert VectorQueryExecutionGuard().execute(timedelta(seconds=1), lambda: 42) == 42

    def test_permit_is_released_after_success(self) -> None:
        guard = VectorQueryExecutionGuard(1)
        for _ in range(3):
            assert guard.execute(timedelta(seconds=1), lambda: "ok") == "ok"

    def test_permit_is_released_after_failure(self) -> None:
        guard = VectorQueryExecutionGuard(1)

        def boom() -> None:
            raise RuntimeError("down")

        for _ in range(3):
            with pytest.raises(RuntimeError, match="down"):
                guard.execute(timedelta(seconds=1), boom)

    def test_concurrency_limit_is_enforced(self) -> None:
        guard = VectorQueryExecutionGuard(1)
        started = threading.Event()
        release = threading.Event()

        def slow() -> str:
            started.set()
            release.wait(5)
            return "done"

        worker = threading.Thread(
            target=lambda: guard.execute(timedelta(seconds=5), slow), daemon=True
        )
        worker.start()
        assert started.wait(2)
        try:
            with pytest.raises(VectorQueryValidationException) as info:
                guard.execute(timedelta(seconds=1), lambda: "second")
            assert info.value.code is VectorQueryErrorCode.CONCURRENCY_LIMIT
        finally:
            release.set()
            worker.join(5)

    def test_permit_survives_timeout_until_worker_finishes(self) -> None:
        """CPython 无法强杀线程：超时后许可仍被占用，直到 action 自然结束。"""
        guard = VectorQueryExecutionGuard(1)
        release = threading.Event()
        started = threading.Event()

        def slow() -> None:
            started.set()
            release.wait(5)

        worker = threading.Thread(
            target=lambda: _swallow(guard, timedelta(milliseconds=100), slow), daemon=True
        )
        worker.start()
        assert started.wait(2)
        worker.join(5)
        with pytest.raises(VectorQueryValidationException) as info:
            guard.execute(timedelta(seconds=1), lambda: None)
        assert info.value.code is VectorQueryErrorCode.CONCURRENCY_LIMIT
        release.set()
        time.sleep(0.1)
        assert guard.execute(timedelta(seconds=1), lambda: "free") == "free"


def _swallow(guard, timeout, action) -> None:
    try:
        guard.execute(timeout, action)
    except VectorQueryValidationException:
        pass


class TestTimeout:
    @pytest.mark.parametrize("timeout", [timedelta(0), timedelta(seconds=-1), None])
    def test_invalid_timeout(self, timeout) -> None:
        with pytest.raises(ValueError, match="timeout must be positive"):
            VectorQueryExecutionGuard().execute(timeout, lambda: None)

    def test_slow_action_times_out(self) -> None:
        release = threading.Event()
        guard = VectorQueryExecutionGuard(2)
        try:
            with pytest.raises(VectorQueryValidationException) as info:
                guard.execute(timedelta(milliseconds=100), lambda: release.wait(5))
            assert info.value.code is VectorQueryErrorCode.TIMEOUT
        finally:
            release.set()

    def test_fast_action_beats_timeout(self) -> None:
        assert (
            VectorQueryExecutionGuard().execute(timedelta(milliseconds=500), lambda: 1) == 1
        )


class TestCancellation:
    def test_cancelled_before_start(self) -> None:
        with pytest.raises(CancelledError):
            VectorQueryExecutionGuard().execute(
                timedelta(seconds=1), lambda: 1, cancelled=lambda: True
            )

    def test_cancelled_mid_flight(self) -> None:
        cancel = threading.Event()
        started = threading.Event()
        release = threading.Event()

        def slow() -> None:
            started.set()
            release.wait(5)

        guard = VectorQueryExecutionGuard(2)
        errors: list[BaseException] = []

        def run() -> None:
            try:
                guard.execute(
                    timedelta(seconds=5), slow, cancelled=cancel.is_set
                )
            except BaseException as error:  # noqa: BLE001
                errors.append(error)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        assert started.wait(2)
        cancel.set()
        worker.join(5)
        release.set()
        assert len(errors) == 1
        assert isinstance(errors[0], CancelledError)

    def test_non_callable_cancelled_rejected(self) -> None:
        with pytest.raises(ValueError):
            VectorQueryExecutionGuard().execute(
                timedelta(seconds=1), lambda: None, cancelled=True
            )


class TestErrorPropagation:
    def test_runtime_error_is_reraised_unchanged(self) -> None:
        error = KeyError("missing")

        def boom() -> None:
            raise error

        with pytest.raises(KeyError) as info:
            VectorQueryExecutionGuard().execute(timedelta(seconds=1), boom)
        assert info.value is error

    def test_non_callable_action_rejected(self) -> None:
        with pytest.raises(ValueError, match="action is required"):
            VectorQueryExecutionGuard().execute(timedelta(seconds=1), None)