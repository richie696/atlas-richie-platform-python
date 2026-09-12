"""Sentinel RuleSource Port + File Source (M3.2)。

中文
----
``RuleSource`` 是 RuleRepository 拉取规则的 Port;1.0 主包提供
``FileRuleSource`` 读取本地 JSON / YAML 文件(可选 pyyaml;**不**强制
3rd-party)。

设计要点:

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
Sentinel RuleSource Port + File Source (M3.2).

``RuleSource`` is the Port for ``RuleRepository`` to pull rules; 1.0
main wheel provides ``FileRuleSource`` for local JSON / YAML files
(pyyaml optional; **not** required 3rd-party).

Design points:

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
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from ..rules.repository import RuleRepository
from ..rules.snapshot import RuleVersion, RuleSnapshot


@runtime_checkable
class RuleSource(Protocol):
    """中文
    ----
    规则源 Port。

    - ``start(repository)`` 启动后台拉取;返回时已注册
    - ``stop()`` 停止;幂等
    - ``latest()`` 同步拉一次最新(测试用)

    English
    --------
    Rule source Port.

    - ``start(repository)`` starts background pull; returns after
      registration.
    - ``stop()`` stops; idempotent.
    - ``latest()`` synchronous one-shot pull (for tests)."""

    def start(self, repository: RuleRepository) -> None:
        ...

    def stop(self) -> None:
        ...

    def latest(self) -> RuleSnapshot | None:
        ...


@dataclass(slots=True)
class FileRuleSource:
    """中文
    ----
    本地文件 RuleSource(JSON / YAML)。

    行为:

    - 启动后台 task,每 ``poll_interval_sec`` 检查文件 ``mtime_ns``
    - 文件改了 → 读全文 + 解析 + 构造 ``RuleSnapshot`` + 推 Repository
    - 文件不存在 / 解析失败 → 跳过本轮(Repository 保留 last-known-good)
    - 停止 = 取消后台 task,关闭文件句柄(若有)

    YAML 支持:尝试 import yaml;失败时只能解析 JSON。

    English
    --------
    Local file RuleSource (JSON / YAML).

    Behavior:

    - Start background task, check file ``mtime_ns`` every
      ``poll_interval_sec``.
    - File changed → read full text + parse + build ``RuleSnapshot`` +
      push to Repository.
    - File missing / parse fail → skip this round (Repository keeps
      last-known-good).
    - Stop = cancel background task, close any file handle.

    YAML support: try to import yaml; if not available, only JSON
    works.
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

        English
        --------
        Start background pull task, push to ``repository``.
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


__all__ = ["RuleSource", "FileRuleSource"]
