"""Opt-in acceptance against a disposable, loopback-only Nacos 3 server."""

from __future__ import annotations

import hashlib
import os
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    NacosRuleSourceConflict,
    NacosRuleSourceWrite,
    NacosRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    NacosRegisteredSourceChecker,
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)


_BASE_URL_ENV = "SENTINEL_NACOS_ACCEPTANCE_URL"


class NacosRuleSourceWriterAcceptance(unittest.IsolatedAsyncioTestCase):
    """Verify actual Nacos CAS, stale-revision refusal, and exact read-back."""

    @classmethod
    def setUpClass(cls) -> None:
        endpoint = os.environ.get(_BASE_URL_ENV)
        if not endpoint:
            raise unittest.SkipTest(f"set {_BASE_URL_ENV} for local acceptance")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or not 1 <= parsed.port <= 64535
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                f"{_BASE_URL_ENV} must be an explicit loopback HTTP URL with a port"
            )
        cls.endpoint = endpoint.rstrip("/")
        cls.port = parsed.port

    async def asyncSetUp(self) -> None:
        self.data_id = f"sentinel-acceptance-{uuid4().hex}.json"
        self.group = "SENTINEL_ACCEPTANCE"
        self.namespace = "public"
        self.source_id = f"local-nacos-{uuid4().hex}"
        self.connection = SourceConnectionInput(
            source_id=self.source_id,
            expected_revision="local-acceptance-source-revision",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location=self.namespace,
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        self.target = NacosRulePublicationTarget(
            binding_id=f"local-binding-{uuid4().hex}",
            source_id=self.source_id,
            namespace=self.namespace,
            group=self.group,
            data_id=self.data_id,
        )
        self.policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "127.0.0.1",
                    ("127.0.0.1/32",),
                    frozenset({self.port, self.port + 1000}),
                ),
            )
        )
        self.http = PinnedAioHttpJsonClient()
        self.reader = NacosRuleSourceReader(self.policy, self.http)
        self.writer = NacosRuleSourceWriter(
            self.policy, self.reader, http_client=self.http
        )
        self.seed = b'{"version":"seed"}'
        await self._admin_request(
            "POST",
            data={
                "namespaceId": self.namespace,
                "groupName": self.group,
                "dataId": self.data_id,
                "content": self.seed.decode("utf-8"),
                "type": "json",
            },
        )

    async def asyncTearDown(self) -> None:
        if hasattr(self, "data_id"):
            await self._admin_request(
                "DELETE",
                params={
                    "namespaceId": self.namespace,
                    "groupName": self.group,
                    "dataId": self.data_id,
                },
                allow_failure=True,
            )

    async def test_cas_conflict_and_exact_readback_against_nacos(self) -> None:
        baseline = await self.reader.read(self.connection, self.target)
        self.assertEqual(baseline.value, self.seed)

        candidate = b'{"version":"candidate"}'
        receipt = await self.writer.write(
            NacosRuleSourceWrite(
                connection=self.connection,
                target=self.target,
                expected_md5=baseline.md5,
                value=candidate,
            )
        )
        expected_md5 = hashlib.md5(candidate, usedforsecurity=False).hexdigest()
        self.assertEqual(receipt.md5, expected_md5)

        with self.assertRaises(NacosRuleSourceConflict):
            await self.writer.write(
                NacosRuleSourceWrite(
                    connection=self.connection,
                    target=self.target,
                    expected_md5=baseline.md5,
                    value=b'{"version":"stale-writer"}',
                )
            )

        actual = await self.reader.read(self.connection, self.target)
        self.assertEqual(actual.value, candidate)
        self.assertEqual(actual.md5, receipt.md5)

    async def test_registered_source_check_is_read_only_against_real_nacos(self) -> None:
        checker = NacosRegisteredSourceChecker(
            self.policy, self.http.request
        )
        before = await self.reader.read(self.connection, self.target)

        result = await checker.check(self.connection, "acceptance-operator")

        after = await self.reader.read(self.connection, self.target)
        self.assertTrue(result.reachable)
        self.assertEqual(result.capabilities, (SourceCheckCapability.READ,))
        self.assertIsNone(result.reason)
        self.assertEqual(after.value, before.value)
        self.assertEqual(after.md5, before.md5)

    async def _admin_request(
        self,
        method: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        allow_failure: bool = False,
    ) -> dict[str, object]:
        url = f"{self.endpoint}/v3/admin/cs/config"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8), trust_env=False
            ) as session:
                async with session.request(
                    method, url, params=params, data=data, allow_redirects=False
                ) as response:
                    payload = await response.json(content_type=None)
                    if response.status != 200 or payload.get("code") != 0:
                        raise AssertionError("Nacos Admin API request was not accepted")
                    return payload
        except (aiohttp.ClientError, TimeoutError, AssertionError):
            if allow_failure:
                return {}
            raise


if __name__ == "__main__":
    unittest.main()
