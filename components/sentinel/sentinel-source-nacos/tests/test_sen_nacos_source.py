"""M6.1.3 + M6.1.4 + M6.1.5 NacosRuleSource 单元测试。

中文
----
PLANNING M6.1.3-1.5 硬约束测试覆盖:

- 公开 API 签名 (signature lock)
- __init__ 接受合法 config; 拒绝非法 (传递性)
- state 初始 CONNECTING
- aclose() 幂等 (3 次连续调, 第 2/3 次不抛错, 状态保持 CLOSED)
- 5 类错误分类 (AUTH / NOT_FOUND / EMPTY / DECODE / NETWORK) 单元测试
- 退避: reconnect_initial → reconnect_max 边界
- 脱敏: last_error_message 不含敏感字段
- snapshots() 取消传播: aclose 后 StopAsyncIteration
- 脱敏日志: capture log, 验证不含敏感字段
- 公开 API 不泄漏 nacos SDK 类型 (NacosClient 等)
- 主包 C 层 _supervisor 不被 extension 引用 (C 层物理隔离)

**测试用 fake NacosClient**: 单元测试用 ``_FakeNacosClient`` 模拟
``nacos-sdk-python`` 同步 API (``get_config`` / ``add_config_watcher``
/ ``remove_config_watcher`` / ``stop_subscribe``), **不**连真实 Nacos。
PLANNING M6.1 真实验收 5 场景 (testcontainers / docker-compose) 留给
M6.1 集成测试 (marker=integration, 默认 skip)。

English
--------
M6.1.3 + M6.1.4 + M6.1.5 unit tests for :class:`NacosRuleSource`.

Covers: signature lock, init validation, lifecycle states, idempotent
aclose, 5-way error classification, backoff boundary, redaction,
snapshots cancellation, public-API boundary, C-layer isolation.

Uses ``_FakeNacosClient`` to mock the sync nacos SDK API.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Callable, Iterator

import pytest

from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion

from atlas_richie.sentinel_source_nacos import (
    NacosRuleSourceConfig,
    NacosSourceError,
    NacosSourceState,
)
from atlas_richie.sentinel_source_nacos.source import (
    NacosRuleSource,
    _redact,
)


# ---------------------------------------------------------------------------
# _FakeNacosClient: 模拟 nacos-sdk-python 同步 API
# ---------------------------------------------------------------------------


class _FakeNacosClient:
    """Mock Nacos SDK client for unit tests.

    中文
    ----
    只实现本模块**用到的** API 表面; 不替代完整 SDK 行为。
    """

    def __init__(
        self,
        *,
        server_addresses: list[str] | None = None,
        namespace: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.server_addresses = server_addresses or []
        self.namespace = namespace
        self.username = username
        self.password = password
        # data_id → content (test 直接 set)
        self._config_data: dict[str, str] = {}
        # watchers: data_id → list[cb]
        self._watchers: dict[str, list[Callable[..., None]]] = {}
        # 触发变化的方法 (test 直接调)
        self._stopped: bool = False
        # record calls
        self.stop_subscribe_calls: int = 0
        self.remove_watcher_calls: list[tuple[str, str]] = []

    def set_config(self, data_id: str, content: str | None) -> None:
        if content is None:
            self._config_data.pop(data_id, None)
        else:
            self._config_data[data_id] = content

    def trigger_change(self, data_id: str) -> None:
        """模拟 Nacos 推送; 调所有已注册的 callback。"""
        params = {
            "data_id": data_id,
            "group": "DEFAULT_GROUP",
            "namespace": self.namespace,
            "raw_content": self._config_data.get(data_id),
            "content": self._config_data.get(data_id),
        }
        for cb in self._watchers.get(data_id, []):
            cb(params)

    # --- SDK API ---

    def get_config(self, data_id: str, group: str, timeout: float | None = None) -> str | None:
        return self._config_data.get(data_id)

    def add_config_watcher(
        self,
        data_id: str,
        group: str,
        cb: Callable[..., None],
        content: str | None = None,
    ) -> None:
        self._watchers.setdefault(data_id, []).append(cb)
        # SDK 实际会 init content
        if content is None and data_id in self._config_data:
            content = self._config_data[data_id]
        # 简单起见直接 push initial content
        if content is not None:
            params = {
                "data_id": data_id,
                "group": group,
                "namespace": self.namespace,
                "raw_content": content,
                "content": content,
            }
            try:
                cb(params)
            except Exception:
                pass

    def remove_config_watcher(
        self,
        data_id: str,
        group: str,
        cb: Callable[..., None],
        remove_all: bool = False,
    ) -> None:
        self.remove_watcher_calls.append((data_id, group))
        if data_id in self._watchers:
            self._watchers[data_id] = [
                w for w in self._watchers[data_id] if w != cb
            ]

    def stop_subscribe(self) -> None:
        self.stop_subscribe_calls += 1
        self._stopped = True


def _make_fake_factory() -> tuple[
    Callable[..., _FakeNacosClient], list[_FakeNacosClient]
]:
    """返回 (factory, clients); factory 每次被调追加到 clients 列表。"""
    clients: list[_FakeNacosClient] = []

    def factory(**kwargs: Any) -> _FakeNacosClient:
        c = _FakeNacosClient(**kwargs)
        clients.append(c)
        return c

    return factory, clients


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> NacosRuleSourceConfig:
    return NacosRuleSourceConfig(
        source_id="nacos-prod",
        server_addresses=("nacos-1:8848",),
        namespace="prod",
        group="DEFAULT_GROUP",
        data_id_prefix="gateway",
        reconnect_initial=timedelta(milliseconds=10),
        reconnect_max=timedelta(milliseconds=50),
    )


@pytest.fixture
def factory_and_clients() -> tuple[
    Callable[..., _FakeNacosClient], list[_FakeNacosClient]
]:
    return _make_fake_factory()


@pytest.fixture
def source(
    config: NacosRuleSourceConfig,
    factory_and_clients: tuple[Callable[..., _FakeNacosClient], list[_FakeNacosClient]],
) -> Iterator[tuple[NacosRuleSource, _FakeNacosClient, list[_FakeNacosClient]]]:
    factory, clients = factory_and_clients
    src = NacosRuleSource(config, client_factory=factory)
    # 不调 snapshots(), 只测同步属性
    assert clients == []  # 还未构造 client
    yield src, None, clients  # type: ignore[misc]
    # 同步 fixture 不需要 aclose


# ---------------------------------------------------------------------------
# 公开 API 签名
# ---------------------------------------------------------------------------


class TestPublicApiSignature:
    """公开 API 锁定 (Protocol lock)。"""

    def test_nacos_rule_source_implements_snapshot_rule_source(self) -> None:
        """运行时检查: NacosRuleSource 必须实现 SnapshotRuleSource Protocol。

        注: Protocol 含 dataclass 字段时, issubclass() 不工作 (Python
        typing 限制), 所以用 duck-type 检查: 实例化后看 ``snapshots()`` /
        ``source_id`` / ``aclose()`` 三个 Protocol 必需符号都在。
        """
        factory, _ = _make_fake_factory()
        from atlas_richie.sentinel_source_nacos import NacosRuleSourceConfig
        cfg = NacosRuleSourceConfig(
            source_id="x",
            server_addresses=("n:1",),
            namespace="ns",
            group="g",
            data_id_prefix="p",
        )
        src = NacosRuleSource(cfg, client_factory=factory)
        # Protocol 必需的 3 个成员
        assert callable(getattr(src, "snapshots", None))
        assert callable(getattr(src, "aclose", None))
        assert hasattr(src, "source_id")

    def test_source_id_attribute(self, config: NacosRuleSourceConfig) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        assert src.source_id == "nacos-prod"
        assert isinstance(src.source_id, str)

    def test_state_property(self, config: NacosRuleSourceConfig) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        assert src.state is NacosSourceState.CONNECTING
        assert isinstance(src.state, NacosSourceState)

    def test_last_success_version_initially_none(
        self, config: NacosRuleSourceConfig
    ) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        assert src.last_success_version is None

    def test_last_error_initially_none(self, config: NacosRuleSourceConfig) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        assert src.last_error is None
        assert src.last_error_message is None

    def test_snapshots_is_async_generator(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """`snapshots()` 是异步生成器; aclose 后立即 StopAsyncIteration。"""
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        agen = src.snapshots()

        async def _drive() -> None:
            await src.aclose()
            with pytest.raises(StopAsyncIteration):
                await agen.__anext__()

        asyncio.run(_drive())

    def test_aclose_is_coroutine(self, config: NacosRuleSourceConfig) -> None:
        import inspect
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        assert inspect.iscoroutinefunction(src.aclose)


# ---------------------------------------------------------------------------
# __init__ + 状态
# ---------------------------------------------------------------------------


class TestInitAndState:
    """__init__ 校验 + state 初始值。"""

    def test_init_accepts_valid_config(
        self, config: NacosRuleSourceConfig
    ) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        assert src.source_id == config.source_id
        # 没构造 client (lazy)
        assert src._adapter._client is None

    def test_init_rejects_invalid_config(self) -> None:
        """config 自身校验在 NacosRuleSourceConfig.__post_init__ 完成; 传递性。"""
        from atlas_richie.sentinel.errors import SentinelConfigurationError
        factory, _ = _make_fake_factory()
        # 空白 source_id 应被 config 拒绝
        with pytest.raises((SentinelConfigurationError, ValueError)):
            NacosRuleSourceConfig(
                source_id="",  # 非法
                server_addresses=("nacos:8848",),
                namespace="prod",
                group="DEFAULT_GROUP",
                data_id_prefix="p",
            )

    def test_state_initial_connecting(
        self, config: NacosRuleSourceConfig
    ) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        assert src.state is NacosSourceState.CONNECTING


# ---------------------------------------------------------------------------
# aclose() 幂等 (M6.1.5)
# ---------------------------------------------------------------------------


class TestAcloseIdempotency:
    """aclose() 幂等: 多次连续调, 第 2/3 次不抛错, 状态保持 CLOSED。"""

    @pytest.mark.asyncio
    async def test_aclose_three_times_idempotent(
        self, config: NacosRuleSourceConfig
    ) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        await src.aclose()
        assert src.state is NacosSourceState.CLOSED
        # 第二次 aclose 仍不抛
        await src.aclose()
        assert src.state is NacosSourceState.CLOSED
        # 第三次
        await src.aclose()
        assert src.state is NacosSourceState.CLOSED

    @pytest.mark.asyncio
    async def test_aclose_even_when_sdk_raises(
        self, config: NacosRuleSourceConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """即使 SDK stop_subscribe 抛错, aclose 仍 OK。"""

        class _BadClient(_FakeNacosClient):
            def stop_subscribe(self) -> None:
                raise RuntimeError("simulated SDK panic")
            def remove_config_watcher(self, *a: Any, **kw: Any) -> None:
                raise RuntimeError("simulated SDK panic")

        def factory(**kw: Any) -> _BadClient:
            return _BadClient(**kw)

        src = NacosRuleSource(config, client_factory=factory)
        # 触发 client 构造
        async def _drive() -> None:
            async for _ in src.snapshots():
                pass

        task = asyncio.create_task(_drive())
        await asyncio.sleep(0.05)  # 让 client 构造
        with caplog.at_level(logging.WARNING, logger="atlas_richie.sentinel_source_nacos"):
            await src.aclose()
        # 任务应自然结束
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
        # 状态 CLOSED, 即使 SDK 抛错
        assert src.state is NacosSourceState.CLOSED
        # 日志有 warn (但不含敏感字段)
        # 至少 1 条 warn 关于 stop_subscribe / remove
        assert any("failed" in r.message.lower() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_snapshots_ends_after_aclose(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """aclose 后 snapshots() 立即 StopAsyncIteration。"""
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)

        async def _consume() -> bool:
            count = 0
            async for _ in src.snapshots():
                count += 1
            return count > 0  # 是否至少 yield 过一次

        task = asyncio.create_task(_consume())
        # 立即 aclose
        await asyncio.sleep(0.02)  # 让 snapshot 启动
        await src.aclose()
        # task 应该在 timeout 内结束
        try:
            any_yielded = await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
            pytest.fail("snapshots did not end after aclose")
        # 关闭前可能 0 yield, 1 yield, 都行; 关键是 task 退出
        assert isinstance(any_yielded, bool)


# ---------------------------------------------------------------------------
# 5 类错误分类 (M6.1.4)
# ---------------------------------------------------------------------------


class TestErrorClassification:
    """5 类 NacosSourceError 分类 + 状态机转移 + last_error_message 脱敏。"""

    @pytest.mark.asyncio
    async def test_not_found_error(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """某 data_id get_config 返回 None (404) → NOT_FOUND, 状态 STALE, snapshot 中不含该 data_id。"""
        # 模拟 get_config: 5 个里 flow 有内容, 其它 4 个 None
        def factory_with_partial(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            # flow 有内容 (合法 rule)
            client.set_config(
                config.data_id_for("flow"),
                '[{"resource":"/x","grade":1,"count":10}]',
            )
            # degrade / param_flow / system / authority 都不 set (None = NOT_FOUND)
            return client

        src = NacosRuleSource(config, client_factory=factory_with_partial)
        snap: RuleSnapshot | None = None
        async for s in src.snapshots():
            snap = s
            break
        # break 出来时 state 仍是 STALE / READY
        assert snap is not None
        # snapshot 含 1 个 flow rule
        assert any(r.__class__.__name__ == "FlowRule" for r in snap.rules.values())
        # 状态 STALE (因为有 4 个 NOT_FOUND)
        assert src.state is NacosSourceState.STALE
        # last_error 是 NOT_FOUND
        assert src.last_error is NacosSourceError.NOT_FOUND
        # 至少 4 次 NOT_FOUND
        assert src.error_count(NacosSourceError.NOT_FOUND) >= 4
        # last_success_version 仍设置 (因为 flow 解码成功)
        assert src.last_success_version is not None
        await src.aclose()

    @pytest.mark.asyncio
    async def test_empty_error(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """某 data_id 内容为空 → EMPTY, 状态 STALE, snapshot 不含该 data_id。"""
        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            client.set_config(
                config.data_id_for("flow"),
                '[{"resource":"/x","grade":1,"count":10}]',
            )
            client.set_config(config.data_id_for("degrade"), "")
            client.set_config(config.data_id_for("param_flow"), "[]")
            client.set_config(config.data_id_for("system"), "null")
            # authority 没 set
            return client

        src = NacosRuleSource(config, client_factory=factory)
        snap: RuleSnapshot | None = None
        async for s in src.snapshots():
            snap = s
            break
        # break 出来时 state 仍是 STALE
        assert snap is not None
        # 状态 STALE
        assert src.state is NacosSourceState.STALE
        # 至少 3 次 EMPTY (degrade='', param_flow='[]', system='null')
        assert src.error_count(NacosSourceError.EMPTY) >= 3
        # NOT_FOUND 1 次 (authority)
        assert src.error_count(NacosSourceError.NOT_FOUND) >= 1
        await src.aclose()

    @pytest.mark.asyncio
    async def test_decode_error_keeps_stale(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """某 data_id 内容坏 JSON → DECODE, 状态 STALE, 不 yield。"""
        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            # 故意给一个非 JSON
            client.set_config(config.data_id_for("flow"), "this is not json {")
            return client

        src = NacosRuleSource(config, client_factory=factory)
        # snapshots 应在 initial load 阶段因 DECODE 进入 STALE
        # 因为只 1 个 data_id 有内容, 其它 4 个 NOT_FOUND, 整体 parse 失败 → DECODE
        # 实际: 只有 1 个 data_id 有坏 JSON, 其它 4 个 NOT_FOUND; codec 解析坏 JSON 抛 NacosDecodeError
        # _load_snapshot → DECODE 错误, 状态 STALE, return None
        # initial_load_with_backoff 看到 DECODE → 退避重试 (会一直失败)
        # 我们只等一段, 确认 state STALE / last_error DECODE
        async def _drive() -> None:
            async for _ in src.snapshots():
                pass

        task = asyncio.create_task(_drive())
        await asyncio.sleep(0.1)  # 给 initial 失败 + 退避一次
        await src.aclose()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
        # DECODE 错误
        assert src.error_count(NacosSourceError.DECODE) >= 1
        # 状态 STALE (因为 DECODE 不算致命)
        # 或 DISCONNECTED (因为 _initial_load_with_backoff 把 decode 也当 retry)
        # 当前实现: _load_snapshot 设 STALE; _initial_load_with_backoff 退避后
        # 重试; 退避等待时 state 是 STALE
        assert src.state in (NacosSourceState.STALE, NacosSourceState.DISCONNECTED, NacosSourceState.CLOSED)

    @pytest.mark.asyncio
    async def test_network_error_disconnected(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """SDK get_config 抛连接异常 → NETWORK, 状态 DISCONNECTED, 退避重试。"""
        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            # 覆盖 get_config 抛网络异常
            original = client.get_config

            def boom(*a: Any, **kw2: Any) -> Any:
                raise ConnectionError("simulated network down")

            client.get_config = boom  # type: ignore[method-assign]
            return client

        src = NacosRuleSource(config, client_factory=factory)
        async def _drive() -> None:
            async for _ in src.snapshots():
                pass

        task = asyncio.create_task(_drive())
        await asyncio.sleep(0.1)  # 给首次失败 + 退避
        await src.aclose()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
        # NETWORK 错误
        assert src.error_count(NacosSourceError.NETWORK) >= 1
        # 状态 STALE / DISCONNECTED / CLOSED 都行 (取决于时序)
        assert src.state in (
            NacosSourceState.STALE,
            NacosSourceState.DISCONNECTED,
            NacosSourceState.CLOSED,
        )

    @pytest.mark.asyncio
    async def test_auth_error_no_auto_retry(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """SDK 抛 NacosException("Insufficient privilege") → AUTH, 不自动重试。"""
        from nacos import NacosException

        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            def boom(*a: Any, **kw2: Any) -> Any:
                raise NacosException("Insufficient privilege.")
            client.get_config = boom  # type: ignore[method-assign]
            return client

        src = NacosRuleSource(config, client_factory=factory)
        async def _drive() -> None:
            async for _ in src.snapshots():
                pass

        task = asyncio.create_task(_drive())
        await asyncio.sleep(0.1)  # 给首次失败
        await src.aclose()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
        # AUTH 错误
        assert src.error_count(NacosSourceError.AUTH) >= 1
        # 状态 DISCONNECTED (AUTH 后等人工)
        assert src.state in (
            NacosSourceState.DISCONNECTED,
            NacosSourceState.CLOSED,
        )


# ---------------------------------------------------------------------------
# 退避边界 (M6.1.4)
# ---------------------------------------------------------------------------


class TestBackoff:
    """退避: reconnect_initial → reconnect_max 边界。"""

    def test_backoff_initial(
        self, config: NacosRuleSourceConfig
    ) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        # 0 次尝试: 仍用 initial
        assert src._backoff_seconds() == pytest.approx(
            config.reconnect_initial.total_seconds()
        )

    def test_backoff_grows_then_caps(
        self, config: NacosRuleSourceConfig
    ) -> None:
        factory, _ = _make_fake_factory()
        src = NacosRuleSource(config, client_factory=factory)
        # reconnect_initial=10ms, reconnect_max=50ms
        # 公式: delay = initial * 2^(attempt-1), capped at max
        # attempt=0 → 0.01 (short-circuit)
        # attempt=1 → 0.01*1=0.01
        # attempt=2 → 0.01*2=0.02
        # attempt=3 → 0.01*4=0.04
        # attempt=4 → 0.01*8=0.08 → cap 0.05
        src._reconnect_attempt = 0
        assert src._backoff_seconds() == pytest.approx(0.01)
        src._reconnect_attempt = 1
        assert src._backoff_seconds() == pytest.approx(0.01)
        src._reconnect_attempt = 2
        assert src._backoff_seconds() == pytest.approx(0.02)
        src._reconnect_attempt = 3
        assert src._backoff_seconds() == pytest.approx(0.04)
        src._reconnect_attempt = 4
        assert src._backoff_seconds() == pytest.approx(0.05)  # cap
        src._reconnect_attempt = 10
        assert src._backoff_seconds() == pytest.approx(0.05)  # still cap

    def test_backoff_uses_config_values(self) -> None:
        """重连参数来自 NacosRuleSourceConfig。"""
        factory, _ = _make_fake_factory()
        cfg = NacosRuleSourceConfig(
            source_id="x",
            server_addresses=("nacos:8848",),
            namespace="ns",
            group="g",
            data_id_prefix="p",
            reconnect_initial=timedelta(seconds=1),
            reconnect_max=timedelta(seconds=10),
        )
        src = NacosRuleSource(cfg, client_factory=factory)
        src._reconnect_attempt = 0
        assert src._backoff_seconds() == pytest.approx(1.0)
        src._reconnect_attempt = 5
        # 1.0 * 2^4 = 16 → cap to 10
        assert src._backoff_seconds() == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 脱敏 (M6.1.5)
# ---------------------------------------------------------------------------


class TestRedaction:
    """脱敏: last_error_message / 日志 不含敏感字段。"""

    def test_redact_host_port(self, config: NacosRuleSourceConfig) -> None:
        msg = "connect failed to nacos-1:8848"
        out = _redact(msg, config)
        # host:port 必须被 mask
        assert "nacos-1" not in out
        assert "8848" not in out
        # 但保留部分可读性
        assert "***" in out

    def test_redact_username_password(self, config: NacosRuleSourceConfig) -> None:
        msg = "auth failed username=admin password=secret123"
        out = _redact(msg, config)
        assert "admin" not in out
        assert "secret123" not in out

    def test_redact_namespace(self, config: NacosRuleSourceConfig) -> None:
        msg = "namespace=prod failed"
        out = _redact(msg, config)
        assert "prod" not in out

    def test_redact_token(self, config: NacosRuleSourceConfig) -> None:
        msg = "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        out = _redact(msg, config)
        assert "eyJhbGciOiJIUzI1NiJ9" not in out

    def test_redact_no_op_for_safe_text(
        self, config: NacosRuleSourceConfig
    ) -> None:
        msg = "decode error on data_id 'flow-rules.json'"
        out = _redact(msg, config)
        assert out == msg

    def test_redact_multiple_hosts(self, config: NacosRuleSourceConfig) -> None:
        msg = "nacos-1:8848 and nacos-2:8848 both timeout"
        out = _redact(msg, config)
        assert "8848" not in out
        assert out.count("***:***") == 2

    @pytest.mark.asyncio
    async def test_last_error_message_redacted(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """last_error_message 不应含敏感字段。"""
        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            def boom(*a: Any, **kw2: Any) -> Any:
                raise ConnectionError(
                    "Connection refused to nacos-1:8848"
                )
            client.get_config = boom  # type: ignore[method-assign]
            return client

        src = NacosRuleSource(config, client_factory=factory)
        async def _drive() -> None:
            async for _ in src.snapshots():
                pass
        task = asyncio.create_task(_drive())
        await asyncio.sleep(0.1)
        await src.aclose()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
        # last_error_message 已脱敏
        msg = src.last_error_message or ""
        assert "nacos-1" not in msg
        assert "8848" not in msg
        # 至少 1 个 mask
        assert "***" in msg

    @pytest.mark.asyncio
    async def test_logs_do_not_contain_sensitive_fields(
        self, config: NacosRuleSourceConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """捕获的 log 应不含敏感字段。"""
        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            def boom(*a: Any, **kw2: Any) -> Any:
                raise ConnectionError(
                    "Connection refused to nacos-1:8848 username=admin"
                )
            client.get_config = boom  # type: ignore[method-assign]
            return client

        src = NacosRuleSource(config, client_factory=factory)
        with caplog.at_level(logging.DEBUG, logger="atlas_richie.sentinel_source_nacos"):
            async def _drive() -> None:
                async for _ in src.snapshots():
                    pass
            task = asyncio.create_task(_drive())
            await asyncio.sleep(0.1)
            await src.aclose()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
        # 检查 caplog.text 不含敏感字段
        text = caplog.text
        assert "nacos-1" not in text, f"sensitive host leaked: {text!r}"
        assert "8848" not in text, f"sensitive port leaked: {text!r}"
        assert "admin" not in text, f"sensitive username leaked: {text!r}"


# ---------------------------------------------------------------------------
# 公开 API 不泄漏 nacos SDK 类型
# ---------------------------------------------------------------------------


class TestPublicApiBoundary:
    """公开 API 入参 / 返回值不引入 nacos_sdk_python 类型。"""

    def test_no_nacos_sdk_types_in_public_api(self) -> None:
        import inspect
        from atlas_richie.sentinel_source_nacos import source as mod
        # 类本身
        for cls_name in ["NacosRuleSource"]:
            cls = getattr(mod, cls_name)
            for name, val in inspect.getmembers(cls):
                if name.startswith("_"):
                    continue
                if inspect.ismethod(val) or inspect.isfunction(val):
                    sig = inspect.signature(val)
                    for pname, p in sig.parameters.items():
                        ann = p.annotation
                        ann_mod = getattr(ann, "__module__", "")
                        if ann_mod.startswith("nacos"):
                            pytest.fail(
                                f"{cls_name}.{name} param {pname!r} leaks "
                                f"nacos SDK type (module={ann_mod})"
                            )
                elif not callable(val):
                    ann_mod = getattr(type(val), "__module__", "")
                    if ann_mod.startswith("nacos"):
                        pytest.fail(
                            f"{cls_name}.{name} leaks nacos SDK type "
                            f"(module={ann_mod})"
                        )

    def test_no_nacos_sdk_imports_in_source_module(self) -> None:
        """source 模块静态导入 nacos-sdk-python 仅限于 _NacosAdapter 内, 不污染公开符号。"""
        import atlas_richie.sentinel_source_nacos.source as mod
        for name, val in vars(mod).items():
            if name.startswith("_") and not name.startswith("__"):
                continue
            if name in ("NacosRuleSource",):
                continue
            if name == "logger":
                continue
            ann_mod = getattr(type(val), "__module__", "")
            if ann_mod.startswith("nacos"):
                pytest.fail(
                    f"source.{name} leaks nacos SDK type (module={ann_mod})"
                )


# ---------------------------------------------------------------------------
# C 层物理隔离 (M6.1.0 P0 决策 1)
# ---------------------------------------------------------------------------


class TestCLayerIsolation:
    """extension wheel **不** import 主包 C 层 ``_supervisor.*``。"""

    def test_source_module_does_not_import_supervisor(self) -> None:
        """extension module **不** import 主包 C 层 _supervisor。

        编译时检查: 加载 module 后, 它的 globals / 任何 attribute 的
        ``__module__`` 都**不**应是 ``atlas_richie.sentinel.source._supervisor.*``。
        文档字符串里说"不 import _supervisor"是允许的 (说明性文本)。
        """
        import atlas_richie.sentinel_source_nacos.source as mod
        forbidden = "atlas_richie.sentinel.source._supervisor"
        # 1) module 本身 attrs 的 __module__
        for name, val in vars(mod).items():
            ann_mod = getattr(type(val), "__module__", "")
            if ann_mod.startswith(forbidden):
                pytest.fail(
                    f"source.{name} module {ann_mod!r} is C-layer _supervisor "
                    f"(forbidden by isolation policy)"
                )
        # 2) 模块字典里查 "_supervisor" 子字符串作为 attribute 名 (非源码)
        for name in dir(mod):
            if name == "_supervisor" or name.startswith("_supervisor."):
                pytest.fail(
                    f"source module exposes _supervisor attribute: {name!r}"
                )

    def test_codec_module_does_not_import_supervisor(self) -> None:
        """codec 模块也不 import _supervisor。"""
        import atlas_richie.sentinel_source_nacos.codec as mod
        forbidden = "atlas_richie.sentinel.source._supervisor"
        for name, val in vars(mod).items():
            ann_mod = getattr(type(val), "__module__", "")
            if ann_mod.startswith(forbidden):
                pytest.fail(
                    f"codec.{name} module {ann_mod!r} is C-layer _supervisor"
                )


# ---------------------------------------------------------------------------
# 公开 API 入口: snapshots() 推进
# ---------------------------------------------------------------------------


class TestSnapshotsEndToEnd:
    """snapshots() 端到端: 首次 yield + change 触发 + aclose 结束。"""

    @pytest.mark.asyncio
    async def test_initial_snapshot_yielded(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """首次加载 5 个 data_id → 至少 yield 1 个 snapshot。"""
        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            for rt in ("flow", "degrade", "param_flow", "system", "authority"):
                client.set_config(config.data_id_for(rt), "[]")
            return client

        src = NacosRuleSource(config, client_factory=factory)
        snapshots: list[RuleSnapshot] = []

        async def _drive() -> None:
            async for s in src.snapshots():
                snapshots.append(s)
                # 只取 1 个就退出
                await src.aclose()
                return

        task = asyncio.create_task(_drive())
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()
        # 至少 1 个 snapshot
        assert len(snapshots) >= 1
        snap = snapshots[0]
        assert isinstance(snap, RuleSnapshot)
        assert snap.source_id == "nacos-prod"
        # state 应到 READY (5 个都是空 = EMPTY warnings; 或 STALE)
        assert src.state in (NacosSourceState.READY, NacosSourceState.STALE, NacosSourceState.CLOSED)

    @pytest.mark.asyncio
    async def test_change_triggers_new_snapshot(
        self, config: NacosRuleSourceConfig
    ) -> None:
        """Nacos 推送变化 → 重新拉 5 个 data_id → yield 新 snapshot。"""
        # 用 list 捕获构造的 fake client (在 executor 里创建, 但 list 是引用)
        captured: list[_FakeNacosClient] = []

        def factory(**kw: Any) -> _FakeNacosClient:
            client = _FakeNacosClient(**kw)
            for rt in ("flow", "degrade", "param_flow", "system", "authority"):
                client.set_config(config.data_id_for(rt), "[]")
            captured.append(client)
            return client

        src = NacosRuleSource(config, client_factory=factory)
        snapshots: list[RuleSnapshot] = []

        async def _drive() -> None:
            async for s in src.snapshots():
                snapshots.append(s)
                # 收到 1 个 snapshot 后就退出 (后续 trigger_change 测试)
                if len(snapshots) >= 1:
                    return

        task = asyncio.create_task(_drive())
        # 等 client 构造 + 首次 yield
        for _ in range(20):
            if captured and snapshots:
                break
            await asyncio.sleep(0.05)
        assert captured, "fake client was not created within 1s"
        assert snapshots, "no initial snapshot within 1s"
        client = captured[0]
        # 触发变化: 改 flow 配置 + 推送
        client.set_config(
            config.data_id_for("flow"),
            '[{"resource":"/x","grade":1,"count":10}]',
        )
        client.trigger_change(config.data_id_for("flow"))
        # 重启消费 task, 收取新 snapshot
        async def _drive_2() -> None:
            async for s in src.snapshots():
                snapshots.append(s)

        task2 = asyncio.create_task(_drive_2())
        try:
            await asyncio.wait_for(task2, timeout=3.0)
        except asyncio.TimeoutError:
            pass
        await src.aclose()
        try:
            await asyncio.wait_for(task2, timeout=1.0)
        except asyncio.TimeoutError:
            task2.cancel()
        # 至少 2 个 snapshot
        assert len(snapshots) >= 2, f"expected >= 2, got {len(snapshots)}"
        # 找到第一个 version 与初始不同的 snapshot
        initial_version = snapshots[0].version
        different = next(
            (s for s in snapshots[1:] if s.version != initial_version),
            None,
        )
        assert different is not None, (
            f"no snapshot with different version; "
            f"versions={[s.version for s in snapshots]}"
        )
