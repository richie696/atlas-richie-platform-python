import unittest
from unittest.mock import patch

import httpx

from atlas_richie.http import (
    AsyncHttpClient,
    HttpAuditEvent,
    HttpClient,
    HttpClientClosedError,
    HttpClientOptions,
    HttpConnectError,
    HttpDecodeError,
    HttpRequest,
    HttpResponse,
    HttpResponseLimitError,
    HttpStatusError,
    HttpStreamClosedError,
    HttpTimeout,
    MediaType,
    MultipartPart,
    SseEventParser,
)


class _Events:
    def __init__(self) -> None:
        self.events: list[HttpAuditEvent] = []

    def record(self, event: HttpAuditEvent) -> None:
        self.events.append(event)


class _TraceInterceptor:
    def __init__(self, trace: list[str]) -> None:
        self._trace = trace

    def intercept(self, request: HttpRequest, proceed):  # type: ignore[no-untyped-def]
        self._trace.append(f"before:{request.headers['X-Request-Id']}")
        response = proceed(request)
        self._trace.append("after")
        return response


class _ShortCircuitInterceptor:
    def __init__(self, trace: list[str]) -> None:
        self._trace = trace

    def intercept(self, request: HttpRequest, _proceed):  # type: ignore[no-untyped-def]
        self._trace.append("short-circuit")
        return HttpResponse(200, {}, b"cached", request.method, request.url)


class _AsyncTraceInterceptor:
    def __init__(self, trace: list[str]) -> None:
        self._trace = trace

    async def intercept(self, request: HttpRequest, proceed):  # type: ignore[no-untyped-def]
        self._trace.append(f"before:{request.headers['X-Request-Id']}")
        response = await proceed(request)
        self._trace.append("after")
        return response


def _controlled_client(transport: httpx.BaseTransport):
    return patch(
        "atlas_richie.http.client._HttpxClientFactory.create_sync",
        return_value=httpx.Client(transport=transport),
    )


def _controlled_async_client(transport: httpx.AsyncBaseTransport):
    return patch(
        "atlas_richie.http.client._HttpxClientFactory.create_async",
        return_value=httpx.AsyncClient(transport=transport),
    )


class HttpClientContractTests(unittest.TestCase):
    def test_httpx_is_hidden_and_controlled_transport_receives_request_id(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"result": "ok"}, request=request)

        events = _Events()
        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient(audit_sink=events) as client:
                response = client.execute(HttpRequest.get("https://unit.test/json?secret=not-recorded"))

        self.assertEqual({"result": "ok"}, response.json())
        self.assertTrue(captured[0].headers["X-Request-Id"])
        self.assertEqual("https://unit.test/json", events.events[-1].url)
        self.assertNotIn("headers", HttpAuditEvent.__dataclass_fields__)
        self.assertNotIn("body", HttpAuditEvent.__dataclass_fields__)

        import atlas_richie.http as public_api

        self.assertNotIn("httpx", public_api.__all__)

    def test_interceptor_order_and_short_circuit_are_explicit(self) -> None:
        trace: list[str] = []
        events = _Events()
        client = HttpClient(
            interceptors=(_TraceInterceptor(trace), _ShortCircuitInterceptor(trace)),
            audit_sink=events,
        )
        try:
            response = client.execute(HttpRequest.get("https://unit.test/value"))
        finally:
            client.close()

        self.assertEqual(b"cached", response.body)
        self.assertEqual("before", trace[0][:6])
        self.assertEqual(["short-circuit", "after"], trace[1:])
        self.assertEqual(200, events.events[-1].status_code)

    def test_status_decode_response_limit_and_close_are_distinct(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/status":
                return httpx.Response(418, content=b"teapot", request=request)
            if request.url.path == "/invalid-json":
                return httpx.Response(200, content=b"not-json", request=request)
            return httpx.Response(200, content=b"too-large", request=request)

        transport = httpx.MockTransport(handler)
        with _controlled_client(transport):
            with HttpClient() as client:
                with self.assertRaises(HttpStatusError):
                    client.execute(HttpRequest.get("https://unit.test/status")).require_success()
                with self.assertRaises(HttpDecodeError):
                    client.execute(HttpRequest.get("https://unit.test/invalid-json")).json()

        with _controlled_client(transport):
            limited = HttpClient(HttpClientOptions(max_response_bytes=3))
            try:
                with self.assertRaises(HttpResponseLimitError):
                    limited.execute(HttpRequest.get("https://unit.test/large"))
            finally:
                limited.close()
        with self.assertRaises(HttpClientClosedError):
            limited.execute(HttpRequest.get("https://unit.test/json"))

    def test_default_does_not_follow_redirect_and_connect_error_is_mapped(self) -> None:
        def redirect_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "/target"}, request=request)

        with _controlled_client(httpx.MockTransport(redirect_handler)):
            with HttpClient() as client:
                self.assertEqual(302, client.execute(HttpRequest.get("https://unit.test/redirect")).status_code)

        def unavailable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        with _controlled_client(httpx.MockTransport(unavailable)):
            with HttpClient() as client:
                with self.assertRaises(HttpConnectError):
                    client.execute(HttpRequest.get("https://unit.test/unavailable"))

    def test_immutable_fluent_request_owns_query_and_body_semantics(self) -> None:
        original = HttpRequest.post("https://unit.test/widgets")
        request = (
            original.with_query_param("tag", "first")
            .with_query_params((("tag", "second"), ("page", "1")))
            .with_json({"name": "widget"})
            .with_timeout(HttpTimeout(connect=1.0, read=2.0, write=3.0, pool=4.0))
        )
        captured: list[httpx.Request] = []

        def handler(incoming: httpx.Request) -> httpx.Response:
            captured.append(incoming)
            return httpx.Response(201, request=incoming)

        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as client:
                self.assertEqual(201, client.send(request).status_code)

        self.assertEqual((), original.query)
        self.assertEqual("tag=first&tag=second&page=1", captured[0].url.query.decode())
        self.assertEqual(MediaType.JSON, captured[0].headers["content-type"].split(";")[0])
        self.assertEqual(b'{"name":"widget"}', captured[0].content)

    def test_form_multipart_and_sse_parser_have_owned_protocol_semantics(self) -> None:
        form = HttpRequest.post("https://unit.test/token").with_form({"scope": "items:read"})
        multipart = HttpRequest.post("https://unit.test/upload").with_multipart(
            (MultipartPart("file", b"payload", filename="note.txt", media_type="text/plain"),),
            boundary="unit-boundary",
        )
        parser = SseEventParser()
        self.assertIsNone(parser.feed(": ignored"))
        self.assertIsNone(parser.feed("id: 7"))
        self.assertIsNone(parser.feed("event: changed"))
        self.assertIsNone(parser.feed("data: one"))
        self.assertIsNone(parser.feed("data: two"))
        self.assertIsNone(parser.feed("retry: 1500"))
        event = parser.feed("")

        self.assertEqual(b"scope=items%3Aread", form.content)
        self.assertIn(b'Content-Disposition: form-data; name="file"; filename="note.txt"', multipart.content or b"")
        self.assertEqual("one\ntwo", event.data if event else None)
        self.assertEqual("changed", event.event if event else None)
        self.assertEqual(1500, event.retry_ms if event else None)

    def test_sync_sse_stream_is_aspect_aware_and_closes(self) -> None:
        captured: list[httpx.Request] = []

        def handler(incoming: httpx.Request) -> httpx.Response:
            captured.append(incoming)
            return httpx.Response(200, content=b"data: first\n\ndata: second\n\n", request=incoming)

        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as client:
                events = list(client.iter_sse(HttpRequest.get("https://unit.test/events")))
                response = client.open_stream(HttpRequest.get("https://unit.test/stream"))
                list(response.iter_bytes())
                with self.assertRaises(HttpStreamClosedError):
                    list(response.iter_bytes())

        self.assertEqual(["first", "second"], [event.data for event in events])
        self.assertEqual(MediaType.EVENT_STREAM, captured[0].headers["accept"])
        self.assertTrue(captured[0].headers["x-request-id"])


class AsyncHttpClientContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_client_has_the_same_interceptor_contract_and_lifecycle(self) -> None:
        trace: list[str] = []
        events = _Events()
        request = HttpRequest.get("https://unit.test/short-circuit")

        class _AsyncShortCircuit:
            async def intercept(self, incoming: HttpRequest, _proceed):  # type: ignore[no-untyped-def]
                trace.append("short-circuit")
                return HttpResponse(204, {}, b"", incoming.method, incoming.url)

        client = AsyncHttpClient(
            interceptors=(_AsyncTraceInterceptor(trace), _AsyncShortCircuit()),
            audit_sink=events,
        )
        response = await client.execute(request)
        await client.aclose()
        await client.aclose()

        self.assertEqual(204, response.status_code)
        self.assertEqual("before", trace[0][:6])
        self.assertEqual(["short-circuit", "after"], trace[1:])
        self.assertEqual(204, events.events[-1].status_code)
        with self.assertRaises(HttpClientClosedError):
            await client.execute(request)

    async def test_async_sse_stream_matches_sync_semantics(self) -> None:
        async def handler(incoming: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"event: notice\ndata: ready\n\n", request=incoming)

        with _controlled_async_client(httpx.MockTransport(handler)):
            async with AsyncHttpClient() as client:
                events = [event async for event in client.iter_sse(HttpRequest.get("https://unit.test/events"))]

        self.assertEqual(["notice"], [event.event for event in events])
        self.assertEqual(["ready"], [event.data for event in events])


if __name__ == "__main__":
    unittest.main()
