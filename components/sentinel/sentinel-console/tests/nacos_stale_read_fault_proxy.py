"""Controlled HTTP/gRPC fault injection for disposable Nacos acceptance.

The proxy forwards every request to a real Nacos instance. It can discard one
successful upstream ConfigPublish response and replay one previously observed
real baseline GET response. This models a deliberately stale network/proxy read;
it does not assert native Nacos replication or consistency behavior.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator

import aiohttp
from aiohttp import web


class NacosStaleReadFaultProxy:
    """Loopback reverse proxy with one-shot write-ack and stale-read faults."""

    def __init__(
        self,
        *,
        upstream_http_port: int,
        upstream_grpc_port: int,
        data_id: str,
        group: str,
        baseline: bytes,
    ) -> None:
        if any(
            type(port) is not int or not 1 <= port <= 65_535
            for port in (upstream_http_port, upstream_grpc_port)
        ):
            raise ValueError("Nacos proxy upstream ports are invalid")
        if not all(isinstance(value, str) and value for value in (data_id, group)):
            raise ValueError("Nacos proxy target identity is invalid")
        if not isinstance(baseline, bytes) or not baseline:
            raise ValueError("Nacos proxy baseline must be non-empty bytes")

        self._upstream_http_port = upstream_http_port
        self._upstream_grpc_port = upstream_grpc_port
        self._data_id = data_id
        self._group = group
        self._baseline = baseline
        self._baseline_response: tuple[int, bytes, dict[str, str]] | None = None
        self._http_session: aiohttp.ClientSession | None = None
        self._http_runner: web.AppRunner | None = None
        self._grpc_server = None
        self._grpc_channel = None
        self._proxy_http_port: int | None = None
        self._proxy_grpc_port: int | None = None
        self._drop_next_publish_ack = False
        self._hold_next_publish_ack = False
        self._publish_ack_held = asyncio.Event()
        self._release_publish_ack = asyncio.Event()
        self._abort_next_publish_before_upstream = False
        self._stale_read_armed = False
        self.publish_requests_received = 0
        self.dropped_publish_acks = 0
        self.publish_requests_forwarded = 0
        self.successful_upstream_publishes = 0
        self.stale_reads_served = 0
        self.stale_reads_returned_baseline = 0
        self.baseline_reads_forwarded = 0
        self.candidate_reads_forwarded = 0

    @property
    def http_port(self) -> int:
        if self._proxy_http_port is None:
            raise RuntimeError("Nacos proxy is not started")
        return self._proxy_http_port

    @property
    def grpc_port(self) -> int:
        if self._proxy_grpc_port is None:
            raise RuntimeError("Nacos proxy is not started")
        return self._proxy_grpc_port

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.http_port}/nacos"

    def drop_next_publish_acknowledgement(self) -> None:
        """Drop one client-visible ack after Nacos returns a successful commit."""
        if self._drop_next_publish_ack:
            raise RuntimeError("a Nacos publish acknowledgement fault is already armed")
        self._drop_next_publish_ack = True

    def abort_next_publish_before_upstream(self) -> None:
        """Reject one client publish after proxy receipt but before Nacos sees it."""
        if self._abort_next_publish_before_upstream:
            raise RuntimeError("a Nacos pre-dispatch fault is already armed")
        self._abort_next_publish_before_upstream = True

    def hold_next_successful_publish_acknowledgement(self) -> None:
        """Hold one successful upstream response until explicitly released."""
        if self._hold_next_publish_ack:
            raise RuntimeError("a Nacos publish acknowledgement hold is already armed")
        self._publish_ack_held.clear()
        self._release_publish_ack.clear()
        self._hold_next_publish_ack = True

    async def wait_for_held_publish_acknowledgement(self, *, timeout: float) -> None:
        """Wait until Nacos committed and the proxy intercepted its response."""
        await asyncio.wait_for(self._publish_ack_held.wait(), timeout=timeout)

    def release_held_publish_acknowledgement(self) -> None:
        """Release a held response during normal completion or teardown."""
        self._release_publish_ack.set()

    def serve_one_stale_baseline_read(self) -> None:
        """Return the cached real baseline response for the next exact config GET."""
        if self._baseline_response is None:
            raise RuntimeError("no real Nacos baseline response has been observed")
        if self._stale_read_armed:
            raise RuntimeError("a Nacos stale-read fault is already armed")
        self._stale_read_armed = True

    async def start(self) -> None:
        """Start an HTTP and gRPC loopback proxy on reserved Nacos-style ports."""
        if self._http_runner is not None or self._grpc_server is not None:
            raise RuntimeError("Nacos fault proxy is already started")

        self._proxy_http_port, self._proxy_grpc_port = _free_loopback_port_pair()
        self._http_session = aiohttp.ClientSession(auto_decompress=False)
        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.router.add_route("*", "/{path:.*}", self._forward_http)
        self._http_runner = web.AppRunner(app)
        await self._http_runner.setup()
        site = web.TCPSite(self._http_runner, "127.0.0.1", self.http_port)
        await site.start()

        import grpc

        self._grpc_channel = grpc.aio.insecure_channel(
            f"127.0.0.1:{self._upstream_grpc_port}"
        )
        self._grpc_server = grpc.aio.server()
        self._grpc_server.add_generic_rpc_handlers(
            (
                grpc.method_handlers_generic_handler(
                    "Request",
                    {
                        "request": grpc.unary_unary_rpc_method_handler(
                            self._forward_unary,
                            request_deserializer=lambda value: value,
                            response_serializer=lambda value: value,
                        )
                    },
                ),
                grpc.method_handlers_generic_handler(
                    "BiRequestStream",
                    {
                        "requestBiStream": grpc.stream_stream_rpc_method_handler(
                            self._forward_stream,
                            request_deserializer=lambda value: value,
                            response_serializer=lambda value: value,
                        )
                    },
                ),
            )
        )
        bound_port = self._grpc_server.add_insecure_port(
            f"127.0.0.1:{self.grpc_port}"
        )
        if bound_port != self.grpc_port:
            raise RuntimeError("could not bind the Nacos gRPC fault proxy")
        await self._grpc_server.start()

    async def close(self) -> None:
        """Stop the owned proxy servers and client resources."""
        if self._grpc_server is not None:
            await self._grpc_server.stop(grace=0)
            self._grpc_server = None
        if self._grpc_channel is not None:
            await self._grpc_channel.close()
            self._grpc_channel = None
        if self._http_runner is not None:
            await self._http_runner.cleanup()
            self._http_runner = None
        if self._http_session is not None:
            await self._http_session.close()
            self._http_session = None

    async def _forward_http(self, request: web.Request) -> web.Response:
        is_target_read = (
            request.method == "GET"
            and request.path.endswith("/v3/admin/cs/config")
            and request.query.get("dataId") == self._data_id
            and request.query.get("groupName") == self._group
        )
        if is_target_read and self._stale_read_armed:
            cached = self._baseline_response
            if cached is None:
                raise RuntimeError("stale-read fault lost its observed baseline")
            self._stale_read_armed = False
            self.stale_reads_served += 1
            status, body, headers = cached
            if _response_content(body) != self._baseline:
                raise AssertionError("cached Nacos stale response is not the baseline")
            self.stale_reads_returned_baseline += 1
            return web.Response(status=status, body=body, headers=headers)

        session = self._http_session
        if session is None:
            raise RuntimeError("Nacos HTTP fault proxy is not started")
        upstream_url = f"http://127.0.0.1:{self._upstream_http_port}{request.path}"
        excluded_request_headers = {
            "connection",
            "content-length",
            "host",
            "transfer-encoding",
        }
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.casefold() not in excluded_request_headers
        }
        async with session.request(
            request.method,
            upstream_url,
            params=request.query,
            headers=headers,
            data=await request.read(),
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as upstream:
            body = await upstream.read()
            response_headers = {
                key: value
                for key, value in upstream.headers.items()
                if key.casefold()
                not in {"connection", "content-length", "transfer-encoding"}
            }
            if is_target_read and upstream.status == 200:
                self._observe_config_read(upstream.status, body, response_headers)
            return web.Response(
                status=upstream.status,
                body=body,
                headers=response_headers,
            )

    def _observe_config_read(
        self, status: int, body: bytes, headers: dict[str, str]
    ) -> None:
        content_bytes = _response_content(body)
        if content_bytes is None:
            return
        if content_bytes == self._baseline:
            self._baseline_response = (
                status,
                body,
                {"content-type": headers.get("Content-Type", "application/json")},
            )
            self.baseline_reads_forwarded += 1
        else:
            self.candidate_reads_forwarded += 1

    async def _forward_unary(self, request: bytes, context) -> bytes:
        import grpc

        from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
            _decode_payload,
            _payload_message_class,
        )
        from google.protobuf import descriptor_pb2, descriptor_pool
        from google.protobuf.message_factory import GetMessageClass

        channel = self._grpc_channel
        if channel is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "proxy unavailable")
        assert channel is not None
        message_type = self._grpc_request_type(request)
        if message_type == "ConfigPublishRequest":
            self.publish_requests_received += 1
            if self._abort_next_publish_before_upstream:
                self._abort_next_publish_before_upstream = False
                await context.abort(
                    grpc.StatusCode.UNAVAILABLE,
                    "fault proxy rejected Nacos publish before upstream dispatch",
                )
                raise AssertionError("unreachable")
        call = channel.unary_unary(
            "/Request/request",
            request_serializer=lambda value: value,
            response_deserializer=lambda value: value,
        )
        if message_type == "ConfigPublishRequest":
            self.publish_requests_forwarded += 1
        try:
            response = await call(request, timeout=10)
        except grpc.aio.AioRpcError as error:
            await context.abort(error.code(), error.details() or "upstream error")
            raise AssertionError("unreachable") from error

        if message_type == "ConfigPublishRequest":
            response_message_type = _payload_message_class(
                descriptor_pb2, descriptor_pool, GetMessageClass
            )
            response_type, response_body = _decode_payload(
                response_message_type.FromString(response)
            )
            if response_type == "ConfigPublishResponse" and response_body.get(
                "resultCode"
            ) == 200:
                self.successful_upstream_publishes += 1
                if self._hold_next_publish_ack:
                    self._hold_next_publish_ack = False
                    self._publish_ack_held.set()
                    await self._release_publish_ack.wait()
                if self._drop_next_publish_ack:
                    self._drop_next_publish_ack = False
                    self.dropped_publish_acks += 1
                    await context.abort(
                        grpc.StatusCode.UNAVAILABLE,
                        "fault proxy discarded successful Nacos publish ack",
                    )
                    raise AssertionError("unreachable")
        return response

    @staticmethod
    def _grpc_request_type(request: bytes) -> str | None:
        from google.protobuf import descriptor_pb2, descriptor_pool
        from google.protobuf.message_factory import GetMessageClass

        from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
            _payload_message_class,
        )

        message_type = _payload_message_class(
            descriptor_pb2, descriptor_pool, GetMessageClass
        )
        return message_type.FromString(request).metadata.type

    async def _forward_stream(self, requests: AsyncIterator[bytes], context):
        import grpc

        channel = self._grpc_channel
        if channel is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "proxy unavailable")
        assert channel is not None
        call = channel.stream_stream(
            "/BiRequestStream/requestBiStream",
            request_serializer=lambda value: value,
            response_deserializer=lambda value: value,
        )(requests)
        try:
            async for response in call:
                yield response
        except grpc.aio.AioRpcError as error:
            await context.abort(error.code(), error.details() or "upstream error")


def _response_content(body: bytes) -> bytes | None:
    """Extract exact Nacos config bytes from a V3 Admin API JSON response."""
    try:
        payload = json.loads(body)
        content = payload["data"]["content"]
        if not isinstance(content, str):
            return None
        return content.encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return None


def _free_loopback_port_pair() -> tuple[int, int]:
    """Reserve HTTP and HTTP+1000 ports for the disposable proxy.

    The macOS ephemeral allocator can return ports above 64535, for which
    Nacos's derived gRPC port is invalid. Use an unprivileged loopback range
    as a fallback instead of failing the acceptance run.
    """
    for _ in range(100):
        try:
            with socket.socket() as http_socket, socket.socket() as grpc_socket:
                http_socket.bind(("127.0.0.1", 0))
                http_port = int(http_socket.getsockname()[1])
                grpc_port = http_port + 1000
                if grpc_port > 65_535:
                    continue
                grpc_socket.bind(("127.0.0.1", grpc_port))
                return http_port, grpc_port
        except OSError:
            continue
    for http_port in range(20_000, 48_000):
        grpc_port = http_port + 1000
        try:
            with socket.socket() as http_socket, socket.socket() as grpc_socket:
                http_socket.bind(("127.0.0.1", http_port))
                grpc_socket.bind(("127.0.0.1", grpc_port))
                return http_port, grpc_port
        except OSError:
            continue
    raise AssertionError("could not reserve loopback Nacos proxy ports")

