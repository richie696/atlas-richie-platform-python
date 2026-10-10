"""Minimal Nacos gRPC envelope transport with pinned IP and TLS authority."""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

from .registered_source_checker import PinnedSourceTarget

_MAX_RESPONSE_BYTES = 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 3.0
_CONNECTION_SETUP_SETTLE_SECONDS = 0.1
_CLIENT_VERSION = "Nacos-Python-Client:v3.2.0"
_CLIENT_LABELS = {"source": "sdk"}
_SDK_ABILITY_TABLE = {"mcp": True, "agent": True}


class NacosGrpcUnavailable(RuntimeError):
    """Nacos gRPC could not be reached before a configuration write was sent."""


class NacosGrpcRejected(RuntimeError):
    """Nacos explicitly rejected the request authorization."""


class NacosGrpcConflict(RuntimeError):
    """Nacos rejected the compare-and-set because the provider revision changed."""


class NacosGrpcOutcomeUnknown(RuntimeError):
    """A request was sent but the server result could not be verified."""


class NacosGrpcRequestClient(Protocol):
    """Consumer-owned seam for one typed Nacos unary request."""

    async def request(
        self,
        target: PinnedSourceTarget,
        *,
        request_type: str,
        body: dict[str, object],
        headers: dict[str, str],
    ) -> tuple[str, dict[str, object]]:
        """Send one request and return the response envelope type and JSON body."""


class NacosGrpcTransport:
    """Send Nacos SDK payloads without importing its private client machinery."""

    async def request(
        self,
        target: PinnedSourceTarget,
        *,
        request_type: str,
        body: dict[str, object],
        headers: dict[str, str],
    ) -> tuple[str, dict[str, object]]:
        """Register a pinned gRPC connection, then issue exactly one unary request."""
        try:
            import grpc
            from google.protobuf import descriptor_pb2, descriptor_pool
            from google.protobuf.message_factory import GetMessageClass
        except ImportError as error:
            raise NacosGrpcUnavailable from error

        if len(target.addresses) == 0 or not 1 <= target.port <= 65535:
            raise NacosGrpcUnavailable
        payload_type = _payload_message_class(
            descriptor_pb2, descriptor_pool, GetMessageClass
        )
        connection_setup_body = _connection_setup_body(body.get("tenant"))
        host = target.addresses[0].compressed
        if ":" in host:
            host = f"[{host}]"
        address = f"{host}:{target.port}"
        channel_options = (
            ("grpc.max_receive_message_length", _MAX_RESPONSE_BYTES),
            ("grpc.ssl_target_name_override", target.hostname),
            ("grpc.default_authority", target.hostname),
        )
        if _is_tls_target(target):
            channel = grpc.aio.secure_channel(
                address,
                grpc.ssl_channel_credentials(),
                options=channel_options,
            )
        else:
            channel = grpc.aio.insecure_channel(address, options=channel_options)

        unary = channel.unary_unary(
            "/Request/request",
            request_serializer=lambda payload: payload.SerializeToString(),
            response_deserializer=payload_type.FromString,
        )
        stream = None
        stream_task = None
        keep_stream_open = asyncio.Event()
        setup_acknowledged = asyncio.Event()
        setup_ack_response_sent = asyncio.Event()
        outbound_requests = asyncio.Queue()
        outbound_requests.put_nowait(
            _payload(
                payload_type,
                "ConnectionSetupRequest",
                connection_setup_body,
                {},
            )
        )

        async def setup_requests():
            while not keep_stream_open.is_set():
                request_payload = await outbound_requests.get()
                if request_payload is None:
                    return
                yield request_payload
                if request_payload.metadata.type == "SetupAckResponse":
                    setup_ack_response_sent.set()

        async def watch_server_requests(call):
            async for response_payload in call:
                response_type, response_body = _decode_payload(response_payload)
                if response_type == "SetupAckRequest":
                    await outbound_requests.put(
                        _payload(
                            payload_type,
                            "SetupAckResponse",
                            _setup_ack_response_body(response_body),
                            {},
                        )
                    )
                    setup_acknowledged.set()

        try:
            async with asyncio.timeout(_REQUEST_TIMEOUT_SECONDS):
                await channel.channel_ready()
        except grpc.aio.AioRpcError as error:
            await channel.close()
            if error.code() in {
                grpc.StatusCode.UNAUTHENTICATED,
                grpc.StatusCode.PERMISSION_DENIED,
            }:
                raise NacosGrpcRejected from None
            raise NacosGrpcUnavailable from None
        except Exception:
            await channel.close()
            raise NacosGrpcUnavailable from None

        try:
            check = _payload(payload_type, "ServerCheckRequest", {}, {})
            check_response = await unary(check, timeout=_REQUEST_TIMEOUT_SECONDS)
            check_type, check_body = _decode_payload(check_response)
            if check_type != "ServerCheckResponse" or check_body.get("resultCode") != 200:
                raise NacosGrpcUnavailable
            if not isinstance(check_body.get("connectionId"), str) or not check_body[
                "connectionId"
            ]:
                raise NacosGrpcUnavailable
        except NacosGrpcUnavailable:
            await channel.close()
            raise
        except grpc.aio.AioRpcError as error:
            await channel.close()
            if error.code() in {
                grpc.StatusCode.UNAUTHENTICATED,
                grpc.StatusCode.PERMISSION_DENIED,
            }:
                raise NacosGrpcRejected from None
            raise NacosGrpcUnavailable from None
        except Exception:
            await channel.close()
            raise NacosGrpcUnavailable from None

        try:
            stream_rpc = channel.stream_stream(
                "/BiRequestStream/requestBiStream",
                request_serializer=lambda payload: payload.SerializeToString(),
                response_deserializer=payload_type.FromString,
            )
            stream = stream_rpc(setup_requests())
            stream_task = asyncio.create_task(watch_server_requests(stream))
            if check_body.get("supportAbilityNegotiation") is True:
                await _wait_for_setup_ack(
                    setup_acknowledged,
                    setup_ack_response_sent,
                    stream_task,
                    _REQUEST_TIMEOUT_SECONDS,
                )
            else:
                await asyncio.sleep(_CONNECTION_SETUP_SETTLE_SECONDS)
                if stream_task.done():
                    stream_task.result()
                    raise NacosGrpcUnavailable
        except NacosGrpcUnavailable:
            raise
        except grpc.aio.AioRpcError as error:
            if error.code() in {
                grpc.StatusCode.UNAUTHENTICATED,
                grpc.StatusCode.PERMISSION_DENIED,
            }:
                raise NacosGrpcRejected from None
            raise NacosGrpcUnavailable from None
        except Exception:
            raise NacosGrpcUnavailable from None

        try:
            payload = _payload(payload_type, request_type, body, headers)
            response = await unary(payload, timeout=_REQUEST_TIMEOUT_SECONDS)
            return _decode_payload(response)
        except grpc.aio.AioRpcError as error:
            if error.code() in {
                grpc.StatusCode.UNAUTHENTICATED,
                grpc.StatusCode.PERMISSION_DENIED,
            }:
                raise NacosGrpcRejected from None
            raise NacosGrpcOutcomeUnknown from None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            raise NacosGrpcOutcomeUnknown from None
        except Exception:
            raise NacosGrpcOutcomeUnknown from None
        finally:
            keep_stream_open.set()
            if stream is not None:
                stream.cancel()
            if stream_task is not None:
                stream_task.cancel()
                await asyncio.gather(stream_task, return_exceptions=True)
            await channel.close()


async def _wait_for_setup_ack(
    acknowledged: asyncio.Event,
    response_sent: asyncio.Event,
    stream_task: asyncio.Task[None],
    timeout_seconds: float,
) -> None:
    """Complete both halves of the negotiated setup ack before unary dispatch."""
    async def wait_for_ack_exchange() -> None:
        await acknowledged.wait()
        await response_sent.wait()

    ack_task = asyncio.create_task(wait_for_ack_exchange())
    try:
        done, _ = await asyncio.wait(
            (ack_task, stream_task),
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if ack_task in done and acknowledged.is_set():
            return
        if stream_task in done:
            stream_task.result()
        raise NacosGrpcUnavailable
    finally:
        if not ack_task.done():
            ack_task.cancel()
        await asyncio.gather(ack_task, return_exceptions=True)


def _connection_setup_body(tenant: object) -> dict[str, object]:
    """Project the pinned source into the Nacos SDK connection registration DTO."""
    if not isinstance(tenant, str):
        raise ValueError("Nacos connection setup requires a tenant string")
    return {
        "headers": {},
        "requestId": "",
        "module": "internal",
        "clientVersion": _CLIENT_VERSION,
        "tenant": tenant,
        "labels": _CLIENT_LABELS.copy(),
        "abilityTable": _SDK_ABILITY_TABLE.copy(),
    }


def _setup_ack_response_body(request: dict[str, object]) -> dict[str, object]:
    """Echo the server setup request identity using the SDK response envelope."""
    request_id = request.get("requestId", "")
    if not isinstance(request_id, str):
        raise ValueError("Nacos setup acknowledgement request id is invalid")
    return {
        "resultCode": 200,
        "errorCode": 0,
        "message": "",
        "requestId": request_id,
    }


def _is_tls_target(target: PinnedSourceTarget) -> bool:
    """TLS is selected by the caller-provided endpoint scheme marker."""
    return target.secure


def _payload_message_class(descriptor_pb2, descriptor_pool, get_message_class):
    """Create the small official Payload/Metadata wire schema at runtime."""
    from google.protobuf import any_pb2 as _any_pb2

    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(_any_pb2.DESCRIPTOR.serialized_pb)
    file_descriptor = descriptor_pb2.FileDescriptorProto(
        name="nacos_grpc_payload.proto",
        package="atlas_richie.nacos.grpc",
        syntax="proto3",
        dependency=["google/protobuf/any.proto"],
    )
    metadata = file_descriptor.message_type.add(name="Metadata")
    _field(metadata, "type", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    _field(metadata, "clientIp", 8, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    entry = metadata.nested_type.add(name="HeadersEntry")
    entry.options.map_entry = True
    _field(entry, "key", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    _field(entry, "value", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    _field(
        metadata,
        "headers",
        7,
        descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
        type_name=".atlas_richie.nacos.grpc.Metadata.HeadersEntry",
        label=descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED,
    )
    payload = file_descriptor.message_type.add(name="Payload")
    _field(
        payload,
        "metadata",
        2,
        descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
        type_name=".atlas_richie.nacos.grpc.Metadata",
    )
    _field(
        payload,
        "body",
        3,
        descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
        type_name=".google.protobuf.Any",
    )
    descriptor = pool.AddSerializedFile(
        file_descriptor.SerializeToString()
    )
    return get_message_class(descriptor.message_types_by_name["Payload"])


def _field(
    message,
    name: str,
    number: int,
    field_type: int,
    *,
    type_name: str | None = None,
    label: int | None = None,
) -> None:
    field = message.field.add(name=name, number=number, type=field_type)
    if type_name is not None:
        field.type_name = type_name
    if label is not None:
        field.label = label


def _payload(payload_type, request_type, body, headers):
    payload = payload_type()
    payload.metadata.type = request_type
    payload.metadata.headers.update(headers)
    payload.body.value = json.dumps(
        body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return payload


def _decode_payload(payload) -> tuple[str, dict[str, object]]:
    metadata_type = payload.metadata.type
    body = json.loads(payload.body.value.decode("utf-8"))
    if (
        not isinstance(metadata_type, str)
        or not metadata_type
        or not isinstance(body, dict)
    ):
        raise ValueError("Nacos gRPC response envelope is invalid")
    return metadata_type, body


__all__ = [
    "NacosGrpcConflict",
    "NacosGrpcOutcomeUnknown",
    "NacosGrpcRejected",
    "NacosGrpcRequestClient",
    "NacosGrpcTransport",
    "NacosGrpcUnavailable",
]
