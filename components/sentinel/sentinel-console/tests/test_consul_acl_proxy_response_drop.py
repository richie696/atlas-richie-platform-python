"""Verify the disposable Consul proxy can model a committed, lost response."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import unittest

from aiohttp import ClientSession, TCPConnector, web
from consul_acl_test_support import DisposableConsulAclServer

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceOutcomeUnknown,
    ConsulRuleSourceWrite,
    ConsulRuleSourceWriter,
)


class ConsulAclProxyResponseDropTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_cas_failure_before_consul_dispatch_is_unknown_and_not_retried(
        self,
    ) -> None:
        key = "sentinel/test/pre-upstream-drop.json"
        baseline = b'{"daily":"baseline"}'
        candidate = b'{"scheduled":"candidate"}'
        server = DisposableConsulAclServer(key)
        try:
            await server.start()
            server.write_management_value(key, baseline)
            policy = server.registered_target_policy()
            connection = SourceConnectionInput(
                source_id="synthetic-source",
                expected_revision="synthetic-revision",
                provider=ConfigurationSourceProvider.CONSUL,
                endpoint=server.endpoint,
                location="dc1",
                authentication_mode=SourceCheckAuthenticationMode.DIRECT,
                acl_token=server.application_token,
            )
            reader = ConsulRuleSourceReader(policy, server.http_client())
            original = await reader.read(connection, key)
            self.assertEqual(original.value, baseline)

            server.arm_cas_drop_before_upstream(key)
            writer = ConsulRuleSourceWriter(policy, server.http_client())
            write = asyncio.create_task(
                writer.write(
                    ConsulRuleSourceWrite(
                        connection=connection,
                        key=key,
                        expected_modify_index=original.modify_index,
                        value=candidate,
                    )
                )
            )
            await server.wait_for_pre_upstream_cas_drop(timeout=10)
            with self.assertRaises(ConsulRuleSourceOutcomeUnknown):
                await write

            observed = await reader.read(connection, key)
            self.assertEqual(observed.value, baseline)
            attempted_cas = [
                raw_path
                for raw_path, _token in server.observed_requests
                if "cas=" in raw_path
            ]
            self.assertEqual(len(attempted_cas), 1)
            self.assertTrue(
                all(
                    token == server.application_token
                    for _, token in server.observed_requests
                )
            )
        finally:
            await server.close()

    async def test_cas_request_can_be_held_before_reaching_consul(self) -> None:
        key = "sentinel/test/cas-barrier.json"
        value = b'{"synthetic":"candidate"}'
        write_count = 0

        async def consul_kv(request: web.Request) -> web.Response:
            nonlocal write_count
            if request.method == "PUT":
                write_count += 1
                return web.Response(text="true")
            return web.json_response([])

        fake_consul = web.Application()
        fake_consul.router.add_route("*", "/v1/kv/{key:.*}", consul_kv)
        consul_runner = web.AppRunner(fake_consul)
        await consul_runner.setup()
        consul_site = web.TCPSite(consul_runner, "127.0.0.1", 0)
        await consul_site.start()
        assert consul_site._server is not None
        consul_port = consul_site._server.sockets[0].getsockname()[1]

        proxy = DisposableConsulAclServer(key)
        proxy.port = consul_port
        barrier_armed = False
        try:
            await proxy._start_tls_proxy()
            proxy.arm_hold_cas_before_upstream(key)
            barrier_armed = True
            connector = TCPConnector(ssl=proxy.client_ssl_context)
            async with ClientSession(connector=connector) as session:
                write_request = asyncio.create_task(
                    session.put(
                        f"{proxy.endpoint}/v1/kv/{key}?cas=7",
                        data=value,
                        headers={"X-Consul-Token": "synthetic-token"},
                    )
                )
                await proxy.wait_for_held_cas(timeout=3)
                self.assertFalse(write_request.done())
                self.assertEqual(write_count, 0)

                proxy.release_held_cas()
                response = await write_request
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.text(), "true")
                self.assertEqual(write_count, 1)
        finally:
            if barrier_armed:
                proxy.release_held_cas()
            await proxy.close()
            await consul_runner.cleanup()

    async def test_committed_write_response_is_reset_after_client_cancellation(
        self,
    ) -> None:
        key = "sentinel/test/response-drop.json"
        value = b'{"synthetic":"candidate"}'
        state: dict[str, bytes | int] = {"modify_index": 1}
        write_count = 0

        async def consul_kv(request: web.Request) -> web.Response:
            nonlocal write_count
            if request.method == "PUT":
                state["value"] = await request.read()
                state["modify_index"] = int(state["modify_index"]) + 1
                write_count += 1
                return web.Response(text="true")
            encoded_value = base64.b64encode(bytes(state["value"])).decode("ascii")
            payload = [
                {
                    "Key": key,
                    "ModifyIndex": state["modify_index"],
                    "Value": encoded_value,
                }
            ]
            return web.json_response(payload)

        fake_consul = web.Application()
        fake_consul.router.add_route("*", "/v1/kv/{key:.*}", consul_kv)
        consul_runner = web.AppRunner(fake_consul)
        await consul_runner.setup()
        consul_site = web.TCPSite(consul_runner, "127.0.0.1", 0)
        await consul_site.start()
        assert consul_site._server is not None
        consul_port = consul_site._server.sockets[0].getsockname()[1]

        proxy = DisposableConsulAclServer(key)
        proxy.port = consul_port
        try:
            await proxy._start_tls_proxy()
            proxy.arm_response_drop_after_commit(key)
            connector = TCPConnector(ssl=proxy.client_ssl_context)
            async with ClientSession(connector=connector) as session:
                write_request = asyncio.create_task(
                    session.put(
                        f"{proxy.endpoint}/v1/kv/{key}?cas=0",
                        data=value,
                        headers={"X-Consul-Token": "synthetic-token"},
                    )
                )
                await proxy.wait_for_committed_response(timeout=3)
                self.assertFalse(write_request.done())
                self.assertEqual(state["value"], value)
                self.assertEqual(write_count, 1)

                write_request.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await write_request
                proxy.release_dropped_response()
                await proxy.wait_for_dropped_response(timeout=3)

                read_back = await session.get(f"{proxy.endpoint}/v1/kv/{key}")
                self.assertEqual(read_back.status, 200)
                observed = json.loads(await read_back.text())
                self.assertEqual(base64.b64decode(observed[0]["Value"]), value)
                self.assertEqual(write_count, 1)
        finally:
            await proxy.close()
            await consul_runner.cleanup()


if __name__ == "__main__":
    unittest.main()
