"""Opt-in real-provider stale-read recovery on disposable SQL dialects."""

from __future__ import annotations

import os
import unittest

from activation_plan_nacos_stale_read_acceptance import (
    assert_activation_plan_recovers_after_proxy_injected_nacos_stale_read,
    assert_nacos_pre_dispatch_remains_unknown,
    assert_nacos_restore_pre_dispatch_remains_unknown,
    assert_nacos_restore_preflight_blocks_external_change,
    assert_nacos_worker_dies_while_successful_ack_is_held,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

_RUN_ACCEPTANCE = (
    os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_STALE_READ_ACCEPTANCE") == "1"
)


def _validated_url(value: str | None, driver: str) -> str | None:
    if value is None:
        return None
    url = make_url(value)
    if (
        url.drivername != driver
        or not url.database
        or not url.database.startswith("sentinel_console_test_")
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            "Nacos stale-read acceptance requires an isolated loopback "
            "sentinel_console_test_* database"
        )
    return value


_POSTGRES_URL = _validated_url(
    os.environ.get("SENTINEL_CONSOLE_TEST_POSTGRES_URL"), "postgresql+psycopg"
)
_MYSQL_URL = _validated_url(
    os.environ.get("SENTINEL_CONSOLE_TEST_MYSQL_URL"), "mysql+asyncmy"
)


class NacosStaleReadPostgreSQLAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    """Run against disposable PostgreSQL when explicitly enabled."""

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _POSTGRES_URL,
        "use the disposable PostgreSQL runner and opt-in flag",
    )
    async def test_postgresql_lost_ack_stale_read_then_exact_recovery(self) -> None:
        assert _POSTGRES_URL is not None
        engine = create_async_engine(_POSTGRES_URL, pool_size=3)
        try:
            await assert_activation_plan_recovers_after_proxy_injected_nacos_stale_read(
                engine
            )
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _POSTGRES_URL,
        "use the disposable PostgreSQL runner and opt-in flag",
    )
    async def test_postgresql_nacos_pre_dispatch_unknown_is_not_replayed(self) -> None:
        assert _POSTGRES_URL is not None
        engine = create_async_engine(_POSTGRES_URL, pool_size=3)
        try:
            await assert_nacos_pre_dispatch_remains_unknown(engine)
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _POSTGRES_URL,
        "use the disposable PostgreSQL runner and opt-in flag",
    )
    async def test_postgresql_restore_preflight_blocks_prior_external_change(
        self,
    ) -> None:
        assert _POSTGRES_URL is not None
        engine = create_async_engine(_POSTGRES_URL, pool_size=3)
        try:
            await assert_nacos_restore_preflight_blocks_external_change(engine)
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _POSTGRES_URL,
        "use the disposable PostgreSQL runner and opt-in flag",
    )
    async def test_postgresql_restore_pre_dispatch_unknown_is_not_replayed(
        self,
    ) -> None:
        assert _POSTGRES_URL is not None
        engine = create_async_engine(_POSTGRES_URL, pool_size=3)
        try:
            await assert_nacos_restore_pre_dispatch_remains_unknown(engine)
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _POSTGRES_URL,
        "use the disposable PostgreSQL runner and opt-in flag",
    )
    async def test_postgresql_worker_dies_while_nacos_ack_is_held(self) -> None:
        assert _POSTGRES_URL is not None
        engine = create_async_engine(_POSTGRES_URL, pool_size=3)
        try:
            await assert_nacos_worker_dies_while_successful_ack_is_held(engine)
        finally:
            await engine.dispose()


class NacosStaleReadMySQLAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    """Run against disposable MySQL when explicitly enabled."""

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _MYSQL_URL,
        "use the disposable MySQL runner and opt-in flag",
    )
    async def test_mysql_lost_ack_stale_read_then_exact_recovery(self) -> None:
        assert _MYSQL_URL is not None
        engine = create_async_engine(_MYSQL_URL, pool_size=3)
        try:
            await assert_activation_plan_recovers_after_proxy_injected_nacos_stale_read(
                engine
            )
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _MYSQL_URL,
        "use the disposable MySQL runner and opt-in flag",
    )
    async def test_mysql_nacos_pre_dispatch_unknown_is_not_replayed(self) -> None:
        assert _MYSQL_URL is not None
        engine = create_async_engine(_MYSQL_URL, pool_size=3)
        try:
            await assert_nacos_pre_dispatch_remains_unknown(engine)
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _MYSQL_URL,
        "use the disposable MySQL runner and opt-in flag",
    )
    async def test_mysql_restore_preflight_blocks_prior_external_change(
        self,
    ) -> None:
        assert _MYSQL_URL is not None
        engine = create_async_engine(_MYSQL_URL, pool_size=3)
        try:
            await assert_nacos_restore_preflight_blocks_external_change(engine)
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _MYSQL_URL,
        "use the disposable MySQL runner and opt-in flag",
    )
    async def test_mysql_restore_pre_dispatch_unknown_is_not_replayed(self) -> None:
        assert _MYSQL_URL is not None
        engine = create_async_engine(_MYSQL_URL, pool_size=3)
        try:
            await assert_nacos_restore_pre_dispatch_remains_unknown(engine)
        finally:
            await engine.dispose()

    @unittest.skipUnless(
        _RUN_ACCEPTANCE and _MYSQL_URL,
        "use the disposable MySQL runner and opt-in flag",
    )
    async def test_mysql_worker_dies_while_nacos_ack_is_held(self) -> None:
        assert _MYSQL_URL is not None
        engine = create_async_engine(_MYSQL_URL, pool_size=3)
        try:
            await assert_nacos_worker_dies_while_successful_ack_is_held(engine)
        finally:
            await engine.dispose()


__all__ = []
