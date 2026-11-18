"""Coverage for cache-core surfaces the smoke and expiry suites do not reach.

Targets: key utilities, bounded-list element conversion (including the
backend-injected JSON hook), defensive-copy edge cases, and the manager's
bulk / region operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from atlas_richie.cache_core import LocalCacheManager
from atlas_richie.cache_core.commons import CacheKeyUtils
from atlas_richie.cache_core.commons.geo_point_result import GeoPointResult
from atlas_richie.cache_core.config.bloom_filter_config import BloomFilterConfig, BloomFilterType
from atlas_richie.cache_core.local import CacheDefinition, ExpiryPolicy, LocalCacheProperties
from atlas_richie.cache_core.local.util.defensive_copy_utils import DefensiveCopyUtils
from atlas_richie.cache_core.operations.bounded_list_element_converter import (
    BoundedListElementConverter,
)

pytestmark = pytest.mark.unit

REGION = "bulk-region"


class _NoDeepcopy:
    """Module-level so the pickle fallback can actually serialize it."""

    def __init__(self) -> None:
        self.value = 7

    def __deepcopy__(self, memo):
        raise TypeError("cannot deepcopy")


@pytest.fixture
def manager() -> LocalCacheManager:
    return LocalCacheManager(
        properties=LocalCacheProperties(
            cache_definitions={
                REGION: CacheDefinition(
                    expiry_policy=ExpiryPolicy.ETERNAL, ttl_millis=300_000, max_size=100
                )
            }
        )
    )


class TestCacheKeyUtils:
    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("plain", "plain"),
            ("ns@@real", "real"),
            ("a@@b@@c", "b@@c"),
            ("@@leading", "leading"),
            ("trailing@@", ""),
            ("", ""),
            ("single@at", "single@at"),
        ],
    )
    def test_get_real_key(self, key: str, expected: str) -> None:
        assert CacheKeyUtils.get_real_key(key) == expected

    def test_only_first_separator_splits(self) -> None:
        assert CacheKeyUtils.get_real_key("a@@b@@c") == "b@@c"

    def test_get_real_keys_maps_each(self) -> None:
        assert CacheKeyUtils.get_real_keys(["ns@@a", "b", "x@@y@@z"]) == ["a", "b", "y@@z"]

    def test_empty_list(self) -> None:
        assert CacheKeyUtils.get_real_keys([]) == []


class TestBoundedListElementConverter:
    def test_none_is_silent(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            assert BoundedListElementConverter.convert_one(None, "k", str, "pop") is None
        assert caplog.records == [], "an empty read is not a failure"

    @pytest.mark.parametrize(
        ("raw", "clazz", "expected"),
        [("123", int, 123), (123, str, "123"), ("1.5", float, 1.5), (b"x", bytes, b"x"), (1, bool, True)],
    )
    def test_primitive_conversion(self, raw, clazz, expected) -> None:
        assert BoundedListElementConverter.convert_one(raw, "k", clazz, "pop") == expected

    def test_conversion_failure_returns_none_and_warns(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            assert BoundedListElementConverter.convert_one("not-a-number", "k", int, "pop") is None
        assert len(caplog.records) == 1
        assert "k" in caplog.text and "pop" in caplog.text

    def test_non_primitive_requires_backend_json_hook(self, caplog) -> None:
        """The core has no JSON dependency; the backend must inject the hook."""

        @dataclass
        class Payload:
            a: int

        with caplog.at_level(logging.WARNING):
            assert BoundedListElementConverter.convert_one({"a": 1}, "k", Payload, "pop") is None
        assert "NotImplementedError" in caplog.text or "JSON" in caplog.text

    def test_convert_all_keeps_good_and_drops_bad(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            result = BoundedListElementConverter.convert_all(["1", "bad", None, "3"], "k", int, "range")
        assert result == [1, 3]
        assert "丢弃 2 个元素" in caplog.text
        assert "rawCount=4" in caplog.text and "returned=2" in caplog.text

    def test_convert_all_clean_input_does_not_warn(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            assert BoundedListElementConverter.convert_all(["1", "2"], "k", int, "range") == [1, 2]
        assert caplog.records == []

    def test_convert_all_empty(self) -> None:
        assert BoundedListElementConverter.convert_all([], "k", int, "range") == []

    def test_json_hook_is_unimplemented_in_core_by_design(self) -> None:
        """The core carries no JSON dependency; the backend must inject the hook."""
        from atlas_richie.cache_core.operations.bounded_list_element_converter import _json_convert

        with pytest.raises(NotImplementedError, match="backend"):
            _json_convert("{}", dict)


class TestDefensiveCopy:
    @pytest.mark.parametrize("value", [None, True, 3, 3.5, "s", b"b", 1 + 2j, (1, "a"), frozenset({1, 2})])
    def test_trivially_immutable_returns_same_object(self, value) -> None:
        assert DefensiveCopyUtils.copy(value) is value

    def test_nested_mutable_is_deep_copied(self) -> None:
        original = {"list": [1, {"deep": [2]}]}
        copied = DefensiveCopyUtils.copy(original)
        copied["list"][1]["deep"].append(99)
        assert original["list"][1]["deep"] == [2]

    def test_tuple_containing_mutable_is_copied(self) -> None:
        inner = [1]
        original = (inner,)
        copied = DefensiveCopyUtils.copy(original)
        assert copied is not original
        copied[0].append(2)
        assert inner == [1]

    def test_frozenset_of_mutable_is_copied(self) -> None:
        original = frozenset({(1, 2)})
        assert DefensiveCopyUtils.copy(original) is original

    def test_list_copy_is_independent(self) -> None:
        original = [1, 2]
        copied = DefensiveCopyUtils.copy(original)
        copied.append(3)
        assert original == [1, 2]

    def test_pickle_fallback_when_deepcopy_fails(self) -> None:
        original = _NoDeepcopy()
        copied = DefensiveCopyUtils.copy(original)
        assert copied is not original
        assert copied.value == 7

    def test_stored_value_is_isolated_from_caller(self, manager: LocalCacheManager) -> None:
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)
        payload["items"].append(2)
        assert manager.get(REGION, "k") == {"items": [1]}

    def test_returned_value_is_isolated_from_store(self, manager: LocalCacheManager) -> None:
        manager.put(REGION, "k", {"items": [1]})
        fetched = manager.get(REGION, "k")
        fetched["items"].append(2)
        assert manager.get(REGION, "k") == {"items": [1]}


class TestManagerBulkOperations:
    def test_put_all_and_get_all(self, manager: LocalCacheManager) -> None:
        manager.put_all(REGION, {"a": b"1", "b": b"2", "c": b"3"})
        assert manager.get_all(REGION, ["a", "c"]) == {"a": b"1", "c": b"3"}
        assert manager.size(REGION) == 3

    def test_get_all_skips_missing(self, manager: LocalCacheManager) -> None:
        manager.put(REGION, "a", b"1")
        assert manager.get_all(REGION, ["a", "missing"]) == {"a": b"1"}

    def test_remove_keys(self, manager: LocalCacheManager) -> None:
        manager.put_all(REGION, {"a": b"1", "b": b"2", "c": b"3"})
        assert manager.remove_keys(REGION, ["a", "c", "missing"]) == 2
        assert manager.size(REGION) == 1

    def test_pop_by_count_evicts_oldest(self, manager: LocalCacheManager) -> None:
        for key in ("a", "b", "c"):
            manager.put(REGION, key, b"v")
        popped = manager.pop_by_count(REGION, 2)
        assert set(popped) == {"a", "b"}
        assert manager.get(REGION, "c") == b"v"

    def test_pop_by_count_non_positive_is_noop(self, manager: LocalCacheManager) -> None:
        manager.put(REGION, "a", b"1")
        assert manager.pop_by_count(REGION, 0) == {}
        assert manager.size(REGION) == 1

    def test_clear_region(self, manager: LocalCacheManager) -> None:
        manager.put_all(REGION, {"a": b"1", "b": b"2"})
        assert manager.clear_region(REGION) == 2
        assert manager.size(REGION) == 0

    def test_region_size_and_size_agree(self, manager: LocalCacheManager) -> None:
        manager.put_all(REGION, {"a": b"1", "b": b"2"})
        assert manager.region_size(REGION) == manager.size(REGION) == 2

    def test_multi_region_isolation(self, manager: LocalCacheManager) -> None:
        manager.put("r1", "k", b"one")
        manager.put("r2", "k", b"two")
        assert manager.get("r1", "k") == b"one"
        assert manager.get("r2", "k") == b"two"
        manager.clear_region("r1")
        assert manager.get("r1", "k") is None
        assert manager.get("r2", "k") == b"two"

    def test_get_and_remove(self, manager: LocalCacheManager) -> None:
        manager.put(REGION, "k", b"v")
        assert manager.get_and_remove(REGION, "k") == b"v"
        assert manager.get_and_remove(REGION, "k") is None

    def test_get_and_put_returns_previous(self, manager: LocalCacheManager) -> None:
        manager.put(REGION, "k", b"old")
        assert manager.get_and_put(REGION, "k", b"new") == b"old"
        assert manager.get(REGION, "k") == b"new"

    def test_get_and_replace_only_when_present(self, manager: LocalCacheManager) -> None:
        assert manager.get_and_replace(REGION, "absent", b"v") is None
        assert manager.get(REGION, "absent") is None
        manager.put(REGION, "k", b"old")
        assert manager.get_and_replace(REGION, "k", b"new") == b"old"

    def test_put_if_absent_with_ttl(self, manager: LocalCacheManager) -> None:
        assert manager.put_if_absent_with_ttl(REGION, "k", b"1", 60_000) is True
        assert manager.put_if_absent_with_ttl(REGION, "k", b"2", 60_000) is False
        assert manager.get(REGION, "k") == b"1"

    def test_contains_key(self, manager: LocalCacheManager) -> None:
        manager.put(REGION, "k", b"v")
        assert manager.contains_key(REGION, "k") is True
        assert manager.contains_key(REGION, "nope") is False


class TestValueObjects:
    def test_geo_point_result_defaults(self) -> None:
        point = GeoPointResult(member="m", longitude=1.0, latitude=2.0)
        assert point.distance is None
        assert GeoPointResult(member="m", longitude=1.0, latitude=2.0, distance=5.0).distance == 5.0

    def test_bloom_filter_config_defaults(self) -> None:
        config = BloomFilterConfig()
        assert config.enable is False
        assert config.type is BloomFilterType.REDISSON
        assert config.key == "platform:cache:bloom:global"
        assert config.expected_insertions == 10_000_000
        assert config.false_probability == 0.001

    def test_bloom_filter_type_values(self) -> None:
        assert BloomFilterType.REDISSON.value == "redisson"
        assert BloomFilterType.GUAVA.value == "guava"

    def test_bloom_filter_config_overrides(self) -> None:
        config = BloomFilterConfig(enable=True, type=BloomFilterType.GUAVA, false_probability=0.01)
        assert config.enable is True
        assert config.type is BloomFilterType.GUAVA
        assert config.false_probability == 0.01
