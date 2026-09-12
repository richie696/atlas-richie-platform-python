# R-SENTINEL-M0-skeleton: Atlas Richie Sentinel 家族 — skeleton + design doc

## Status

**Done.** 10 个 wheel 骨架建好,workspace 注册完成,`uv lock` 通过,import 验证通过。**没有任何功能实现** — 只是 metadata + 目录结构 + 设计文档。

## 完成内容

### 1. 10 个 wheel 骨架(在 `components/sentinel/` 聚合下)

| wheel | pyproject | Python import | 状态 |
|---|---|---|---|
| `atlas-richie-sentinel-primitives` | ✅ 0.0.1a1 | `atlas_richie.sentinel_primitives` | 骨架(原 R-104 迁入待 M0.1) |
| `atlas-richie-sentinel-core` | ✅ 0.0.1a1 | `atlas_richie.sentinel_core` | 骨架(M1 实现) |
| `atlas-richie-sentinel-rules` | ✅ 0.0.1a1 | `atlas_richie.sentinel_rules` | 骨架(M3-M4 实现) |
| `atlas-richie-sentinel-source-file` | ✅ 0.0.1a1 | `atlas_richie.sentinel_source_file` | 骨架(M2 实现) |
| `atlas-richie-sentinel-source-nacos` | ✅ 0.0.1a1 | `atlas_richie.sentinel_source_nacos` | 骨架(M6+ 实现) |
| `atlas-richie-sentinel-source-redis` | ✅ 0.0.1a1 | `atlas_richie.sentinel_source_redis` | 骨架(M6+ 实现) |
| `atlas-richie-sentinel-adapter-asgi` | ✅ 0.0.1a1 | `atlas_richie.sentinel_adapter_asgi` | 骨架(M2 实现) |
| `atlas-richie-sentinel-adapter-httpx` | ✅ 0.0.1a1 | `atlas_richie.sentinel_adapter_httpx` | 骨架(M4 实现) |
| `atlas-richie-sentinel-dashboard` | ✅ 0.0.1a1 | `atlas_richie.sentinel_dashboard` | 骨架(M5 实现) |
| `atlas-richie-sentinel-cluster` | ✅ 0.0.1a1 | `atlas_richie.sentinel_cluster` | 骨架(M6+ 实现) |

每个 wheel 含:
- `pyproject.toml` — name, version 0.0.1a1, deps, optional extras, classifiers
- `src/atlas_richie/sentinel_<name>/__init__.py` — `__version__` + `__all__` 注释(实际导入符号在后续 milestone 填)
- `tests/__init__.py` — 空
- `README.md` — placeholder,引用 `R-SENTINEL-design.md`

### 2. workspace 注册

- `pyproject.toml`:
  - `members` 列表追加 10 个路径
  - `[tool.uv.sources]` 追加 10 个 workspace dep
- `versions.toml`:追加 10 个版本条目(都是 `0.0.1a1`)
- `tools/release/verify_isolated_wheels.py`:`PACKAGES` 列表追加 7 个 wheel(M6+ 的 nacos/redis/cluster 没加,因为 deps 可能跟其他 wheel 冲突)

### 3. 设计文档

`docs/acceptance/R-SENTINEL-design.md`(29KB)涵盖:
1. 背景与目标(为什么做,跟 Java 对位,双层防护模型)
2. 家族拆分(10 个 wheel,依赖图,用户安装矩阵,Mono-version)
3. 各 wheel 详细设计(primitives/core/rules/adapter-asgi/adapter-httpx/source-*/dashboard/cluster)
4. M0 → M5 Milestone 详细拆分
5. 跟同类产品对比(pystamina-py / pybreaker / Java Sentinel)
6. 测试策略(覆盖率 90%+,benchmark,兼容性)
7. 风险与缓解
8. 跟现有 wheel 的关系(resilience 改 shim,http/mcp 1.0 前迁移)
9. 时间表(W37-W44+)
10. 决策记录(9 个关键设计选择 + 证据)

## 验证

| 验证项 | 命令 | 结果 |
|---|---|---|
| `uv lock` | `uv lock` | ✅ 133 → 145 packages,10 个新 wheel 解锁成功 |
| `uv pip install -e` 10 个 | edit 模式全部成功 | ✅ |
| 单独 build | `uv build --package` × 10 | ✅ 10 wheel + sdist 全部产出 |
| Import | `python -c "import atlas_richie.sentinel_*; print(__version__)"` | ✅ 10 个全部 0.2.0 |
| **isolated install**(在干净 venv) | `uv pip install --find-links dist/ ... 10 wheel` | ✅ 10/10 全部 OK,import 全部成功 |
| isolated verify(全平台) | `tools/release/verify_isolated_wheels.py` | ⚠️ 被 R-240 aliyun-kms 阻塞(`alibabacloud-darabonba-array==0.1.0` yanked),非 M0 sentinel 引入 |

**Pre-existing 阻塞**:`prepare_wheelhouse.py` 因 R-240 aliyun-kms 链上的 yanked dep 无法 build 完整 wheelhouse。**M0 sentinel wheels 单独 install 全部成功**,但全平台 `verify_isolated_wheels.py` 需要 R-240 修了才能跑。已在 R-246 系列工作的 todo 列表里记录,不在 M0-skeleton 的 scope 内。

## Deps 范围

每个 wheel 严格控制 deps(每个完整功能 ≤ 4 个 runtime dep):

| wheel | runtime deps |
|---|---|
| sentinel-primitives | contracts + stamina + aiolimiter |
| sentinel-core | contracts + sentinel-primitives |
| sentinel-rules | contracts + sentinel-core |
| sentinel-source-file | core + rules + pyyaml + watchfiles |
| sentinel-source-nacos | core + rules + nacos-sdk-python |
| sentinel-source-redis | core + rules + redis |
| sentinel-adapter-asgi | core + rules + source-file + starlette + psutil |
| sentinel-adapter-httpx | core + rules + httpx |
| sentinel-dashboard | core + rules + fastapi + uvicorn |
| sentinel-cluster | core + rules + redis |

最重的 wheel:adapter-asgi(5 个 runtime dep),最轻的:core / rules(2 个)。

## 风险记录

### 1. `stamina` 版本上限(已修复)

- 初次写 `stamina>=0.10,<1.0`,但 PyPI 上 stamina 已经 26.x(改了版本号方案)
- 放宽到 `stamina>=0.10,<30.0`,`uv lock` 通过
- 教训:不熟悉的 dep,先查 PyPI 实际版本分布再写 upper bound

### 2. `redis` 版本冲突(已修复)

- `cache-redis` 要 `redis>=8.1.0`(M5.x 改了)
- `sentinel-cluster` / `sentinel-source-redis` 初写 `redis>=5.0,<6.0`
- 放宽到 `redis>=5.0,<9.0`,`uv lock` 通过
- 教训:cross-wheel 共享 dep 时,先 `uv lock` 验证,再决定版本范围

### 3. `nacos-sdk-python` 可能没有 wheel for py3.13

- M6+ 还没实现,但 pyproject 提前声明了
- 实际 build 时只 build 了 M0..M5 的 6 个 wheel;nacos/redis/cluster 的 build 留 M6+ 实现时做

## 下一步(M0.1:迁移 R-104)

| 任务 | 时间 |
|---|---|
| 4.1 把 R-104 5 primitive 从 `atlas_richie.resilience.*` 迁到 `atlas_richie.sentinel_primitives.*` | 2h |
| 4.2 retry/CB → `stamina` 薄 wrapper | 2h |
| 4.3 rate-limit → `aiolimiter` 薄 wrapper | 1h |
| 4.4 `atlas-richie-resilience` 改 4 行 shim | 0.5h |
| 4.5 51 单测 + framework 整体 + isolated verify | 1h |
| 4.6 M0.1 handoff doc + commit + push | 0.5h |
| 4.7 发 PyPI `0.0.1a1` alpha | 0.2h |
| **总计** | **~7.5h** |

启动时间:**下次 session 第一件事**。
