"""L2 configuration must actually reach the infrastructure.

Regression: `enable_l2_caching()` hardcoded True and `l2_caching_data` was never
read, so both properties were decorative — turning L2 off in config did nothing.
No Redis is needed: only the config gate is exercised.
"""

from __future__ import annotations

import pytest

from atlas_richie.cache_core.enums import KeyTypeEnum
from atlas_richie.cache_redis.redis_cache_infrastructure import RedisCacheInfrastructure
from atlas_richie.cache_redis.redis_cache_properties import RedisCacheProperties

pytestmark = pytest.mark.unit


class _Backend:
    connection_string = "fake://"

    def make_key(self, key: str) -> str:
        return f"ns:{key}"

    def raw_client(self):
        raise AssertionError("config gate must not touch Redis")


def _props(**overrides) -> RedisCacheProperties:
    return RedisCacheProperties(url="redis://127.0.0.1:6379/0", **overrides)


def _infra(**overrides) -> RedisCacheInfrastructure:
    return RedisCacheInfrastructure(_Backend(), _props(**overrides))


class TestL2Switch:
    def test_default_is_opt_in(self) -> None:
        assert _infra().enable_l2_caching() is False

    def test_explicit_enable(self) -> None:
        assert _infra(enable_l2_caching=True).enable_l2_caching() is True

    def test_explicit_disable(self) -> None:
        assert _infra(enable_l2_caching=False).enable_l2_caching() is False

    def test_no_properties_means_disabled(self) -> None:
        assert RedisCacheInfrastructure(_Backend()).enable_l2_caching() is False


class TestKeyTypeRestriction:
    def test_empty_list_means_all_types(self) -> None:
        infra = _infra(enable_l2_caching=True, l2_caching_data=[])
        assert infra.enable_key_type_cache(KeyTypeEnum.STRING) is True
        assert infra.enable_key_type_cache(KeyTypeEnum.HASH) is True

    def test_list_restricts_to_named_types(self) -> None:
        infra = _infra(enable_l2_caching=True, l2_caching_data=["string"])
        assert infra.enable_key_type_cache(KeyTypeEnum.STRING) is True
        assert infra.enable_key_type_cache(KeyTypeEnum.HASH) is False

    def test_type_names_are_case_insensitive(self) -> None:
        infra = _infra(enable_l2_caching=True, l2_caching_data=["STRING", "Hash"])
        assert infra.enable_key_type_cache(KeyTypeEnum.STRING) is True
        assert infra.enable_key_type_cache(KeyTypeEnum.HASH) is True
        assert infra.enable_key_type_cache(KeyTypeEnum.SET) is False

    def test_disable_key_type_still_wins(self) -> None:
        infra = _infra(enable_l2_caching=True, l2_caching_data=["string"])
        infra.disable_key_type(KeyTypeEnum.STRING)
        assert infra.enable_key_type_cache(KeyTypeEnum.STRING) is False


class TestRemainingTtl:
    def test_ttl_is_read_from_redis(self) -> None:
        class _Client:
            def pttl(self, key: str) -> int:
                assert key == "ns:k"
                return 1234

        class _BackendWithClient(_Backend):
            def raw_client(self):
                return _Client()

        infra = RedisCacheInfrastructure(_BackendWithClient(), _props())
        assert infra.remaining_ttl_millis("k") == 1234

    def test_redis_failure_degrades_to_unknown(self) -> None:
        infra = RedisCacheInfrastructure(_Backend(), _props())
        assert infra.remaining_ttl_millis("k") is None
