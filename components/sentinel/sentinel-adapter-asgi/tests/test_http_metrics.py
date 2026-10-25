"""Tests for bounded, completed-response metrics in the pure ASGI adapter."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from typing import Any

from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.ports.system_metric_sampler import SystemSnapshot
from atlas_richie.sentinel.reporting import (
    HttpMetricSnapshot,
    MetricCapture,
    MetricCaptureSource,
    MetricsCaptureAdapter,
    MetricsReportingBuffer,
)
from atlas_richie.sentinel_adapter_asgi import (
    ASGIHttpMetrics,
    ASGIHttpMetricsSnapshot,
    SentinelASGIMiddleware,
)


def _scope() -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": "/metrics-should-not-store-this-path",
        "headers": [(b"x-user", b"private-user")],
        "query_string": b"secret=value",
    }


async def _receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"request-body", "more_body": False}


class _Recorder:
    def __init__(self, *, fail_on_final_body: bool = False) -> None:
        self.messages: list[dict[str, Any]] = []
        self.fail_on_final_body = fail_on_final_body

    async def __call__(self, message: dict[str, Any]) -> None:
        if (
            self.fail_on_final_body
            and message.get("type") == "http.response.body"
            and not message.get("more_body", False)
        ):
            raise OSError("downstream send failed")
        self.messages.append(message)


def _response_app(*, status: int = 200, finish: bool = True):
    async def app(scope: dict, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"response-body",
                "more_body": not finish,
            }
        )

    return app


class ASGIHttpMetricsRegistryTest(unittest.TestCase):
    def test_snapshot_contains_bounded_histogram_and_no_request_dimensions(
        self,
    ) -> None:
        metrics = ASGIHttpMetrics(
            latency_bucket_bounds_ns=(10, 20), as_of_ns=lambda: 123
        )
        metrics.record_completed_request(duration_ns=10)
        metrics.record_completed_request(duration_ns=11)
        metrics.record_completed_request(duration_ns=21)

        snapshot = metrics.snapshot()

        self.assertEqual(snapshot.completed_requests, 3)
        self.assertEqual(snapshot.as_of_ns, 123)
        self.assertEqual(snapshot.latency_histogram.bucket_counts, (1, 1, 1))
        self.assertEqual(snapshot.latency_histogram.total_ns, 42)
        self.assertIsNone(snapshot.latency_histogram.p95_upper_bound_ns)
        self.assertEqual(
            {item.name for item in fields(snapshot)},
            {"completed_requests", "latency_histogram", "as_of_ns"},
        )

    def test_invalid_duration_is_rejected_without_mutating_snapshot(self) -> None:
        metrics = ASGIHttpMetrics()

        for invalid_duration in (-1, True, 1.5):
            with (
                self.subTest(duration=invalid_duration),
                self.assertRaises(ValueError),
            ):
                metrics.record_completed_request(duration_ns=invalid_duration)  # type: ignore[arg-type]

        self.assertEqual(metrics.snapshot().completed_requests, 0)

    def test_concurrent_updates_keep_counter_and_histogram_consistent(self) -> None:
        metrics = ASGIHttpMetrics(latency_bucket_bounds_ns=(100,))
        workers = 8
        samples_per_worker = 100

        def record_samples() -> None:
            for duration_ns in range(samples_per_worker):
                metrics.record_completed_request(duration_ns=duration_ns)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(lambda _: record_samples(), range(workers)))

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot.completed_requests, workers * samples_per_worker)
        self.assertEqual(
            snapshot.latency_histogram.sample_count, workers * samples_per_worker
        )
        self.assertEqual(
            sum(snapshot.latency_histogram.bucket_counts), workers * samples_per_worker
        )


class ASGIHttpMetricsMiddlewareTest(unittest.IsolatedAsyncioTestCase):
    async def test_completed_error_response_is_included_in_metrics(self) -> None:
        for status in (400, 404, 429, 503):
            with self.subTest(status=status):
                metrics = ASGIHttpMetrics()
                engine = SentinelEngine()
                async with engine:
                    middleware = SentinelASGIMiddleware(
                        app=_response_app(status=status),
                        engine=engine,
                        http_metrics=metrics,
                    )
                    recorder = _Recorder()
                    await middleware(_scope(), _receive, recorder)

                self.assertEqual(recorder.messages[0]["status"], status)
                self.assertEqual(metrics.snapshot().completed_requests, 1)
                self.assertEqual(metrics.snapshot().latency_histogram.sample_count, 1)

    async def test_completed_response_is_captured_as_an_internal_typed_snapshot(
        self,
    ) -> None:
        for status in (400, 503):
            with self.subTest(status=status):
                source = ASGIHttpMetrics(as_of_ns=lambda: 123)
                buffer = MetricsReportingBuffer(capacity=2)
                adapter = MetricsCaptureAdapter(buffer)
                engine = SentinelEngine()
                async with engine:
                    middleware = SentinelASGIMiddleware(
                        app=_response_app(status=status),
                        engine=engine,
                        http_metrics=adapter.wrap_http_metrics(source),
                    )
                    recorder = _Recorder()
                    await middleware(_scope(), _receive, recorder)

                (capture,) = buffer.drain()
                self.assertEqual(recorder.messages[0]["status"], status)
                self.assertIs(capture.source, MetricCaptureSource.HTTP)
                self.assertIsInstance(capture.snapshot, HttpMetricSnapshot)
                self.assertEqual(capture.snapshot.completed_requests, 1)
                self.assertEqual(capture.snapshot.as_of_ns, 123)
                self.assertEqual(capture.snapshot.latency_histogram.sample_count, 1)
                self.assertNotIn("private-user", repr(capture))
                self.assertNotIn("metrics-should-not-store-this-path", repr(capture))

    async def test_incomplete_response_does_not_enqueue_http_capture(self) -> None:
        source = ASGIHttpMetrics()
        buffer = MetricsReportingBuffer(capacity=2)
        adapter = MetricsCaptureAdapter(buffer)
        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=_response_app(finish=False),
                engine=engine,
                http_metrics=adapter.wrap_http_metrics(source),
            )
            await middleware(_scope(), _receive, _Recorder())

        self.assertEqual(source.snapshot().completed_requests, 0)
        self.assertEqual(buffer.pending_count, 0)
        self.assertEqual(adapter.enqueue_failure_count, 0)

    async def test_failed_final_send_does_not_enqueue_http_capture(self) -> None:
        source = ASGIHttpMetrics()
        buffer = MetricsReportingBuffer(capacity=2)
        adapter = MetricsCaptureAdapter(buffer)
        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=_response_app(),
                engine=engine,
                http_metrics=adapter.wrap_http_metrics(source),
            )
            with self.assertRaisesRegex(OSError, "downstream send failed"):
                await middleware(_scope(), _receive, _Recorder(fail_on_final_body=True))

        self.assertEqual(source.snapshot().completed_requests, 0)
        self.assertEqual(buffer.pending_count, 0)
        self.assertEqual(adapter.enqueue_failure_count, 0)

    async def test_snapshot_failure_is_isolated_after_response_completion(self) -> None:
        class SnapshotFailureMetrics(ASGIHttpMetrics):
            def snapshot(self) -> ASGIHttpMetricsSnapshot:
                raise RuntimeError("private snapshot details")

        source = SnapshotFailureMetrics()
        buffer = MetricsReportingBuffer(capacity=2)
        adapter = MetricsCaptureAdapter(buffer)
        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=_response_app(status=503),
                engine=engine,
                http_metrics=adapter.wrap_http_metrics(source),
            )
            recorder = _Recorder()
            await middleware(_scope(), _receive, recorder)

        self.assertEqual(recorder.messages[0]["status"], 503)
        self.assertEqual(buffer.pending_count, 0)
        self.assertEqual(adapter.enqueue_failure_count, 1)
        self.assertEqual(adapter.last_enqueue_error_type, "RuntimeError")

    async def test_record_failure_is_isolated_after_response_completion(self) -> None:
        class RecordFailureMetrics(ASGIHttpMetrics):
            def record_completed_request(self, *, duration_ns: int) -> None:
                raise RuntimeError("private record details")

        source = RecordFailureMetrics()
        buffer = MetricsReportingBuffer(capacity=2)
        adapter = MetricsCaptureAdapter(buffer)
        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=_response_app(status=503),
                engine=engine,
                http_metrics=adapter.wrap_http_metrics(source),
            )
            recorder = _Recorder()
            await middleware(_scope(), _receive, recorder)

        self.assertEqual(recorder.messages[0]["status"], 503)
        self.assertEqual(recorder.messages[-1]["body"], b"response-body")
        self.assertEqual(buffer.pending_count, 0)
        self.assertEqual(adapter.enqueue_failure_count, 1)
        self.assertEqual(adapter.last_enqueue_error_type, "RuntimeError")
        self.assertNotIn(
            "private record details", repr(adapter.last_enqueue_error_type)
        )

    async def test_full_local_buffer_rejection_does_not_fail_http_response(
        self,
    ) -> None:
        source = ASGIHttpMetrics()
        buffer = MetricsReportingBuffer(capacity=1)
        adapter = MetricsCaptureAdapter(buffer)
        # Occupy the sole slot with a different source identity.
        self.assertTrue(
            buffer.try_enqueue(
                MetricCapture(
                    MetricCaptureSource.SYSTEM,
                    SystemSnapshot(None, None, None, None, None, 1),
                )
            )
        )
        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=_response_app(status=503),
                engine=engine,
                http_metrics=adapter.wrap_http_metrics(source),
            )
            recorder = _Recorder()
            await middleware(_scope(), _receive, recorder)

        self.assertEqual(recorder.messages[0]["status"], 503)
        self.assertEqual(source.snapshot().completed_requests, 1)
        self.assertEqual(adapter.rejected_capture_count, 1)
        self.assertEqual(adapter.enqueue_failure_count, 0)
        self.assertEqual(len(buffer.drain()), 1)

    async def test_incomplete_response_is_not_counted(self) -> None:
        metrics = ASGIHttpMetrics()
        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=_response_app(finish=False), engine=engine, http_metrics=metrics
            )
            await middleware(_scope(), _receive, _Recorder())

        self.assertEqual(metrics.snapshot().completed_requests, 0)

    async def test_response_with_trailers_counts_after_final_trailer(self) -> None:
        metrics = ASGIHttpMetrics()

        async def response_with_trailers(scope: dict, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                    "trailers": True,
                }
            )
            await send({"type": "http.response.body", "body": b"body"})
            await send(
                {
                    "type": "http.response.trailers",
                    "headers": [(b"x-checksum", b"ignored")],
                    "more_trailers": False,
                }
            )

        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=response_with_trailers, engine=engine, http_metrics=metrics
            )
            await middleware(_scope(), _receive, _Recorder())

        self.assertEqual(metrics.snapshot().completed_requests, 1)

    async def test_response_waiting_for_trailers_is_not_counted_early(self) -> None:
        metrics = ASGIHttpMetrics()

        async def response_missing_trailers(
            scope: dict, receive: Any, send: Any
        ) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                    "trailers": True,
                }
            )
            await send({"type": "http.response.body", "body": b"body"})

        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=response_missing_trailers, engine=engine, http_metrics=metrics
            )
            await middleware(_scope(), _receive, _Recorder())

        self.assertEqual(metrics.snapshot().completed_requests, 0)

    async def test_successful_pathsend_response_is_counted_without_retaining_path(
        self,
    ) -> None:
        metrics = ASGIHttpMetrics()

        async def pathsend_app(scope: dict, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {
                    "type": "http.response.pathsend",
                    "path": "/private/files/customer-export.csv",
                }
            )

        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=pathsend_app, engine=engine, http_metrics=metrics
            )
            await middleware(_scope(), _receive, _Recorder())

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot.completed_requests, 1)
        self.assertNotIn("customer-export.csv", repr(snapshot))

    async def test_failed_pathsend_is_not_counted(self) -> None:
        metrics = ASGIHttpMetrics()

        async def pathsend_app(scope: dict, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {
                    "type": "http.response.pathsend",
                    "path": "/private/files/customer-export.csv",
                }
            )

        class FailingPathsendRecorder(_Recorder):
            async def __call__(self, message: dict[str, Any]) -> None:
                if message.get("type") == "http.response.pathsend":
                    raise OSError("path send failed")
                await super().__call__(message)

        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=pathsend_app, engine=engine, http_metrics=metrics
            )
            with self.assertRaisesRegex(OSError, "path send failed"):
                await middleware(_scope(), _receive, FailingPathsendRecorder())

        self.assertEqual(metrics.snapshot().completed_requests, 0)

    async def test_failed_final_send_is_not_counted(self) -> None:
        metrics = ASGIHttpMetrics()
        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=_response_app(), engine=engine, http_metrics=metrics
            )
            with self.assertRaisesRegex(OSError, "downstream send failed"):
                await middleware(_scope(), _receive, _Recorder(fail_on_final_body=True))

        self.assertEqual(metrics.snapshot().completed_requests, 0)

    async def test_downstream_exception_before_completion_is_not_counted(self) -> None:
        metrics = ASGIHttpMetrics()

        async def broken_app(scope: dict, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise RuntimeError("application failed before final body")

        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=broken_app, engine=engine, http_metrics=metrics
            )
            with self.assertRaisesRegex(RuntimeError, "failed before final body"):
                await middleware(_scope(), _receive, _Recorder())

        self.assertEqual(metrics.snapshot().completed_requests, 0)

    async def test_non_http_scope_does_not_change_metrics(self) -> None:
        metrics = ASGIHttpMetrics()

        async def websocket_app(scope: dict, receive: Any, send: Any) -> None:
            await send({"type": "websocket.accept"})

        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=websocket_app, engine=engine, http_metrics=metrics
            )
            await middleware({"type": "websocket"}, _receive, _Recorder())

        self.assertEqual(metrics.snapshot().completed_requests, 0)

    async def test_final_body_is_recorded_only_once(self) -> None:
        metrics = ASGIHttpMetrics()

        async def duplicate_final_app(scope: dict, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"done"})
            await send({"type": "http.response.body", "body": b"invalid-extra"})

        engine = SentinelEngine()
        async with engine:
            middleware = SentinelASGIMiddleware(
                app=duplicate_final_app, engine=engine, http_metrics=metrics
            )
            await middleware(_scope(), _receive, _Recorder())

        self.assertEqual(metrics.snapshot().completed_requests, 1)


if __name__ == "__main__":
    unittest.main()
