"""性能守卫（`RedisPerfGuard`）— 把 `RedisPerfSettings` 23 字段落到实际操作上。
----
本模块是 R-M5.4（性能守卫 enforcement）的新增内容。`RedisPerfSettings`
在 R-M6 已就位但默认 `enabled=False`，调用方只配置不生效。本模块
把 6 类高频检查（payload 体积 / 批量大小 / 超时 / O(1) 警告 /
forbidden tier 拦截 / 大 key 探针提示）抽到 `RedisPerfGuard` 单一
facade，由每个 manager 注入并按需调用。

设计目标：

- **零开销默认路径**：`enabled=False` 时所有方法都是 no-op
  （contextmanager 立即 yield，不算 time_op start），业务代码无感知。
- **三个失败等级**：`warn`（log 一条 `structlog.warning`）、
  `error`（log 一条 `structlog.error`，但**不抛**，让调用继续）、
  `block`（如果 `block_*_violations=True` 则 `raise
  ConfigurationError`，否则降级为 `error` 级别日志）。
- **threshold 字段独立**：warn / error / block 三个阈值分开配置
  （例如 `string_payload_max_bytes_warn` / `_error` /
  `block_string_payload_violations`），符合 Java `RedisPerf` 23 字段
  的语义。
- **可测**：所有 log 走 `structlog.get_logger("atlas_richie.cache.perf")`
  单例；测试可以用 `caplog` / `structlog.testing.capture_logs()`
  验证。

**与 Java 端对齐**：`cn.richie696.component.cache.redis.perf.RedisPerf`
的所有 23 字段都通过本 `RedisPerfGuard` 暴露 API；本类的方法
（如 `check_string_payload`）对应 Java 的
`RedisPerf.checkStringWritePayload(...)`。

**复杂度分级**：`check_operation_tier` 对位 Java 的
`RedisPerfGuard.execute(manager, method, meta, supplier)` 里的策略判定部分
——白名单、`warn_non_o1`、`block_forbidden_tiers` 三段。Java 把策略判定
与计时合在一个 `execute` 里，Python 侧沿用本仓库"检查前置 + `time_op`
计时"的写法，所以本方法只判定、不计时。分级取值来自
`RedisOperationCatalog`，不再由调用方手写字符串。

**String 载荷形状**：`check_string_write_payload` 对位 Java 的
`checkStringWritePayload`，由 `RedisStringPayloadInspector` 判定
集合/Map/数组整包、超大文本与疑似整包 JSON。

English
--------
Performance guard (`RedisPerfGuard`) — wire `RedisPerfSettings` (23
fields) into actual cache operations. The fields were defined in R-M6
but defaulted to `enabled=False` and were not enforced anywhere.
This module exposes a single facade that managers can inject and
invoke on their hot paths.

Design:

- Zero-overhead default (`enabled=False` → no-op).
- Three failure levels: `warn` / `error` (log only, do not raise) /
  `block` (`raise ConfigurationError` if `block_*_violations=True`,
  else degrade to `error` log).
- The 6 most-frequent guards are implemented here: payload size
  (string / hash-field / hash-whole), batch size, time threshold
  (soft/hard), non-O(1) warnings, forbidden-tier blocking, and
  big-key probe hints. The remaining 17 fields are exposed via
  `settings` for callers that want to compose their own checks.

Mirrors Java's `cn.richie696.component.cache.redis.perf.RedisPerf`
23-field `RedisPerfSettings` 1:1, plus the
`checkStringWritePayload` / `checkBatchRead` / etc. method shapes.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

import structlog

from ..errors import ConfigurationError
from ..redis_cache_properties import RedisPerfSettings
from .command_meta import RedisCommandMeta
from .complexity_tier import BLOCKED_TIERS, RedisComplexityTier
from .string_payload_inspector import (
    RedisStringPayloadInspector,
    StringPayloadSeverity,
)

_log = structlog.get_logger("atlas_richie.cache.perf")


# ── Defaults (the 23 field default values are on `RedisPerfSettings`; ──
# ──  this module reads them and never hard-codes).                  ──
# Below are the **method-level** defaults that the guard relies on but
# that are NOT individual settings fields — e.g. which key-name tokens
# count as "big key" hints. These are intentionally static; tweak via
# subclassing if a caller disagrees with the heuristic.

# Key-name token regexes that suggest a "big" key (e.g. "all", "full",
# "dump", "snapshot"). Lowercase, exact-token match.
_BIG_KEY_TOKENS: tuple[str, ...] = ("all", "full", "dump", "snapshot", "bulk", "export")
_BIG_KEY_TOKEN_RE = re.compile(
    r"(^|[^a-z0-9_]+)(" + "|".join(_BIG_KEY_TOKENS) + r")([^a-z0-9_]+|$)",
    flags=re.IGNORECASE,
)

#: 旧式复杂度字符串 → 分级枚举（`check_complexity` 兼容入口用）。
_LEGACY_COMPLEXITY: dict[str, RedisComplexityTier] = {
    "O1": RedisComplexityTier.O1,
    "LOG_N": RedisComplexityTier.LOG_N,
    "O_N": RedisComplexityTier.LINEAR_N,
    "LINEAR_N": RedisComplexityTier.LINEAR_N,
    "O_N_LOG_N": RedisComplexityTier.WORSE,
    "WORSE": RedisComplexityTier.WORSE,
    "SCRIPT_OR_UNKNOWN": RedisComplexityTier.SCRIPT_OR_UNKNOWN,
}

#: 键名过长时截断的长度（与 Java `ellipsizeKey` 一致）。
_MAX_KEY_HINT = 160


def _ellipsize_key(key: str | None) -> str:
    """超长键名截断，避免日志被一个巨型 key 撑爆。"""
    if key is None:
        return "null"
    if len(key) <= _MAX_KEY_HINT:
        return key
    return key[:_MAX_KEY_HINT] + f"...({len(key)} chars)"


def _is_empty(values: Any) -> bool:
    """`True` iff `values` is `None` or has zero length.

    Used by `check_hash_payload` and `check_batch_size` to short-
    circuit when a manager has already filtered out empty inputs.
    """
    if values is None:
        return True
    try:
        return len(values) == 0
    except TypeError:
        return False


class RedisPerfGuard:
    """`RedisPerfSettings` enforcement facade.

    All public check methods are no-ops when `settings.enabled is
    False`. When enabled, each method consults its specific threshold
    fields and either logs a `structlog` event (warn / error) or
    raises `ConfigurationError` (when the matching `block_*_violations`
    flag is set).

    Args:
        settings: The 23-field `RedisPerfSettings` instance. The
            guard does NOT mutate it; callers can share one settings
            instance across all guards and tweak fields at runtime.
    """

    def __init__(self, settings: RedisPerfSettings) -> None:
        # Store the live reference; do not copy. Callers that need
        # isolation can pass a deep-copied settings instance.
        self._settings = settings

    # ── Accessor for callers that want the underlying settings ─────

    @property
    def settings(self) -> RedisPerfSettings:
        """The `RedisPerfSettings` instance backing this guard.

        Exposed for the rare caller that wants to compose its own
        guard logic against the 23 fields (e.g. a custom report
        endpoint that dumps effective thresholds).
        """
        return self._settings

    @property
    def enabled(self) -> bool:
        """Convenience: `True` iff any guard is active.

        Equivalent to `self._settings.enabled`. The manager-side
        check is `if self._perf is not None and self._perf.enabled`,
        which lets us skip even the context-manager frame in
        disabled mode.
        """
        return self._settings.enabled

    # ══════════════════════════════════════════════════════════════
    # Time-of-completion (TOC) check
    # ══════════════════════════════════════════════════════════════

    @contextmanager
    def time_op(self, op_name: str) -> Iterator[None]:
        """Time a method and emit soft / hard threshold events.

        Usage:
            with self._perf.time_op("set_with_ttl"):
                ...

        Behaviour:

        - `enabled=False` → instant yield, no measurement.
        - `elapsed > toc_hard_ms` → `structlog.error` (with
          `threshold="hard"`, `op=op_name`, `elapsed_ms`).
          We do NOT raise — raising on every slow method would
          couple cache latency to the caller's error budget. The
          caller can layer `block_forbidden_tiers` / a downstream
          circuit breaker on top if it needs hard failures.
        - `elapsed > toc_soft_ms` → `structlog.warning` (with
          `threshold="soft"`).
        - within thresholds → silent.

        Args:
            op_name: A short stable identifier for the operation
                being timed (e.g. `"set_with_ttl"`). Embedded in the
                log event for downstream alerting.
        """
        if not self._settings.enabled:
            yield
            return
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            if elapsed_ms > self._settings.toc_hard_ms:
                _log.error(
                    "perf.hard_timeout",
                    op=op_name,
                    elapsed_ms=elapsed_ms,
                    threshold_ms=self._settings.toc_hard_ms,
                )
            elif elapsed_ms > self._settings.toc_soft_ms:
                _log.warning(
                    "perf.soft_timeout",
                    op=op_name,
                    elapsed_ms=elapsed_ms,
                    threshold_ms=self._settings.toc_soft_ms,
                )

    # ══════════════════════════════════════════════════════════════
    # String payload check
    # ══════════════════════════════════════════════════════════════

    def check_string_payload(self, op_name: str, value: bytes | str) -> None:
        """Warn / block when a single string payload is too large.

        Args:
            op_name: Embed in log events for traceability.
            value: The encoded value (bytes or str — `str` is
                measured by its UTF-8 byte length, not the Python
                char count, to match the Java
                `string_payload_max_bytes_*` field semantics).

        Raises:
            ConfigurationError: When `value` exceeds
                `string_payload_max_bytes_error` AND
                `block_string_payload_violations` is `True`.
        """
        if not self._settings.enabled:
            return
        size = len(value.encode("utf-8") if isinstance(value, str) else value)
        if size > self._settings.string_payload_max_bytes_error:
            if self._settings.block_string_payload_violations:
                raise ConfigurationError(
                    f"string payload {size} bytes exceeds "
                    f"string_payload_max_bytes_error="
                    f"{self._settings.string_payload_max_bytes_error} "
                    f"in op={op_name!r}"
                )
            _log.error(
                "perf.string_payload_too_large",
                op=op_name,
                size=size,
                threshold=self._settings.string_payload_max_bytes_error,
            )
        elif size > self._settings.string_payload_max_bytes_warn:
            _log.warning(
                "perf.string_payload_large",
                op=op_name,
                size=size,
                threshold=self._settings.string_payload_max_bytes_warn,
            )

    # ══════════════════════════════════════════════════════════════
    # Hash field / hash-whole payload check
    # ══════════════════════════════════════════════════════════════

    def check_hash_field_payload(
        self, op_name: str, value: bytes | str
    ) -> None:
        """Warn / block when a single hash-field value is too large.

        Counterpart to Java's `RedisPerf.checkHashFieldPayload`.
        Uses `hash_field_payload_max_bytes_warn` / `_error` /
        `block_hash_payload_violations`.
        """
        if not self._settings.enabled:
            return
        size = len(value.encode("utf-8") if isinstance(value, str) else value)
        if size > self._settings.hash_field_payload_max_bytes_error:
            if self._settings.block_hash_payload_violations:
                raise ConfigurationError(
                    f"hash field payload {size} bytes exceeds "
                    f"hash_field_payload_max_bytes_error="
                    f"{self._settings.hash_field_payload_max_bytes_error} "
                    f"in op={op_name!r}"
                )
            _log.error(
                "perf.hash_field_payload_too_large",
                op=op_name,
                size=size,
                threshold=self._settings.hash_field_payload_max_bytes_error,
            )
        elif size > self._settings.hash_field_payload_max_bytes_warn:
            _log.warning(
                "perf.hash_field_payload_large",
                op=op_name,
                size=size,
                threshold=self._settings.hash_field_payload_max_bytes_warn,
            )

    def check_hash_payload(
        self,
        op_name: str,
        mapping: Mapping[str, Any] | None,
    ) -> None:
        """Warn / block when the **sum of all fields** in a hash is too large.

        The "whole hash" boundary is the sum of UTF-8 byte lengths of
        every encoded value in `mapping` (not the field-name lengths,
        not the Redis internal `OBJ_ENCODING` overhead — those are
        impossible to predict without writing first). The check is
        intended as a coarse anti-pattern detector, not a precise
        budget: a 1MB field mapping is unusual, a 100MB field mapping
        is almost certainly a bug.

        Args:
            op_name: Embed in log events.
            mapping: The `{field: value}` dict about to be written
                (or already read). Pass `None` to no-op (the manager
                short-circuits empty mappings before this call).

        Raises:
            ConfigurationError: When total > `hash_payload_max_bytes_error`
                AND `block_hash_payload_violations`.
        """
        if not self._settings.enabled:
            return
        if _is_empty(mapping):
            return
        total = 0
        for v in mapping.values():  # type: ignore[union-attr]
            if isinstance(v, (bytes, bytearray)):
                total += len(v)
            elif isinstance(v, str):
                total += len(v.encode("utf-8"))
            else:
                # Fallback: best-effort encode via the project's
                # serializer would create a circular import, so
                # count the `repr` length as a coarse proxy.
                total += len(repr(v).encode("utf-8"))
        if total > self._settings.hash_payload_max_bytes_error:
            if self._settings.block_hash_payload_violations:
                raise ConfigurationError(
                    f"hash payload {total} bytes exceeds "
                    f"hash_payload_max_bytes_error="
                    f"{self._settings.hash_payload_max_bytes_error} "
                    f"in op={op_name!r}"
                )
            _log.error(
                "perf.hash_payload_too_large",
                op=op_name,
                size=total,
                threshold=self._settings.hash_payload_max_bytes_error,
            )
        elif total > self._settings.hash_payload_max_bytes_warn:
            _log.warning(
                "perf.hash_payload_large",
                op=op_name,
                size=total,
                threshold=self._settings.hash_payload_max_bytes_warn,
            )

    # ══════════════════════════════════════════════════════════════
    # Batch size check
    # ══════════════════════════════════════════════════════════════

    def check_batch_size(
        self, op_name: str, items: int
    ) -> None:
        """Warn / block when a batch operation is too large.

        Counterpart to Java's `RedisPerf.checkBatchRead` /
        `checkBatchWrite`. The same `max_batch_read_items` field
        covers both read and write batches — Redis doesn't care
        which side the pipeline was on, and the cost of N items
        is roughly the same.

        Args:
            op_name: Embed in log events.
            items: The number of items in the batch. The manager is
                expected to short-circuit empty batches before this
                call; passing `0` or a negative value is treated as
                a no-op.

        Raises:
            ConfigurationError: When `items > max_batch_read_items`
                AND `block_batch_read_violations` is `True`.
        """
        if not self._settings.enabled:
            return
        if items <= 0:
            return
        if items > self._settings.max_batch_read_items:
            if self._settings.block_batch_read_violations:
                raise ConfigurationError(
                    f"batch {items} items exceeds "
                    f"max_batch_read_items="
                    f"{self._settings.max_batch_read_items} "
                    f"in op={op_name!r}"
                )
            _log.warning(
                "perf.batch_too_large",
                op=op_name,
                items=items,
                threshold=self._settings.max_batch_read_items,
            )

    # ══════════════════════════════════════════════════════════════
    # O(1) complexity / forbidden-tier checks
    # ══════════════════════════════════════════════════════════════

    def check_complexity(
        self,
        op_name: str,
        declared_complexity: str,
    ) -> None:
        """按字符串声明复杂度分级（**兼容入口**）。

        新代码请用 :meth:`check_operation_tier` 并从
        :class:`RedisOperationCatalog` 取预设——分级字符串手写容易各写各的，
        而且拿不到 BIGKEY 探测建议。

        本方法把旧字符串映射成 :class:`RedisComplexityTier` 后转交
        `check_operation_tier`，因此**策略语义与新入口完全一致**
        （白名单不命中即报错、按配置拦截 LINEAR_N / WORSE）。

        Args:
            op_name: Embed in log events.
            declared_complexity: 旧式分级字符串（`"O1"` / `"LOG_N"` /
                `"O_N"` / `"O_N_LOG_N"` …）。无法识别时按
                `SCRIPT_OR_UNKNOWN` 处理。
        """
        self.check_operation_tier(
            op_name,
            _LEGACY_COMPLEXITY.get(
                declared_complexity.upper(), RedisComplexityTier.SCRIPT_OR_UNKNOWN
            ),
        )

    # ══════════════════════════════════════════════════════════════
    # Complexity tier policy
    # ══════════════════════════════════════════════════════════════

    def check_operation_tier(
        self,
        op_name: str,
        meta: RedisCommandMeta | RedisComplexityTier,
    ) -> None:
        """按复杂度分级执行策略判定。

        判定顺序与 Java `RedisPerfGuard.executeInternal` 一致：

        1. **白名单**：`toc_allowed_complexities` 非空时，分级不在名单内
           即记 error；`block_forbidden_tiers` 为真时**抛异常**拦截。
        2. **非 O(1) 告警**：`warn_non_o1` 为真且分级不是 `O1` 时记 warning。
        3. **禁用档拦截**：`block_forbidden_tiers` 为真且分级属于
           `LINEAR_N` / `WORSE` 时**抛异常**——这两档在 ToC 核心路径
           必须禁用。

        与 Java 的差别：Java 把策略判定与计时合在一个 `execute(...)` 里，
        Python 侧沿用本仓库既有的"检查前置 + `time_op` 计时"写法，
        因此本方法只做策略判定，不计时。

        Args:
            op_name: Embed in log events.
            meta: 分级预设（带 BIGKEY 探测建议）或裸分级。
        """
        if not self._settings.enabled:
            return

        if isinstance(meta, RedisCommandMeta):
            tier = meta.tier
            if self._settings.log_big_key_probe_hints:
                self._log_big_key_hints(op_name, meta)
        else:
            tier = meta

        allowed = self._settings.toc_allowed_complexities
        if allowed:
            normalized_allowed = {
                str(item).strip().upper() for item in allowed if str(item).strip()
            }
            if tier.value.upper() not in normalized_allowed:
                _log.error(
                    "perf.tier_not_allowed",
                    op=op_name,
                    tier=tier.value,
                    allowed=list(allowed),
                )
                if self._settings.block_forbidden_tiers:
                    raise ConfigurationError(
                        f"tier {tier.value} not in toc_allowed_complexities "
                        f"(op={op_name!r}, allowed={list(allowed)})"
                    )

        if self._settings.warn_non_o1 and tier is not RedisComplexityTier.O1:
            _log.warning(
                "perf.non_o1_op",
                op=op_name,
                tier=tier.value,
            )

        if self._settings.block_forbidden_tiers and tier in BLOCKED_TIERS:
            _log.error(
                "perf.forbidden_tier",
                op=op_name,
                tier=tier.value,
            )
            raise ConfigurationError(
                f"operation blocked by complexity policy "
                f"(op={op_name!r}, tier={tier.value})"
            )

    def _log_big_key_hints(
        self, op_name: str, meta: RedisCommandMeta
    ) -> None:
        """非 O(1) 操作时，提示该用哪个命令探一下 BIGKEY。"""
        if meta.tier is RedisComplexityTier.O1:
            return
        hints = meta.probe_hints()
        if not hints:
            return
        _log.warning(
            "perf.big_key_probe_hints",
            op=op_name,
            tier=meta.tier.value,
            suggest=hints,
            meta=meta.description,
        )

    # ══════════════════════════════════════════════════════════════
    # String payload shape inspection
    # ══════════════════════════════════════════════════════════════

    def check_string_write_payload(
        self,
        op_name: str,
        key: str,
        value: Any,
    ) -> None:
        """写入 Redis String 前检测典型滥用。

        受 `enabled` 与 `warn_string_payload_anti_patterns` 双开关控制。
        **`value` 必须是序列化之前的原始值**——集合 / Map 的形状只有在
        原始值上才看得出来（编码成 JSON 之后就只剩字符串了）。

        Args:
            op_name: Embed in log events.
            key: 缓存键（过长会截断）。
            value: 即将写入的原始值。

        Raises:
            ConfigurationError: 检查结果为 ERROR 且
                `block_string_payload_violations` 为真时抛出。
        """
        if (
            not self._settings.enabled
            or not self._settings.warn_string_payload_anti_patterns
        ):
            return

        result = RedisStringPayloadInspector.inspect(value, self._settings)
        if result.severity is StringPayloadSeverity.OK:
            return

        key_hint = _ellipsize_key(key)
        if result.severity is StringPayloadSeverity.WARN:
            _log.warning(
                "perf.string_payload_anti_pattern",
                op=op_name,
                key=key_hint,
                detail=result.detail,
            )
            return

        _log.error(
            "perf.string_payload_anti_pattern",
            op=op_name,
            key=key_hint,
            detail=result.detail,
        )
        if self._settings.block_string_payload_violations:
            raise ConfigurationError(
                f"String value anti-pattern op={op_name!r} key={key_hint} "
                f"detail={result.detail}"
            )

    # ══════════════════════════════════════════════════════════════
    # Big-key probe hints
    # ══════════════════════════════════════════════════════════════

    def check_key_name_hint(self, key: str) -> None:
        """Log a "you may be about to write a very large value"
        hint when the key name contains tokens like `all` / `full` /
        `dump` / `snapshot` / `bulk` / `export`.

        The hint is purely informational — a `bulk` key with a 1KB
        payload is fine, but a `dump` key with a 100MB payload is
        almost certainly going to hurt. The guard can't see the
        payload size yet at this call site (it is called BEFORE
        `check_string_payload` in the manager), so the hint is a
        cheap leading indicator for downstream alerting.

        Args:
            key: The user-supplied key (NOT namespaced — the
                token check is on the business-meaningful part).
        """
        if not self._settings.enabled:
            return
        if not self._settings.log_big_key_probe_hints:
            return
        if _BIG_KEY_TOKEN_RE.search(key):
            _log.info("perf.big_key_probe_hint", key=key)


# ── Exports ──────────────────────────────────────────────────────

__all__ = ["RedisPerfGuard"]
