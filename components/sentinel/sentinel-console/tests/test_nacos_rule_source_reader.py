"""Controlled transport and loopback contracts for Nacos exact config reads."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceAbsent,
    NacosRuleSourceReadRejected,
    NacosRuleSourceReadUnavailable,
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)

_CONTENT = '[{"resource":"POST /api/orders","count":25}]'
_CONTENT_BYTES = _CONTENT.encode()
_CONTENT_MD5 = hashlib.md5(_CONTENT_BYTES, usedforsecurity=False).hexdigest()
_TARGET = NacosRulePublicationTarget(
    binding_id="binding-1",
    source_id="source-1",
    namespace="namespace-a",
    group="SENTINEL_GROUP",
    data_id="orders-flow-rules",
)


class ScriptedPinnedHttpClient(PinnedAioHttpJsonClient):
    def __init__(self, *responses: tuple[int, bytes, dict[str, str]]) -> None:
        super().__init__(max_response_bytes=700_000)
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    async def request_raw(self, **request: object) -> tuple[int, bytes, dict[str, str]]:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class NacosRuleSourceReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({8848}),
                ),
            )
        )

    def _connection(self, *, mode=SourceCheckAuthenticationMode.NONE):
        if mode is SourceCheckAuthenticationMode.DIRECT:
            return SourceConnectionInput(
                source_id="source-1",
                expected_revision="source-revision-1",
                provider=ConfigurationSourceProvider.NACOS,
                endpoint="https://127.0.0.1:8848/nacos",
                location="namespace-a",
                authentication_mode=mode,
                username="operator",
                password="[REDACTED_SECRET]",
            )
        return SourceConnectionInput(
            source_id="source-1",
            expected_revision="source-revision-1",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint="https://127.0.0.1:8848/nacos",
            location="namespace-a",
            authentication_mode=mode,
        )

    def _config_response(
        self,
        *,
        content: str = _CONTENT,
        namespace: str = "namespace-a",
        group: str = "SENTINEL_GROUP",
        data_id: str = "orders-flow-rules",
        md5: str = _CONTENT_MD5,
    ) -> tuple[int, bytes, dict[str, str]]:
        return (
            200,
            json.dumps(
                {
                    "code": 0,
                    "data": {
                        "namespaceId": namespace,
                        "groupName": group,
                        "dataId": data_id,
                        "content": content,
                        "md5": md5,
                    },
                }
            ).encode(),
            {"Content-Type": "application/json"},
        )

    async def test_reads_exact_pinned_admin_resource_and_checks_provider_md5(
        self,
    ) -> None:
        client = ScriptedPinnedHttpClient(self._config_response())
        reader = NacosRuleSourceReader(self.policy, client)

        snapshot = await reader.read(self._connection(), _TARGET)

        self.assertEqual(snapshot.value, _CONTENT_BYTES)
        self.assertEqual(snapshot.revision, _CONTENT_MD5)
        self.assertNotIn(_CONTENT, repr(snapshot))
        request = client.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["path"], "/v3/admin/cs/config")
        self.assertEqual(
            request["params"],
            {
                "namespaceId": "namespace-a",
                "groupName": "SENTINEL_GROUP",
                "dataId": "orders-flow-rules",
            },
        )
        self.assertEqual(request["headers"], {})

    async def test_direct_credentials_are_exchanged_once_and_token_stays_in_header(
        self,
    ) -> None:
        client = ScriptedPinnedHttpClient(
            (
                200,
                b'{"accessToken":"short-lived-token"}',
                {"Content-Type": "application/json"},
            ),
            self._config_response(),
        )
        reader = NacosRuleSourceReader(self.policy, client)

        await reader.read(
            self._connection(mode=SourceCheckAuthenticationMode.DIRECT), _TARGET
        )

        self.assertEqual([call["method"] for call in client.requests], ["POST", "GET"])
        self.assertEqual(client.requests[0]["path"], "/v3/auth/user/login")
        self.assertEqual(
            client.requests[0]["form"],
            {"username": "operator", "password": "[REDACTED_SECRET]"},
        )
        self.assertEqual(
            client.requests[1]["headers"], {"accessToken": "short-lived-token"}
        )
        self.assertEqual(client.requests[1]["params"]["dataId"], _TARGET.data_id)

    async def test_authentication_denial_is_distinct_from_read_denial(self) -> None:
        login_client = ScriptedPinnedHttpClient((403, b"{}", {}))
        reader = NacosRuleSourceReader(self.policy, login_client)
        with self.assertRaises(NacosRuleSourceReadRejected):
            await reader.read(
                self._connection(mode=SourceCheckAuthenticationMode.DIRECT), _TARGET
            )
        self.assertEqual(len(login_client.requests), 1)

        read_client = ScriptedPinnedHttpClient((403, b"{}", {}))
        reader = NacosRuleSourceReader(self.policy, read_client)
        with self.assertRaises(NacosRuleSourceReadRejected):
            await reader.read(self._connection(), _TARGET)

    async def test_oversized_or_header_unsafe_authentication_token_is_rejected(
        self,
    ) -> None:
        for token in ("x" * 8_193, "token\r\nX-Injected: yes", "令牌"):
            with self.subTest(token_length=len(token)):
                client = ScriptedPinnedHttpClient(
                    (200, json.dumps({"accessToken": token}).encode(), {})
                )
                reader = NacosRuleSourceReader(self.policy, client)
                with self.assertRaises(NacosRuleSourceReadRejected):
                    await reader.read(
                        self._connection(mode=SourceCheckAuthenticationMode.DIRECT),
                        _TARGET,
                    )
                self.assertEqual(len(client.requests), 1)

    async def test_identity_and_checksum_mismatch_fail_closed(self) -> None:
        bad_responses = (
            self._config_response(namespace="other-namespace"),
            self._config_response(group="OTHER_GROUP"),
            self._config_response(data_id="other-data-id"),
            self._config_response(md5="0" * 32),
            self._config_response(content="\ud800"),
        )
        for response in bad_responses:
            with self.subTest(response=response):
                reader = NacosRuleSourceReader(
                    self.policy, ScriptedPinnedHttpClient(response)
                )
                with self.assertRaises(NacosRuleSourceReadUnavailable):
                    await reader.read(self._connection(), _TARGET)

    async def test_only_documented_nacos_not_found_code_means_absent(
        self,
    ) -> None:
        reader = NacosRuleSourceReader(
            self.policy,
            ScriptedPinnedHttpClient(
                (404, b'{"code":20004,"message":"resource not found"}', {})
            ),
        )
        with self.assertRaises(NacosRuleSourceAbsent):
            await reader.read(self._connection(), _TARGET)

        invalid_absence_responses = (
            (404, b"", {}),
            (404, b'{"code":20005,"message":"resource conflict"}', {}),
            (404, b'{"code":true}', {}),
            OSError("redacted transport detail"),
        )
        for response in invalid_absence_responses:
            with self.subTest(response=response):
                reader = NacosRuleSourceReader(
                    self.policy, ScriptedPinnedHttpClient(response)
                )
                with self.assertRaises(NacosRuleSourceReadUnavailable) as raised:
                    await reader.read(self._connection(), _TARGET)
                self.assertIsNone(raised.exception.__cause__)
                self.assertNotIn("redacted transport detail", str(raised.exception))

    async def test_wrong_source_or_provider_is_rejected_before_io(self) -> None:
        client = ScriptedPinnedHttpClient(self._config_response())
        reader = NacosRuleSourceReader(self.policy, client)
        wrong_source = SourceConnectionInput(
            source_id="other-source",
            expected_revision="source-revision-1",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint="https://127.0.0.1:8848/nacos",
            location="namespace-a",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        with self.assertRaises(ValueError):
            await reader.read(wrong_source, _TARGET)
        self.assertEqual(client.requests, [])

        wrong_provider = SourceConnectionInput(
            source_id="source-1",
            expected_revision="source-revision-1",
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint="https://127.0.0.1:8500",
            location="dc-east",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        with self.assertRaises(ValueError):
            await reader.read(wrong_provider, _TARGET)
        self.assertEqual(client.requests, [])

    async def test_oversized_response_bound_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PinnedAioHttpJsonClient(max_response_bytes=2 * 1024 * 1024 + 1)


class NacosRuleSourceReaderLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_transport_reads_exact_config_through_context_path(
        self,
    ) -> None:
        observed: list[tuple[str, dict[str, str]]] = []

        async def handle(request: web.Request) -> web.Response:
            observed.append((request.path, dict(request.query)))
            return web.json_response(
                {
                    "code": 0,
                    "data": {
                        "namespaceId": "namespace-a",
                        "groupName": "SENTINEL_GROUP",
                        "dataId": "orders-flow-rules",
                        "content": _CONTENT,
                        "md5": _CONTENT_MD5,
                    },
                }
            )

        app = web.Application()
        app.router.add_get("/nacos/v3/admin/cs/config", handle)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        try:
            assert server.port is not None
            port = server.port
            policy = RegisteredSourceTargetPolicy(
                (
                    RegisteredSourceTargetRule(
                        provider=ConfigurationSourceProvider.NACOS,
                        hostname="127.0.0.1",
                        networks=(ipaddress.ip_network("127.0.0.1/32"),),
                        ports=frozenset({port}),
                    ),
                )
            )
            reader = NacosRuleSourceReader(policy)
            connection = SourceConnectionInput(
                source_id="source-1",
                expected_revision="source-revision-1",
                provider=ConfigurationSourceProvider.NACOS,
                endpoint=f"http://127.0.0.1:{port}/nacos",
                location="namespace-a",
                authentication_mode=SourceCheckAuthenticationMode.NONE,
            )

            snapshot = await reader.read(connection, _TARGET)

            self.assertEqual(snapshot.value, _CONTENT_BYTES)
            self.assertEqual(
                observed,
                [
                    (
                        "/nacos/v3/admin/cs/config",
                        {
                            "namespaceId": "namespace-a",
                            "groupName": "SENTINEL_GROUP",
                            "dataId": "orders-flow-rules",
                        },
                    )
                ],
            )
        finally:
            await server.close()
