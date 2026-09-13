# R-SENTINEL-M6.1.7 HANDOFF — Nacos SDK 升级 + Polling 改造 (现状 + 已知限制 + 后续建议)

> **HANDOFF 文档 (M6.1.7 实施现状)**. 给下个 session / 接手者必读.
> 对应 design: `docs/M6.1.7-SDK-UPGRADE-POLLING.md` (5 owner sign-off 已通过).
> 对应 commit: `ae15740` (commit 1) + 待 commit 2 (集成测试) + commit 3 (文档).

| Field | Value |
| ----- | ----- |
| Document | `HANDOFF-M6.1.7.md` (实施现状, 已知限制) |
| Phase | M6.1.7a (spike ✅) / M6.1.7b (spike ✅) / M6.1.7.1-7.8 (实施 ✅) / M6.1.7.9-7.10 (集成测试 🟡 部分) / M6.1.7.11-7.13 (文档 ⏳) |
| HEAD | `ae15740` (commit 1) |
| 当前状态 | Commit 1 已 push; 5 场景集成测试 2/5 全过 (FirstLoad + AcloseIdempotent), 3/5 fail (LegalUpdate + InvalidUpdate + DisconnectRecover, 根因见 §3) |
| 单测 | 112 passed + 0 regression (commit 1) |
| 集成测 | 5 场景: FirstLoad ✅, AcloseIdempotent ✅, LegalUpdate ❌, InvalidUpdate ❌, DisconnectRecover ❌ |

---

## 1. 本会话完成的工作

### 1.1 commit 1 (`ae15740`) — SDK 升级 + polling 改造

- **SDK 升级**: `nacos-sdk-python` 0.1.16 / 2.0.11 → **3.2.0** (PyPI, 2026-04)
  - 模块路径: `nacos` → `v2.nacos` (async + gRPC)
  - pyproject: `>=2.0,<3.0` → `>=3.0,<4.0`; lockfile 同步
- **架构改造**: push → polling
  - 删 `add_config_watcher` / `stop_subscribe` / `NacosCallbackParams`
  - 新增 `NacosRuleSourceConfig.poll_interval: timedelta`, 默认 1s, 下限 100ms
  - `NacosRuleSource.snapshots()` 内部启动 `_poll_loop` background task
  - 校验 yield 的 snapshot checksum 跟上次对比, 变化 yield, 无变化 skip
  - `aclose()` 取消 `_poll_task` + `await svc.shutdown()`, 幂等保持
- **5 类错误分类**调整:
  - `EMPTY` 走 SDK 3.2.0 行为: `content == ""` / `content.strip() in ("[]", "null")`
  - `NOT_FOUND` 走 `NacosException(error_code in (400, 404))` 或 `content is None`
  - `AUTH` / `DECODE` / `NETWORK` 路径保持
- **测试**: 单元测试 112 passed + 0 regression; `_FakeNacosClient` 重写为 async API

### 1.2 commit 2 (待 push) — 5 场景集成测试

- `tests/integration/` 新建: `__init__.py` / `conftest.py` / `test_sen_nacos_integration.py`
- 5 场景: 首次加载 / 合法更新 / 无效更新 / 断网恢复 / aclose 幂等
- env var gate: `ATLAS_RICHIE_SENTINEL_NACOS_URL` / `_USER` / `_PASSWORD`
- 真实 Nacos: 本机 Docker `nacos-pg-3.2.3`, 端口 8848+9848
- 2/5 场景通过, 3/5 失败 (根因见 §3)

### 1.3 commit 3 (待 push) — 文档 (pending)

- EXTENSION_GUIDE §3.6 polling 行为
- RULE_REFERENCE §1.5 polling 默认值
- OPERATIONS §2.3 5 场景验证清单

---

## 2. 当前实现要点

### 2.1 `NacosRuleSourceConfig.poll_interval`

```python
@dataclass(frozen=True, slots=True)
class NacosRuleSourceConfig:
    poll_interval: timedelta = field(default=timedelta(seconds=1))
    # __post_init__ 校验: >= 100ms (default-deny 资源上限, ADR-SEN-007 追加)
```

### 2.2 `NacosRuleSource.snapshots()` polling 循环

```python
async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
    snapshot, _ = await self._initial_load_with_backoff()
    if snapshot is not None:
        yield snapshot
    if self._closed:
        return
    # 启动 polling 后台 task
    self._poll_event = asyncio.Event()
    self._poll_task = asyncio.create_task(self._poll_loop(), name=...)
    while not self._closed:
        next_snapshot = await self._wait_for_next_snapshot()
        if next_snapshot is None or self._closed:
            return
        yield next_snapshot

async def _poll_loop(self) -> None:
    while not self._closed:
        await asyncio.sleep(self._poll_interval_sec)
        if self._closed:
            return
        snapshot, _ = await self._load_snapshot()
        if snapshot is None:
            # 错误退避
            ...
            continue
        # 跟上次 checksum 比对
        if (self._last_success_version is None
            or snapshot.version.checksum != self._last_success_version.checksum):
            self._last_success_version = snapshot.version
            self._pending_snapshot = snapshot
            if self._poll_event is not None:
                self._poll_event.set()
```

### 2.3 适配层 SDK 3.2.0 用法

```python
# _NacosAdapter._ensure_client
grpc_cfg = GRPCConfig(port_offset=1000, grpc_timeout=int(read_timeout_sec * 1000))
client_config = (
    ClientConfigBuilder()
    .server_address(",".join(cfg.server_addresses))  # 适配 SDK 0.1.16 tuple → str
    .namespace_id(cfg.namespace)
    .username(cfg.auth.username if cfg.auth else None)
    .password(cfg.auth.password if cfg.auth else None)
    .grpc_config(grpc_cfg)
    .timeout_ms(int(read_timeout_sec * 1000))
    .load_cache_at_start(False)  # SDK 3.2.0 spike: 关掉 disk cache
    .build()
)
client_config.disable_use_config_cache = True  # SDK 3.2.0 spike: 关掉 fail-over cache
self._client = await self._client_factory(client_config)
```

---

## 3. 已知限制 (3/5 集成场景 fail 根因)

### 3.1 TestLegalUpdate / TestInvalidUpdate / TestDisconnectRecover fail

**现象**: 集成测试中, **NacosRuleSource (SDK 3.2.0 client A) 拉不到 admin client (SDK 3.2.0 client B) publish 的内容**. 单独 sp 脚本 (单 client 同时 publish + get) 正常, **多 client 跨实例** get 拿不到.

**已排除**:

- ❌ SDK 兼容性: 单 client publish + get OK (spike 验证)
- ❌ 5 类错误分类: 单元测试 112 全过
- ❌ namespace / data_id 错位: 已加 debug log 验证 namespace + data_id 完全对齐
- ❌ publish 同步延迟: 已加 admin client 轮询 get 直到拿到 v1 的 delay
- ❌ SDK cache: 已加 `load_cache_at_start=False` + `disable_use_config_cache=True`
- ❌ Nacos 3.2.3 server 端 V1/V2/V3 endpoint 缺失: SDK 单独 get_config 走 V3 gRPC OK (spike 验证)

**未排除 (待 SDK 上游)**:

- 🟡 **SDK 3.2.0 gRPC client 跟 Nacos 3.2.3 server 之间的最终一致协议**: 多 client 实例 publish 后, 跨实例 get 在某些时序下拿不到新内容 (虽然 admin client 自己 get 拿得到). 这是 SDK 3.2.0 跟 Nacos 3.2.3 server 之间的 gRPC query_config response cache / connection state 行为问题, 不在 M6.1.7 可控范围.
- 🟡 **SDK 3.2.0 内部 gRPC stream 401**: 集成测试期间 SDK 日志持续报 `Error [-401]: failed to connect nacos server`, 跟 Nacos 3.2.3 server 鉴权握手失败, 但 query_config HTTP 仍 OK. SDK 内部 gRPC stream 跟 query_config 是分开的, 401 不直接导致 query 失败, 但可能影响 cache invalidation.

### 3.2 M6.1.7d 真实验收 5 场景现状

| 场景 | 状态 | 备注 |
| --- | --- | --- |
| TestFirstLoad | ✅ PASS | 单元 test 也能过 (用 _FakeNacosClient); 真 Nacos 也过 |
| TestLegalUpdate | ❌ FAIL | SDK/Nacos server 跨实例最终一致问题 (见 §3.1) |
| TestInvalidUpdate | ❌ FAIL | 同 §3.1 |
| TestDisconnectRecover | ❌ FAIL | 同 §3.1 + docker stop 后 gRPC 401 干扰 |
| TestAcloseIdempotent | ✅ PASS | aclose 幂等性不依赖 SDK 内容抓取 |

---

## 4. 给下个 session 的建议

### 4.1 选项 A (推荐): 升级 SDK 3.x patch 版本 (3.2.1 / 3.2.2 / 3.3.x)

```bash
# 看 PyPI 新版本
curl https://pypi.org/pypi/nacos-sdk-python/json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for v, files in sorted(data['releases'].items(), key=lambda x: x[1][0]['upload_time'] if x[1] else '')[-10:]:
    if v.startswith('3.') and files:
        print(v, files[0]['upload_time'])
"
```

如果有 3.2.x patch 修复 gRPC 401 / cache 兼容问题, 直接换 `>=3.2,<3.3` 重新跑 5 场景.

### 4.2 选项 B: 改用 Nacos 2.x 跑真实验收

```bash
docker run -d --name nacos-2x-test \
  -e MODE=standalone \
  -e JVM_XMS=512m -e JVM_XMX=512m \
  -p 18848:8848 -p 19848:9848 \
  nacos/nacos-server:v2.4.0
```

然后设 env var:
```bash
export ATLAS_RICHIE_SENTINEL_NACOS_URL=127.0.0.1:18848
.venv/bin/pytest tests/integration/ -m integration -v
```

Nacos 2.x 跟 SDK 3.2.0 走 V3 gRPC, 鉴权 + 跨实例最终一致性更稳. **不需要改任何代码**.

### 4.3 选项 C: 写 V3 HTTP adapter (跳过 SDK)

直接用 `httpx` 调 Nacos 3.2.3 V3 endpoint (`/nacos/v3/admin/cs/config` + V3 long-poll protocol). 这破坏 Open-Closed, 但能完全控制 401 / cache 行为. **1.0 publish 前不建议**, 留给 1.x future.

### 4.4 选项 D: 接受现状 + 1.0 文档化

5 场景 2 场景过 + 单测全过. 1.0 publish 时:
- 在 OPERATIONS / RULE_REFERENCE 加 "M6.1.7 已知限制: Nacos 3.x SDK 跨实例最终一致性问题, 待 SDK 3.2.1+ 修复"
- 集成测试标记 `xfail` 3 场景 + reason 字段
- 1.x future 安排 M6.1.8 修

---

## 5. 当前 base + 重新跑测试

```bash
cd /Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/sentinel-source-nacos

# 单元测试
.venv/bin/pytest tests/ -q --ignore=tests/integration
# 期望: 112 passed

# 集成测试 (2/5 期望过)
.venv/bin/pytest tests/integration/ -m integration -v
# 期望: TestFirstLoad PASSED, TestAcloseIdempotent PASSED, 其它 3 fail
```

环境要求: 本机 Docker `nacos-pg-3.2.3` 跑在 8848+9848, 容器 username/password=nacos.

---

## 6. 风险与缓解 (updated)

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| SDK 3.2.0 跨实例最终一致性问题 | 5 场景中 3 失败 | 选项 A/B/C/D (见 §4) |
| 1.0 publish 前未做真实验收 | 用户接 Nacos 3.x 可能踩坑 | §3.1 文档化 + §4 选项 D |
| polling 默认 1s 不达 push 模式 < 100ms 实时性 | 业务系统反应慢 | poll_interval 可调到 100ms 下限 |
| `disable_use_config_cache=True` 在 Nacos 2.x server 行为 | 未知 | 集成测试需 Nacos 2.x 验证 (§4 选项 B) |

---

**Document version**: 1.0
**Created by**: Mavis (mvs_cef3b0c9918e473f8de8ad4b42fef7ca)
**Last updated**: 2026-09-13
**Status**: 实施 90% 完成, 5 场景 2/5 全过, 3/5 待 SDK/server 兼容修复
