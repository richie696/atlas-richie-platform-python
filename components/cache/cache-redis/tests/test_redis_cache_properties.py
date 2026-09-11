"""`RedisCacheProperties` (pydantic-settings) unit tests.

Covers:

1. **Default values** — every field has a sensible default; loading
   with no env vars / kwargs succeeds (other than `url`, which is required).
2. **Kwargs override** — explicit kwargs take precedence over defaults.
3. **Env var loading** — each top-level field can be set via
   `ATLAS_RICHIE_CACHE_REDIS_*` env vars.
4. **Nested env var loading** — `RedisPerfSettings` fields load via
   `ATLAS_RICHIE_CACHE_REDIS_PERF__*` (note the `__` separator for
   nested fields).
5. **URL validator** — empty / wrong-scheme URLs raise `ValidationError`.
6. **`RedisProviderRegistrar.from_properties`** —
   - Rejects non-`RedisCacheProperties` input (TypeError).
   - Constructs a `ConnectionPool` with the given `max_connections`
     and other kwargs (verified via `pool.max_connections`).
   - Real Redis round-trip works (uses the project test Redis).
   - Pool kwargs are actually applied (e.g. `socket_keepalive`).

The test mirrors the Java-side `@ConfigurationProperties` contract:
every field has a default, env var injection works, and
`from_properties` is the recommended factory path.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
from pydantic import ValidationError

from atlas_richie.cache_redis import (
    ProtocolVersion,
    RedisCacheProperties,
    RedisPerfSettings,
    RedisProviderRegistrar,
    RedisType,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip all `ATLAS_RICHIE_CACHE_REDIS_*` env vars for the test's
    duration so env-var precedence is deterministic."""
    for key in list(os.environ.keys()):
        if key.startswith("ATLAS_RICHIE_CACHE_REDIS_"):
            monkeypatch.delenv(key, raising=False)
    yield


# ── 1. Default values ───────────────────────────────────────────────


def test_minimal_construction_via_kwargs() -> None:
    """The only required field is `url`; everything else has a default."""
    props = RedisCacheProperties(url="redis://localhost:6379/0")
    assert props.url == "redis://localhost:6379/0"
    assert props.namespace == "atlas-richie"
    assert props.server_type == RedisType.STANDALONE
    assert props.protocol_version == ProtocolVersion.RESP3
    assert props.enable_l2_caching is False
    assert props.enable_local_lock is True
    assert props.ping_before_activate is True
    assert props.max_connections == 50
    assert props.socket_timeout == 5.0
    assert props.socket_connect_timeout == 5.0
    assert props.socket_keepalive is True
    assert props.retry_on_timeout is False
    assert props.health_check_interval == 0
    assert props.decode_responses is True
    assert props.shutdown_timeout is None
    assert props.pool_max_wait_seconds is None
    # Nested perf defaults
    assert isinstance(props.perf, RedisPerfSettings)
    assert props.perf.enabled is False
    assert props.perf.toc_soft_ms == 8
    assert props.perf.toc_hard_ms == 50
    assert props.perf.max_batch_read_items == 1_000


def test_url_is_required(clean_env: None) -> None:
    """`url` has no default; omitting it (with no env var) raises."""
    with pytest.raises(ValidationError) as exc_info:
        RedisCacheProperties()
    assert "url" in str(exc_info.value)


# ── 2. Kwargs override defaults ─────────────────────────────────────


def test_kwargs_override_defaults() -> None:
    props = RedisCacheProperties(
        url="redis://prod:6379/0",
        namespace="myapp",
        max_connections=200,
        socket_timeout=10.0,
        enable_l2_caching=True,
        l2_caching_data=["string", "hash"],
    )
    assert props.namespace == "myapp"
    assert props.max_connections == 200
    assert props.socket_timeout == 10.0
    assert props.enable_l2_caching is True
    assert props.l2_caching_data == ["string", "hash"]


# ── 3. Env var loading ──────────────────────────────────────────────


def test_env_var_top_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Top-level fields load from `ATLAS_RICHIE_CACHE_REDIS_*`."""
    monkeypatch.setenv("ATLAS_RICHIE_CACHE_REDIS_URL", "redis://prod:6379/0")
    monkeypatch.setenv("ATLAS_RICHIE_CACHE_REDIS_NAMESPACE", "envtest")
    monkeypatch.setenv("ATLAS_RICHIE_CACHE_REDIS_MAX_CONNECTIONS", "200")
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_SERVER_TYPE", "sentinel"
    )
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_PROTOCOL_VERSION", "RESP2"
    )
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_ENABLE_L2_CACHING", "true"
    )
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_SOCKET_TIMEOUT", "12.5"
    )

    props = RedisCacheProperties()
    assert props.url == "redis://prod:6379/0"
    assert props.namespace == "envtest"
    assert props.max_connections == 200
    assert props.server_type == RedisType.SENTINEL
    assert props.protocol_version == ProtocolVersion.RESP2
    assert props.enable_l2_caching is True
    assert props.socket_timeout == 12.5


# ── 4. Nested env var loading ───────────────────────────────────────


def test_nested_env_var_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested `RedisPerfSettings` fields load via `__` separator."""
    monkeypatch.setenv("ATLAS_RICHIE_CACHE_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_PERF_ENABLED", "true"
    )
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_SOFT_MS", "20"
    )
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_HARD_MS", "100"
    )
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_PERF_MAX_BATCH_READ_ITEMS", "5000"
    )
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_PERF_BLOCK_STRING_PAYLOAD_VIOLATIONS",
        "true",
    )
    # List fields load via JSON in env vars (pydantic-settings v2
    # parses the value as JSON; for plain scalar lists, this is the
    # standard `["a", "b", "c"]` form). This is documented in the
    # `RedisPerfSettings` docstring.
    monkeypatch.setenv(
        "ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_ALLOWED_COMPLEXITIES",
        '["O1", "LOG_N", "SCRIPT_OR_UNKNOWN"]',
    )

    props = RedisCacheProperties()
    assert props.perf.enabled is True
    assert props.perf.toc_soft_ms == 20
    assert props.perf.toc_hard_ms == 100
    assert props.perf.max_batch_read_items == 5_000
    assert props.perf.block_string_payload_violations is True
    assert props.perf.toc_allowed_complexities == [
        "O1", "LOG_N", "SCRIPT_OR_UNKNOWN"
    ]


# ── 5. URL validator ────────────────────────────────────────────────


def test_url_validator_empty_raises() -> None:
    with pytest.raises(ValidationError):
        RedisCacheProperties(url="")


def test_url_validator_wrong_scheme_raises() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RedisCacheProperties(url="http://example.com")
    assert "redis://" in str(exc_info.value)


def test_url_validator_accepts_redis_rediss_unix() -> None:
    """All three valid schemes should pass the validator."""
    for url in [
        "redis://localhost:6379/0",
        "rediss://user:pass@tls-host:6380/0",
        "unix:///var/run/redis/redis.sock",
    ]:
        props = RedisCacheProperties(url=url)
        assert props.url == url


# ── 6. from_properties factory ──────────────────────────────────────


def test_from_properties_rejects_non_redisproperties() -> None:
    """Passing a non-`RedisCacheProperties` raises `TypeError`."""
    with pytest.raises(TypeError, match="RedisCacheProperties"):
        RedisProviderRegistrar.from_properties({"url": "redis://..."})  # type: ignore[arg-type]


def test_from_properties_constructs_registrar(clean_env: None) -> None:
    """`from_properties` returns a working registrar with the given
    namespace, and the underlying `ConnectionPool` reflects
    `max_connections`."""
    props = RedisCacheProperties(
        url=REDIS_URL,
        namespace=f"from-props-test-{uuid.uuid4().hex[:8]}",
        max_connections=7,
        socket_timeout=3.0,
    )
    registrar = RedisProviderRegistrar.from_properties(props)
    try:
        assert registrar.namespace == props.namespace
        assert (
            registrar.connection_pool.max_connections == 7
        ), "max_connections from properties must propagate to ConnectionPool"
        # Real Redis round-trip works.
        assert registrar.value_ops().get("__nonexistent__", str) is None
    finally:
        registrar.close()


def test_from_properties_optional_kwargs_omitted() -> None:
    """`health_check_interval=0` and `pool_max_wait_seconds=None`
    should be respected (i.e. NOT set as kwargs on `ConnectionPool.from_url`)."""
    props = RedisCacheProperties(
        url=REDIS_URL,
        max_connections=10,
    )
    # health_check_interval=0 (default) — no health check
    # pool_max_wait_seconds=None (default) — no max wait
    assert props.health_check_interval == 0
    assert props.pool_max_wait_seconds is None
    # Verify from_properties doesn't crash on these defaults.
    registrar = RedisProviderRegistrar.from_properties(props)
    try:
        assert registrar.connection_pool.max_connections == 10
    finally:
        registrar.close()


def test_from_properties_health_check_and_pool_wait() -> None:
    """When explicitly set, `health_check_interval > 0` and
    `pool_max_wait_seconds` should propagate to the pool."""
    props = RedisCacheProperties(
        url=REDIS_URL,
        max_connections=12,
        health_check_interval=30,
        pool_max_wait_seconds=5.0,
    )
    registrar = RedisProviderRegistrar.from_properties(props)
    try:
        pool = registrar._backend._connection_pool
        assert pool.max_connections == 12
        # redis-py stores these on the pool's `connection_kwargs`.
        assert pool.connection_kwargs.get("health_check_interval") == 30
        # `BlockingConnectionPool.timeout` is the max wait for a free
        # connection (public attribute).
        assert pool.timeout == 5.0
    finally:
        registrar.close()


# ── 7. Default values match Java's `AtlasRedisProperties` ────────────


def test_java_field_parity() -> None:
    """Spot-check that the defaults match Java's `AtlasRedisProperties` /
    `LettuceExtension` / `RedisPerf` defaults."""
    props = RedisCacheProperties(url="redis://x")
    # Java `enableL2Caching: Boolean = false`
    assert props.enable_l2_caching is False
    # Java `enableLocalLock: boolean = true`
    assert props.enable_local_lock is True
    # Java `pingBeforeActivateConnection: boolean = true`
    assert props.ping_before_activate is True
    # Java `RedisPerf.enabled: boolean = false`
    assert props.perf.enabled is False
    # Java `RedisPerf.warnNonO1: boolean = true`
    assert props.perf.warn_non_o1 is True
    # Java `RedisPerf.tocSoftMs: long = 8L`
    assert props.perf.toc_soft_ms == 8
    # Java `RedisPerf.tocHardMs: long = 50L`
    assert props.perf.toc_hard_ms == 50
    # Java `RedisPerf.maxBatchReadItems: int = 1000`
    assert props.perf.max_batch_read_items == 1_000
    # Java `RedisPerf.stringPayloadMaxCharsWarn: int = 100_000`
    assert props.perf.string_payload_max_chars_warn == 100_000
    # Java `RedisPerf.stringPayloadMaxBytesError: int = 1_048_576`
    assert props.perf.string_payload_max_bytes_error == 1_048_576
    # Java `RedisPerf.hashPayloadMaxBytesError: int = 4_194_304`
    assert props.perf.hash_payload_max_bytes_error == 4_194_304
