"""Sentinel RuleSource Port + File Source (M3.2 + M6.1.0d-1)。

中文
----
M6.1.0d-1 在 1.0 ``RuleSource`` 之上引入**两个独立 Port**:

- :class:`LegacyRuleSource` — 1.0 旧契约 (``start`` / ``stop`` /
  ``latest``); 1.x 全程保留, ``SentinelEngine.install_legacy_source()``
  接受
- :class:`SnapshotRuleSource` — 新契约 (``snapshots() -> AsyncIterator
  [RuleSnapshot]`` + ``aclose()``); ``SentinelEngine.assemble_sources()``
  仅接受

**Type alias** ``RuleSource = LegacyRuleSource`` — 1.0 公共符号保留为
``LegacyRuleSource`` 的 alias, 1.0 用户零代码改动; 1.x 全程**不**删除,
**不**发 deprecation warning (API delta v3 决策 3 / MIGRATION-M6 §2.3)。

**DTO** :class:`RuleSourceAssembly` — 公开 immutable assembly DTO, 包含
``source`` / ``priority`` / ``failover_after``, ``__post_init__`` 校验
priority≥0 / failover_after≥0; ``__post_init__`` 不触发生命周期调用
(重入校验由 contract test 负责)。

**FileRuleSource** 是 1.0 ``LegacyRuleSource`` 实现; 公共 API
(start / stop / latest) 不变, 行为锁定 (API delta v3 决策 3 / MIGRATION-M6
§1.A / DESIGN §10.3 L1091-1093)。

设计要点 (FileRuleSource):

- **Polling 间隔** (默认 3s):``start()`` 启动后台 task,定期 read →
  parse → 推送给 ``RuleRepository.apply_snapshot``;任何步骤失败保留
  last-known-good(``RuleRepository`` 已有)
- **File change detection**:用文件 ``mtime_ns`` 检测改动,避免每次
  重新解析(性能 + 避免无谓事件)
- **JSON-only 默认**:``pyyaml`` 是 optional dep;不装也能用
- **At-least-once delivery**:同一文件在两次 poll 之间被改多次,只
  推最后版本(mtime 单调递增)

English
--------
M6.1.0d-1 introduces two independent Ports over 1.0 ``RuleSource``:

- :class:`LegacyRuleSource` — 1.0 old contract (``start`` / ``stop`` /
  ``latest``); preserved for the entire 1.x phase, accepted by
  ``SentinelEngine.install_legacy_source()``.
- :class:`SnapshotRuleSource` — new contract (``snapshots() -> AsyncIterator
  [RuleSnapshot]`` + ``aclose()``); the only type accepted by
  ``SentinelEngine.assemble_sources()``.

**Type alias** ``RuleSource = LegacyRuleSource`` — the 1.0 public symbol
is kept as an alias of ``LegacyRuleSource``, so 1.0 users see zero code
changes; never removed during 1.x, and **no** deprecation warning (API
delta v3 decision 3 / MIGRATION-M6 §2.3).

**DTO** :class:`RuleSourceAssembly` — public immutable assembly DTO
with ``source`` / ``priority`` / ``failover_after``; ``__post_init__``
validates priority≥0 / failover_after≥0 and does **not** trigger
lifecycle calls (re-entrancy is contract test territory).

**FileRuleSource** is a 1.0 ``LegacyRuleSource`` implementation; public
API (start / stop / latest) is unchanged, behavior is locked (API delta
v3 decision 3 / MIGRATION-M6 §1.A / DESIGN §10.3 L1091-1093).

Design points (FileRuleSource):

- **Polling interval** (default 3s): ``start()`` launches a background
  task, periodically reads → parses → pushes to
  ``RuleRepository.apply_snapshot``; any step failure keeps
  last-known-good (already in ``RuleRepository``).
- **File change detection**: file ``mtime_ns``; skip re-parse if
  unchanged (perf + avoid spurious events).
- **JSON-only default**: ``pyyaml`` is optional dep; works without it.
- **At-least-once delivery**: same file modified multiple times
  between polls; only the last version is pushed (mtime monotonic).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, AsyncIterator, Callable, Mapping, Protocol, runtime_checkable

from ..rules.repository import RuleRepository
from ..rules.snapshot import RuleSnapshot, RuleVersion


# ---------------------------------------------------------------------------
# Protocol 1: LegacyRuleSource (1.0 旧契约) + RuleSource alias
# ---------------------------------------------------------------------------


@runtime_checkable
class LegacyRuleSource(Protocol):
    """中文
    ----
    1.0 旧契约 Port。``start(repository)`` 直连 ``RuleRepository.apply
    _snapshot``; 不经 Supervisor; 1.x 全程保留。

    1.0 公共符号 ``RuleSource`` 是本类的 type alias (见下)。

    接受方式:

    - 旧单源用户: ``SentinelEngine.install_legacy_source(source, *,
      repository=repo)`` 走 1.0 行为, **不**获多源 / failover
    - 等同 1.0 直连 ``source.start(repository)``

    **不**接受方式:

    - ``SentinelEngine.assemble_sources()`` 只接受 ``SnapshotRuleSource``
    - 不要 shim 包装成 ``SnapshotRuleSource`` (违反 1.0 行为锁定)

    English
    --------
    1.0 legacy contract Port. ``start(repository)`` connects directly
    to ``RuleRepository.apply_snapshot``; bypasses the Supervisor;
    preserved for the entire 1.x phase.

    The 1.0 public symbol ``RuleSource`` is a type alias of this class
    (see below).

    Accepted via:

    - Legacy single-source users:
      ``SentinelEngine.install_legacy_source(source, *, repository=repo)``
      preserves 1.0 behavior; **no** multi-source / failover.
    - Equivalent to direct 1.0 ``source.start(repository)``.

    **Not** accepted via:

    - ``SentinelEngine.assemble_sources()`` only accepts
      ``SnapshotRuleSource``.
    - Do not shim-wrap as ``SnapshotRuleSource`` (violates 1.0 behavior
      lock).
    """

    def start(self, repository: RuleRepository) -> None:
        ...

    def stop(self) -> None:
        ...

    def latest(self) -> RuleSnapshot | None:
        ...


# 1.0 公共符号保留: type alias 到 LegacyRuleSource
RuleSource = LegacyRuleSource
"""中文
----
1.0 公共符号 ``RuleSource`` 保留为 :class:`LegacyRuleSource` 的 type
alias; 1.0 用户 ``from atlas_richie.sentinel.source import RuleSource``
继续工作, 1.x 阶段**不**发 deprecation warning, **不**删除
(API delta v3 决策 3 / MIGRATION-M6 §2.2)。

English
--------
The 1.0 public symbol ``RuleSource`` is kept as a type alias of
:class:`LegacyRuleSource`; 1.0 users
``from atlas_richie.sentinel.source import RuleSource`` keep working;
no deprecation warning during 1.x, never removed (API delta v3
decision 3 / MIGRATION-M6 §2.2).
"""


# ---------------------------------------------------------------------------
# Protocol 2: SnapshotRuleSource (新契约) — assemble_sources 唯一接受
# ---------------------------------------------------------------------------


@runtime_checkable
class SnapshotRuleSource(Protocol):
    """中文
    ----
    新契约 Port; ``SentinelEngine.assemble_sources()`` 仅接受本类型。

    关键差异 (与 1.0 ``LegacyRuleSource``):

    - ``source_id`` — 配置时用户提供的 stable 字符串 (e.g.
      ``"nacos-prod"``); 不自动从 endpoint / path / token 构造
      (rule_source_activation.md §7)。 Supervisor 把它转写到
      ``_RuleSourceBinding.source_id`` 并出现在 activation fact 中。
    - ``snapshots()`` 是**异步迭代器**, 单向 yield 已校验完整
      ``RuleSnapshot``; 不持有 ``RuleRepository`` 引用
    - ``aclose()`` 幂等关闭; 由 ``SentinelEngine.aclose()`` 经
      Supervisor 统一关闭 (DESIGN §10.3 L1081-1089)
    - 不直接调 ``RuleRepository.apply_snapshot`` (由 Supervisor 仲裁)
    - 不暴露 priority / failover_after; 由 ``RuleSourceAssembly`` 显式
      声明, 防止 Source 自己声明优先级 (DESIGN §10.5)

    English
    --------
    New-contract Port; the only type accepted by
    ``SentinelEngine.assemble_sources()``.

    Key differences (vs 1.0 ``LegacyRuleSource``):

    - ``source_id`` — user-provided stable string at configuration
      time (e.g. ``"nacos-prod"``); never auto-derived from endpoint /
      path / token (rule_source_activation.md §7). The Supervisor
      transcribes it into ``_RuleSourceBinding.source_id`` and
      includes it in the activation fact.
    - ``snapshots()`` is an **async iterator**, one-way yielding
      already-validated ``RuleSnapshot``; no ``RuleRepository`` ref.
    - ``aclose()`` idempotent close; closed by
      ``SentinelEngine.aclose()`` through Supervisor (DESIGN §10.3
      L1081-1089).
    - Does not call ``RuleRepository.apply_snapshot`` directly (the
      Supervisor arbitrates).
    - Does not expose priority / failover_after; declared explicitly
      via ``RuleSourceAssembly``, preventing the Source from claiming
      its own priority (DESIGN §10.5).
    """

    source_id: str
    """中文
    ----
    配置时 stable 字符串标识 (e.g. ``"nacos-prod"``); Supervisor 在
    转换 ``_RuleSourceBinding`` 时读取, 写入 activation fact 的
    ``previous_source_id`` / ``source_id`` 字段。

    **不**自动从 endpoint / path / token 构造 (rule_source_activation.md
    §7)。

    English
    --------
    User-supplied stable identifier at configuration time (e.g.
    ``"nacos-prod"``); the Supervisor reads it during conversion to
    ``_RuleSourceBinding`` and includes it in activation fact
    ``previous_source_id`` / ``source_id`` fields.

    **Never** auto-derived from endpoint / path / token
    (rule_source_activation.md §7).
    """

    def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        ...

    async def aclose(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Public DTO: RuleSourceAssembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleSourceAssembly:
    """中文
    ----
    公开 immutable assembly DTO, 用于 ``SentinelEngine.assemble_sources()``。

    - ``source`` — 必须实现 :class:`SnapshotRuleSource` (新契约)
    - ``priority`` — 整数, 大值优先; 全局唯一 (重复 = 公共契约违反,
      由 contract test 兜底; 启动时 Supervisor 抛
      ``SentinelConfigurationError("duplicate_priority")``)
    - ``failover_after`` — 短抖动容错窗口; active stale 后等这么久才
      切到次高 priority ready source (rule_source_activation.md §1)

    ``__post_init__`` 校验 (不触发生命周期):

    - ``priority >= 0``
    - ``failover_after.total_seconds() >= 0``

    English
    --------
    Public immutable assembly DTO, used by
    ``SentinelEngine.assemble_sources()``.

    - ``source`` — must implement :class:`SnapshotRuleSource` (new
      contract).
    - ``priority`` — int, larger wins; globally unique (duplicate =
      public contract violation, caught by contract test; Supervisor
      raises ``SentinelConfigurationError("duplicate_priority")`` at
      start).
    - ``failover_after`` — short-jitter tolerance window; after active
      becomes stale, wait this long before switching to the next
      highest priority ready source (rule_source_activation.md §1).

    ``__post_init__`` validates (no lifecycle calls):

    - ``priority >= 0``
    - ``failover_after.total_seconds() >= 0``
    """

    source: SnapshotRuleSource
    priority: int
    failover_after: timedelta

    def __post_init__(self) -> None:
        if self.priority < 0:
            raise ValueError(
                f"RuleSourceAssembly.priority must be >= 0 (got {self.priority})"
            )
        if self.failover_after.total_seconds() < 0:
            raise ValueError(
                f"RuleSourceAssembly.failover_after must be >= 0 "
                f"(got {self.failover_after})"
            )


# ---------------------------------------------------------------------------
# Public impl: FileRuleSource (1.0 LegacyRuleSource 形态, 公共 API 不变)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FileRuleSource:
    """中文
    ----
    本地文件 RuleSource(JSON / YAML) — 1.0 ``LegacyRuleSource`` 形态。

    行为(1.0 锁定, 1.x 全程不变):

    - 启动后台 task,每 ``poll_interval_sec`` 检查文件 ``mtime_ns``
    - 文件改了 → 读全文 + 解析 + 构造 ``RuleSnapshot`` + 推 Repository
    - 文件不存在 / 解析失败 → 跳过本轮(Repository 保留 last-known-good)
    - 停止 = 取消后台 task,关闭文件句柄(若有)

    YAML 支持:尝试 import yaml;失败时只能解析 JSON。

    **M6.1.0d-1 状态**: 本类**仍**是 ``LegacyRuleSource`` 形态; 1.x
    全程**不**升级为 ``SnapshotRuleSource`` (DESIGN §10.3 L1091-1093);
    1.0 用户通过 ``SentinelEngine.install_legacy_source(self, *,
    repository=repo)`` 接入, 走 1.0 行为, 不经 Supervisor。

    English
    --------
    Local file RuleSource (JSON / YAML) — 1.0 ``LegacyRuleSource``
    shape.

    Behavior (1.0 lock, unchanged for the entire 1.x):

    - Start background task, check file ``mtime_ns`` every
      ``poll_interval_sec``.
    - File changed → read full text + parse + build ``RuleSnapshot`` +
      push to Repository.
    - File missing / parse fail → skip this round (Repository keeps
      last-known-good).
    - Stop = cancel background task, close any file handle.

    YAML support: try to import yaml; if not available, only JSON
    works.

    **M6.1.0d-1 status**: this class **remains** a
    ``LegacyRuleSource``; the 1.x phase will **not** upgrade it to
    ``SnapshotRuleSource`` (DESIGN §10.3 L1091-1093); 1.0 users plug
    in via ``SentinelEngine.install_legacy_source(self, *,
    repository=repo)`` and get 1.0 behavior, bypassing the Supervisor.
    """

    path: str
    poll_interval_sec: float = 3.0
    source_id: str = "file"
    _running: bool = field(default=False, init=False)
    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _last_mtime_ns: int = field(default=0, init=False, repr=False)
    _last_snapshot: RuleSnapshot | None = field(default=None, init=False, repr=False)
    _yaml_available: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            import yaml  # noqa: F401
            self._yaml_available = True
        except ImportError:
            self._yaml_available = False

    def latest(self) -> RuleSnapshot | None:
        """中文
        ----
        同步读一次最新快照;M3.2 用作测试 + 一次性启动加载。

        English
        --------
        Synchronous one-shot read; M3.2 uses this for tests + first
        load at startup.
        """
        snap = self._read_file()
        if snap is not None:
            self._last_snapshot = snap
        return snap

    def _read_file(self) -> RuleSnapshot | None:
        if not os.path.isfile(self.path):
            return None
        mtime = os.stat(self.path).st_mtime_ns
        if mtime == self._last_mtime_ns and self._last_snapshot is not None:
            return self._last_snapshot  # unchanged
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return None
        rules = self._parse(text)
        if rules is None:
            return None
        # Compute checksum over canonical rules
        payload = self._canonicalize(rules)
        checksum = RuleVersion.compute_checksum(payload)
        epoch, revision = self._derive_epoch_revision(mtime)
        snap = RuleSnapshot(
            version=RuleVersion(epoch=epoch, revision=revision, checksum=checksum),
            rules=rules,
            applied_at_ns=0,  # set by Repository on apply
            source_id=self.source_id,
        )
        self._last_mtime_ns = mtime
        return snap

    def _parse(self, text: str) -> dict[str, Any] | None:
        """中文
        ----
        解析 JSON / YAML;失败返 None(让 Repository 保留 last-known-good)。

        YAML 优先(JSON 也能用)。M3.2 简化:不解析嵌套结构,只把
        顶层 dict 的 key 当 rule_id,value 是 rule_dict;真正的 rule
        dataclass 反序列化由 M3.5+ 引入 schema registry 完成。

        English
        --------
        Parse JSON / YAML; failure returns ``None`` (let Repository
        keep last-known-good).

        YAML preferred (JSON also works). M3.2 simplification: doesn't
        parse nested structure; top-level dict's key is rule_id, value
        is rule_dict; real rule dataclass deserialization is
        introduced by M3.5+ via schema registry.
        """
        if self._yaml_available:
            try:
                import yaml
                data = yaml.safe_load(text)
                if isinstance(data, dict) and "rules" in data:
                    return data["rules"]
                if isinstance(data, dict):
                    return data
                return None
            except Exception:
                pass
        # JSON fallback
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "rules" in data:
                return data["rules"]
            if isinstance(data, dict):
                return data
            return None
        except json.JSONDecodeError:
            return None

    def _canonicalize(self, rules: Mapping[str, Any]) -> dict[str, Any]:
        """中文
        ----
        标准化规则 payload 用于 checksum(按 rule_id 排序)。

        English
        --------
        Canonicalize rule payload for checksum (sorted by rule_id).
        """
        return {k: rules[k] for k in sorted(rules.keys())}

    def _derive_epoch_revision(self, mtime_ns: int) -> tuple[int, int]:
        """中文
        ----
        从 mtime 推 epoch/revision:epoch = mtime 秒级时间戳,revision = 0
        (M3.2 简化;真集群 epoch 由 server 分配)。

        English
        --------
        Derive epoch/revision from mtime: epoch = mtime in seconds,
        revision = 0 (M3.2 simplification; real cluster epoch assigned
        by server).
        """
        return (mtime_ns // 1_000_000_000, 0)

    def start(self, repository: RuleRepository) -> None:
        """中文
        ----
        启动后台拉取 task,推送给 ``repository``。

        1.0 行为: 直连 ``RuleRepository.apply_snapshot``, 不经
        Supervisor, 不发 activation fact。1.x 全程保留。

        English
        --------
        Start background pull task, push to ``repository``.

        1.0 behavior: direct call to ``RuleRepository.apply_snapshot``,
        bypasses Supervisor, no activation fact emitted. Preserved for
        the entire 1.x.
        """
        if self._running:
            return
        self._running = True
        # 立即读一次(同步)
        snap = self.latest()
        if snap is not None:
            repository.apply_snapshot(snap)
        # 启动后台
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            self._task = loop.create_task(self._poll_loop(repository))
        # 不在 event loop 内(测试场景),M3.2 占位:不创建后台

    async def _poll_loop(self, repository: RuleRepository) -> None:
        """中文
        ----
        后台轮询:每 ``poll_interval_sec`` 读一次,改了推 Repository。

        English
        --------
        Background poll: every ``poll_interval_sec``; if changed, push
        to Repository.
        """
        while self._running:
            try:
                snap = self._read_file()
                if snap is not None:
                    if (
                        self._last_snapshot is None
                        or snap.version.checksum
                        != self._last_snapshot.version.checksum
                    ):
                        self._last_snapshot = snap
                        repository.apply_snapshot(snap)
            except Exception:
                # poll 失败 → 静默,Repository 不动
                pass
            await asyncio.sleep(self.poll_interval_sec)

    def stop(self) -> None:
        """中文
        ----
        停止后台 task(幂等)。

        English
        --------
        Stop background task (idempotent).
        """
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None


# Re-export for the contract base / convenience imports
__all__ = [
    # 1.0 公共符号保留 (alias)
    "RuleSource",
    # 新增公开 Port
    "LegacyRuleSource",
    "SnapshotRuleSource",
    # 新增公开 DTO
    "RuleSourceAssembly",
    # 1.0 实现 (公共 API 不变)
    "FileRuleSource",
]
