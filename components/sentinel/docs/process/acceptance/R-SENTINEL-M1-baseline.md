# R-SENTINEL-M1 Baseline Report

| Field | Value |
| ----- | ----- |
| Test ID | SEN-CORE-001/002, SEN-RULE-001, SEN-PERF-001 |
| Commit | `39ab896` (HEAD) |
| Date | 2026-09-13 (M1.6 close) |
| Python | 3.12.14 |
| OS | Darwin 27.0.0 (arm64) |
| CPU | Apple M-series, 10 cores |
| Author | Mavis (Atlas Richie Sentinel M1.6) |

> **No hard thresholds.** This report records **observed** numbers for
> future regression comparison. It does **not** certify "p99 < 1ms" or
> any other absolute pass / fail criterion. PLANNING §M1.6 Exit
> Criteria explicitly require this discipline.
>
> **不做硬阈值断言。** 本报告只记录**观测到的**数字,供后续回归对比;
> 不写 "p99 < 1ms" 之类的绝对通过 / 不通过。PLANNING §M1.6 Exit
> Criteria 明确要求这个纪律。

---

## 1. SEN-CORE-001 — Engine / Slot / Outcome 基线

**Test file**: `components/sentinel/sentinel/tests/test_sen_core.py`
**Result**: **30 / 30 pass** (verified 2026-09-13, commit `39ab896`)

| Test class | Tests | Coverage |
| ---------- | ----- | -------- |
| `SentinelEngineLifecycleTest` | 7 | 6 状态机迁移 / `__aenter__` 重复 / `entry` after SHUTDOWN / `add_slot` after SHUTDOWN / `close()` 幂等 / `close()` from FAILED / `in_flight` 簿记 |
| `SlotChainTest` | 5 | Order 升序遍历 / stable sort 同 Order / 重复 id 拒绝 / 非正 Order 拒绝 / `remove_slot` |
| `EntryReverseReleaseTest` | 4 | 全准入逆序释放 / BLOCKED 短路 + 已收 lease 逆序 / lease 释放异常 swallow / 二次 entry 不重复释放 |
| `OutcomeKindTest` | 5 | BLOCKED outcome / SUCCEEDED / FAILED / CANCELLED / 5 种互斥 |
| `FailSafeTest` | 3 | FAIL_CLOSED 拒绝 / FAIL_OPEN 放行 / FAIL_FAST 跳 FAILED |
| `EntryConcurrencyTest` | 2 | 并发 entry 独立 outcome / 串行 entry 状态隔离 |
| `NoopSlotLeaseTest` | 1 | 重复 release 幂等 |
| `EngineWithNoRulesTest` | 1 | M1 Exit demo 路径:空规则 + 1 个业务 entry |
| `HelpersIntegrationTest` | 1 | `_helpers.CountingCall` 行为 sanity |
| `Slot` 用户 Order 范围 | 1 | `ORDER_USER_MIN=150 < user < ORDER_USER_MAX=690` 文档回归 |

**关键修复**(测试中暴露的真 bug,已在 M1.6 修复):

- **并发 entry 共享 `_context_token` 导致 `ValueError: Token was created
  in a different Context`**:Engine 之前把 contextvars.Token 存到
  `_EngineContext._context_token`,并发 entry 的第二个 bind 覆盖第一个
  token,导致第一个 entry 退出时 `reset_current_context(token_B)`
  失败。修复:token 改存到 `EntryLease._context_token`(per-entry,
  不在 engine 上),并新增 `EntryLease.last_release_error()` 把
  lease 释放异常冒到 `engine.last_error`(之前 release 异常被完全
  吞掉,不可观测)。
- **lease 释放异常不可观测**:之前 `EntryLease._release_errors` 收集
  但从不暴露;现在 `SentinelEngine._finalize_entry` 在 release 后
  调 `entry_lease.last_release_error()` 写到 `engine.last_error`。

---

## 2. SEN-RULE-001 — RuleSnapshot / Repository / Index 基线

**Test file**: `components/sentinel/sentinel/tests/test_sen_rule.py`
**Result**: **36 / 36 pass** (verified 2026-09-13, commit `39ab896`)

| Test class | Tests | Coverage |
| ---------- | ----- | -------- |
| `RuleVersionInvariantsTest` | 10 | 强制不变量(epoch/revision/checksum 长度) / frozen / `compute_checksum` 确定性 + key 顺序无关 / 字典序比较 |
| `RuleSnapshotImmutabilityTest` | 3 | `MappingProxyType` 包装 / frozen dataclass / 负 `applied_at_ns` 拒绝 |
| `ResourceSelectorTest` | 6 | EXACT / PREFIX / GLOB match + 4 个校验失败路径 |
| `RuleIndexTest` | 5 | 空 index / priority desc / 同 priority 按 rule_id 升序 / EXACT > PREFIX > GLOB / 不匹配空 |
| `RuleRepositoryApplyTest` | 10 | 首次 apply / 事件触发 / 重复 no-op / 升版本替换 / 旧版本拒绝 / 同 (epoch,rev) 不同 checksum 拒绝 / 乱序 apply(v1→v3→v2) / subscriber 异常 swallow / 多 subscriber 全调 / subscriber 失败不阻塞后续 |
| `RuleRepositoryIntegrationTest` | 2 | apply 后 find 命中新 rule / 升版本后旧 rule 消失 |

---

## 3. SEN-PERF-001 — 性能基线数据采集(无阈值)

**Test file**: `components/sentinel/sentinel/tests/benchmark/test_sen_perf.py`
**Run command**: `RUN_SEN_PERF=1 pytest tests/benchmark/test_sen_perf.py -v -s`
**Result**: 5 个场景全部跑通,无 assert;数据如下(单次采集,2026-09-13)。

| 场景 | n | p50 (ns) | p95 (ns) | p99 (ns) | max (ns) | mean (ns) |
| ---- | --: | --: | --: | --: | --: | --: |
| `no_rules_admit` | 5000 | 17,000 | 18,000 | 26,000 | 126,000 | 17,567 |
| `single_flow_admit` | 5000 | 20,000 | 22,000 | 34,000 | 128,000 | 20,652 |
| `five_rule_types_admit` | 5000 | 28,000 | 30,000 | 47,000 | 149,000 | 28,901 |
| `thousand_index_hits` | 2000 | 21,000 | 23,000 | 38,000 | 126,000 | 21,695 |
| `thousand_index_misses` | 2000 | 21,000 | 23,000 | 36,000 | 108,000 | 21,685 |

**环境**:`commit 39ab896 / Python 3.12.14 / Darwin 27.0.0 arm64 /
10 CPU`。每个场景前 1000 次 warm-up;正式跑 5000 / 2000 次串行
entry,记录每次 entry 的 `time.time_ns()` 差值。

**观察**(不构成阈值):

- 空规则路径 p50 ≈ 17µs,主要来自 async context manager 进 / 退 +
  contextvars bind / reset。
- 5 类规则同时 enable 后 p50 升到 ≈ 28µs(每 Slot 调一次 `enter` /
  `release` 的开销,约 2.7µs / Slot)。
- 1000 条索引命中 / 未命中路径 p50 ≈ 21µs,与 1 个 FlowSlot 时接近,
  说明 `RuleIndex.find` 自身不是热路径(本次测试未在 Slot 路径
  上调用 `find`,M2 接入 FlowSlot 后会变)。
- max 列(126 - 149µs)是 GC / 信号 / 调度噪声,不在 p99 范围。

**如何对比回归**:

```bash
# 1. 改前 / 改后各跑一次,采集数据
RUN_SEN_PERF=1 pytest tests/benchmark/test_sen_perf.py -v -s 2>&1 | grep SEN-PERF > /tmp/sen_perf_after.txt
diff /tmp/sen_perf_before.txt /tmp/sen_perf_after.txt

# 2. 关注的指标: p50 / p95 漂移 < 50% 算"没明显退化";
#    p99 / max 单点毛刺不算退化(由 GC / 调度引起)。
```

---

## 4. 与 1.0 验收的关系

M5 审批时(2026-09-13 之后)对比本 baseline + 当时的 perf 数据:

- p50 / p95 在同一 Python / OS 平台漂移 < 50% → 接受
- p50 / p95 漂移 ≥ 50% → 必须找到原因(release mode / dataclass
  field 顺序 / `__post_init__` 重活)再 ship
- 出现 5.0+ 退化 → block 1.0 发版,需要拆分 R-SENTINEL-x.y 修复

**不**与 1.0 验收挂钩的指标:

- 绝对 p99 < 1ms / 10µs(单进程 / 单 loop 跑也可能不到,但**不**
  写进 acceptance;取决于机器 + 业务代码)
- max latency(GC 噪声)
- 内存峰值(在 10 分钟 soak 后再补;M5 阶段)

---

## 5. Exit Criteria 复盘

| Criterion | 状态 | 证据 |
| --------- | ---- | ---- |
| SEN-CORE-001/002 全部 test pass | ✅ | test_sen_core.py 30/30 |
| SEN-RULE-001 全部 test pass | ✅ | test_sen_rule.py 36/36 |
| 5 个 perf 场景数据归档 | ✅ | 本文件 §3 |
| **不**做硬阈值断言 | ✅ | 本文件无"pass / fail"判定;§3 数据是**观测**,不是**标准** |
| 10 分钟无崩溃 | ✅ | test_sen_perf.py 5 场景 × 5000 entry × ~20µs ≈ 0.5s;无崩溃 |

---

## 6. 已知未做

- 10 分钟 soak 测试:留给 M5 阶段(§4 备注)。当前基线 0.5s 内 5
  场景无崩溃,**不**是 10 分钟内存泄漏证据。
- 多 worker 语义测试:见 R-SENTINEL-M3.6(独立任务,见 PLANNING)。
- RuleSource 契约测试:见 R-SENTINEL-M3.1(独立任务,见 PLANNING)。
- ASGI / HTTPX / Dashboard 路径的 perf:这些 wheel 各自有 perf 测试
  (不在 M1.6 范围)。

---

## 7. 重新采集步骤

```bash
cd components/sentinel/sentinel
source .venv/bin/activate

# 1. 跑 core + rule 测试,确认全绿
python -m pytest tests/ -v

# 2. 跑 perf baseline(默认 skip,需要 RUN_SEN_PERF=1 开启)
RUN_SEN_PERF=1 python -m pytest tests/benchmark/test_sen_perf.py -v -s 2>&1 | tee /tmp/sen_perf_$(date +%Y%m%d).log
```

Perf 数据每跑一次都会因 GC / 调度抖动;§3 的数字是单次采样,只是
存档起点。后续每周一次采样,看漂移。
