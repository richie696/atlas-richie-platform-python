"""Focused checks for source target policy and provider read-only probes."""

from __future__ import annotations

import ipaddress
import socket
import ssl
import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer
from yarl import URL

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    ConsulRegisteredSourceChecker,
    NacosRegisteredSourceChecker,
    PinnedSourceTarget,
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
    SourceTargetRejected,
    _PinnedAioHttpResolver,
)


def _record(address: str, port: int):
    address_object = ipaddress.ip_address(address)
    family = socket.AF_INET6 if address_object.version == 6 else socket.AF_INET
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))


class _Resolver:
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, hostname: str, port: int):
        self.calls.append((hostname, port))
        return tuple(_record(address, port) for address in self.addresses)


class _Request:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **request):
        self.calls.append(request)
        return self.responses.pop(0)


class PinnedAioHttpJsonClientTests(unittest.TestCase):
    def test_custom_tls_context_must_verify_certificate_and_hostname(self) -> None:
        insecure_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        insecure_context.check_hostname = False
        insecure_context.verify_mode = ssl.CERT_NONE

        with self.assertRaisesRegex(ValueError, "verify peer identity"):
            PinnedAioHttpJsonClient(ssl_context=insecure_context)

    def test_verified_custom_tls_context_is_accepted(self) -> None:
        trusted_context = ssl.create_default_context()

        client = PinnedAioHttpJsonClient(ssl_context=trusted_context)

        self.assertIsNotNone(client)

    def test_request_timeout_is_bounded_and_numeric(self) -> None:
        self.assertIsNotNone(PinnedAioHttpJsonClient(request_timeout_seconds=8))
        for value in (True, 0, float("inf"), 61):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "request timeout"):
                    PinnedAioHttpJsonClient(request_timeout_seconds=value)


class RegisteredSourceTargetPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_idn_allowlist_and_http_client_use_the_same_ascii_hostname(self) -> None:
        endpoint = "https://faß.de:8848"
        expected_hostname = URL(endpoint).raw_host
        rule = RegisteredSourceTargetRule.create(
            ConfigurationSourceProvider.NACOS,
            "faß.de",
            ("10.20.0.0/24",),
            frozenset({8848}),
        )
        policy = RegisteredSourceTargetPolicy(
            (rule,), _Resolver("10.20.0.15")
        )

        target = await policy.resolve(
            _command(ConfigurationSourceProvider.NACOS, endpoint=endpoint)
        )

        self.assertEqual(rule.hostname, expected_hostname)
        self.assertEqual(target.hostname, expected_hostname)

    async def test_resolves_once_and_pins_allowed_addresses(self) -> None:
        resolver = _Resolver("10.20.0.15", "10.20.0.16")
        policy = _policy(ConfigurationSourceProvider.NACOS, resolver)
        command = _command(ConfigurationSourceProvider.NACOS)

        target = await policy.resolve(command)

        self.assertEqual(target.hostname, "nacos.internal")
        self.assertEqual(target.port, 8848)
        self.assertEqual(
            tuple(map(str, target.addresses)), ("10.20.0.15", "10.20.0.16")
        )
        self.assertEqual(resolver.calls, [("nacos.internal", 8848)])

    async def test_rejects_mixed_allowed_and_disallowed_dns_answers(self) -> None:
        policy = _policy(
            ConfigurationSourceProvider.NACOS,
            _Resolver("10.20.0.15", "169.254.169.254"),
        )

        with self.assertRaises(SourceTargetRejected):
            await policy.resolve(_command(ConfigurationSourceProvider.NACOS))

    async def test_rejects_authenticated_http_even_when_allowlisted(self) -> None:
        policy = _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15"))
        command = _command(
            ConfigurationSourceProvider.NACOS,
            endpoint="http://nacos.internal:8848",
            mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="never-log-this",
        )

        with self.assertRaises(SourceTargetRejected):
            await policy.resolve(command)

    async def test_rejects_explicit_zero_port_instead_of_using_default_port(self) -> None:
        policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule(
                    provider=ConfigurationSourceProvider.NACOS,
                    hostname="nacos.internal",
                    networks=(ipaddress.ip_network("10.20.0.0/24"),),
                    ports=frozenset({80}),
                ),
            ),
            _Resolver("10.20.0.15"),
        )
        command = _command(
            ConfigurationSourceProvider.NACOS,
            endpoint="http://nacos.internal:0",
        )

        with self.assertRaises(SourceTargetRejected):
            await policy.resolve(command)

    async def test_rejects_traversal_and_unbounded_cidr_configuration(self) -> None:
        policy = _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15"))
        command = _command(
            ConfigurationSourceProvider.NACOS,
            endpoint="https://nacos.internal:8848/%2e%2e/other",
        )

        with self.assertRaises(SourceTargetRejected):
            await policy.resolve(command)
        with self.assertRaises(ValueError):
            RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.NACOS,
                "nacos.internal",
                ("0.0.0.0/0",),
                frozenset({8848}),
            )


class ProviderRegisteredSourceCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_resolver_uses_only_the_policy_pinned_addresses(self) -> None:
        target = PinnedSourceTarget(
            hostname="nacos.internal",
            port=8848,
            addresses=(
                ipaddress.ip_address("10.20.0.15"),
                ipaddress.ip_address("10.20.0.16"),
            ),
        )
        resolver = _PinnedAioHttpResolver(target)

        answers = await resolver.resolve("nacos.internal", 8848, socket.AF_UNSPEC)

        self.assertEqual(
            [answer["host"] for answer in answers],
            ["10.20.0.15", "10.20.0.16"],
        )
        with self.assertRaises(OSError):
            await resolver.resolve("other.internal", 8848, socket.AF_UNSPEC)

    async def test_nacos_direct_auth_then_read_probe_does_not_write(self) -> None:
        request = _Request(
            [
                (200, {"accessToken": "temporary-token"}, {}),
                (200, {"code": 0, "data": {"totalCount": 0}}, {}),
            ]
        )
        checker = NacosRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15")),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.NACOS,
            mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="private-password",
        )

        result = await checker.check(command, "admin-1")

        self.assertTrue(result.reachable)
        self.assertEqual(result.capabilities, (SourceCheckCapability.READ,))
        self.assertEqual([call["method"] for call in request.calls], ["POST", "GET"])
        self.assertEqual(request.calls[1]["path"], "/v3/admin/cs/config/list")
        self.assertEqual(
            request.calls[1]["headers"], {"accessToken": "temporary-token"}
        )
        self.assertNotIn("accessToken", request.calls[1]["params"])

    async def test_nacos_denies_bad_credentials_without_disclosing_them(self) -> None:
        request = _Request([(401, {}, {})])
        checker = NacosRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15")),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.NACOS,
            mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="private-password",
        )

        result = await checker.check(command, "admin-1")

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason.value, "authentication")
        self.assertNotIn("private-password", repr(command))

    async def test_nacos_authentication_endpoint_outage_is_not_bad_credentials(self) -> None:
        for status in (429, 500, 502, 503):
            with self.subTest(status=status):
                request = _Request([(status, {}, {})])
                checker = NacosRegisteredSourceChecker(
                    _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15")),
                    request,
                )
                command = _command(
                    ConfigurationSourceProvider.NACOS,
                    mode=SourceCheckAuthenticationMode.DIRECT,
                    username="operator",
                    password="private-password",
                )

                result = await checker.check(command, "admin-1")

                self.assertFalse(result.reachable)
                self.assertEqual(result.reason.value, "connection")
                self.assertEqual(len(request.calls), 1)

    async def test_nacos_rejects_an_empty_access_token_before_admin_probe(self) -> None:
        request = _Request([(200, {"accessToken": ""}, {})])
        checker = NacosRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15")),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.NACOS,
            mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="private-password",
        )

        result = await checker.check(command, "admin-1")

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason.value, "authentication")
        self.assertEqual(len(request.calls), 1)

    async def test_nacos_rejects_boolean_false_as_success_code(self) -> None:
        request = _Request([(200, {"code": False, "data": {}}, {})])
        checker = NacosRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15")),
            request,
        )

        result = await checker.check(
            _command(ConfigurationSourceProvider.NACOS), "admin-1"
        )

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason.value, "connection")
        self.assertEqual(len(request.calls), 1)

    async def test_nacos_accepts_documented_integer_and_string_success_codes(self) -> None:
        for code in (0, "0"):
            with self.subTest(code=code):
                request = _Request([(200, {"code": code}, {})])
                checker = NacosRegisteredSourceChecker(
                    _policy(
                        ConfigurationSourceProvider.NACOS,
                        _Resolver("10.20.0.15"),
                    ),
                    request,
                )

                result = await checker.check(
                    _command(ConfigurationSourceProvider.NACOS), "admin-1"
                )

                self.assertTrue(result.reachable)
                self.assertEqual(result.capabilities, (SourceCheckCapability.READ,))

    async def test_nacos_rejects_access_token_with_header_controls(self) -> None:
        request = _Request([(200, {"accessToken": "token\r\nX-Injected: yes"}, {})])
        checker = NacosRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15")),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.NACOS,
            mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="private-password",
        )

        result = await checker.check(command, "admin-1")

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason.value, "authentication")
        self.assertEqual(len(request.calls), 1)

    async def test_nacos_rejects_non_ascii_access_token_before_admin_probe(self) -> None:
        request = _Request([(200, {"accessToken": "令牌-token"}, {})])
        checker = NacosRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.NACOS, _Resolver("10.20.0.15")),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.NACOS,
            mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="private-password",
        )

        result = await checker.check(command, "admin-1")

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason.value, "authentication")
        self.assertEqual(len(request.calls), 1)

    async def test_consul_probe_reports_only_verified_capabilities(self) -> None:
        request = _Request([(200, {}, {"X-Consul-Index": "42"})])
        checker = ConsulRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.CONSUL, _Resolver("10.30.0.8")),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.CONSUL,
            endpoint="https://consul.internal:8500",
            location="dc-east",
            mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token="private-token",
        )

        result = await checker.check(command, "admin-1")

        self.assertEqual(
            result.capabilities,
            (SourceCheckCapability.READ, SourceCheckCapability.WATCH),
        )
        self.assertEqual(request.calls[0]["method"], "GET")
        self.assertEqual(
            request.calls[0]["headers"], {"X-Consul-Token": "private-token"}
        )
        self.assertEqual(request.calls[0]["params"]["wait"], "1ms")

    async def test_consul_authentication_rejections_classify_401_and_403(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status):
                request = _Request([(status, {}, {})])
                checker = ConsulRegisteredSourceChecker(
                    _policy(
                        ConfigurationSourceProvider.CONSUL,
                        _Resolver("10.30.0.8"),
                    ),
                    request,
                )
                command = _command(
                    ConfigurationSourceProvider.CONSUL,
                    endpoint="https://consul.internal:8500",
                    mode=SourceCheckAuthenticationMode.DIRECT,
                    acl_token="private-token",
                )

                result = await checker.check(command, "admin-1")

                self.assertFalse(result.reachable)
                self.assertEqual(result.reason.value, "authentication")
                self.assertEqual(len(request.calls), 1)

    async def test_consul_rejects_acl_token_with_header_controls_before_request(self) -> None:
        request = _Request([(200, {}, {"X-Consul-Index": "42"})])
        resolver = _Resolver("10.30.0.8")
        checker = ConsulRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.CONSUL, resolver),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.CONSUL,
            endpoint="https://consul.internal:8500",
            mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token="private-token\r\nX-Injected: yes",
        )

        result = await checker.check(command, "admin-1")

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason.value, "unsupported")
        self.assertEqual(request.calls, [])
        self.assertEqual(resolver.calls, [])

    async def test_consul_rejects_non_ascii_acl_token_before_resolution(self) -> None:
        request = _Request([(200, {}, {"X-Consul-Index": "42"})])
        resolver = _Resolver("10.30.0.8")
        checker = ConsulRegisteredSourceChecker(
            _policy(ConfigurationSourceProvider.CONSUL, resolver),
            request,
        )
        command = _command(
            ConfigurationSourceProvider.CONSUL,
            endpoint="https://consul.internal:8500",
            mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token="令牌-token",
        )

        result = await checker.check(command, "admin-1")

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason.value, "unsupported")
        self.assertEqual(request.calls, [])
        self.assertEqual(resolver.calls, [])


class RegisteredSourceCheckerLoopbackIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_nacos_probe_uses_real_http_transport_and_preserves_context_path(
        self,
    ) -> None:
        observed: list[tuple[str, str, dict[str, str]]] = []

        async def handle(request: web.Request) -> web.Response:
            observed.append((request.method, request.path, dict(request.query)))
            return web.json_response({"code": 0, "data": {"totalCount": 0}})

        app = web.Application()
        app.router.add_get("/nacos/v3/admin/cs/config/list", handle)
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
            checker = NacosRegisteredSourceChecker(
                policy, PinnedAioHttpJsonClient().request
            )
            command = _command(
                ConfigurationSourceProvider.NACOS,
                endpoint=f"http://127.0.0.1:{port}/nacos",
                location="namespace-a",
            )

            result = await checker.check(command, "admin-1")

            self.assertTrue(result.reachable)
            self.assertEqual(result.capabilities, (SourceCheckCapability.READ,))
            self.assertEqual(
                observed,
                [
                    (
                        "GET",
                        "/nacos/v3/admin/cs/config/list",
                        {
                            "namespaceId": "namespace-a",
                            "pageNo": "1",
                            "pageSize": "1",
                        },
                    )
                ],
            )
        finally:
            await server.close()

    async def test_consul_probe_does_not_follow_provider_redirects(self) -> None:
        observed: list[str] = []

        async def handle(request: web.Request) -> web.Response:
            observed.append(request.path)
            return web.Response(
                status=302,
                headers={"Location": "http://127.0.0.1:1/untrusted"},
            )

        app = web.Application()
        app.router.add_get("/v1/kv/", handle)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        try:
            assert server.port is not None
            port = server.port
            policy = RegisteredSourceTargetPolicy(
                (
                    RegisteredSourceTargetRule(
                        provider=ConfigurationSourceProvider.CONSUL,
                        hostname="127.0.0.1",
                        networks=(ipaddress.ip_network("127.0.0.1/32"),),
                        ports=frozenset({port}),
                    ),
                )
            )
            checker = ConsulRegisteredSourceChecker(
                policy, PinnedAioHttpJsonClient().request
            )
            command = _command(
                ConfigurationSourceProvider.CONSUL,
                endpoint=f"http://127.0.0.1:{port}",
                location="dc-east",
            )

            result = await checker.check(command, "admin-1")

            self.assertFalse(result.reachable)
            self.assertEqual(result.reason.value, "connection")
            self.assertEqual(observed, ["/v1/kv/"])
        finally:
            await server.close()


def _policy(provider, resolver):
    network = (
        "10.20.0.0/24"
        if provider is ConfigurationSourceProvider.NACOS
        else "10.30.0.0/24"
    )
    hostname = (
        "nacos.internal"
        if provider is ConfigurationSourceProvider.NACOS
        else "consul.internal"
    )
    port = 8848 if provider is ConfigurationSourceProvider.NACOS else 8500
    return RegisteredSourceTargetPolicy(
        (
            RegisteredSourceTargetRule(
                provider=provider,
                hostname=hostname,
                networks=(ipaddress.ip_network(network),),
                ports=frozenset({port}),
            ),
        ),
        resolver,
    )


def _command(
    provider,
    *,
    endpoint="https://nacos.internal:8848",
    location="namespace-a",
    mode=SourceCheckAuthenticationMode.NONE,
    username=None,
    password=None,
    acl_token=None,
):
    return SourceConnectionInput(
        source_id=None,
        expected_revision=None,
        provider=provider,
        endpoint=endpoint,
        location=location,
        authentication_mode=mode,
        username=username,
        password=password,
        acl_token=acl_token,
    )
