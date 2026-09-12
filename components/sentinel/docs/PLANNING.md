# R-SENTINEL Implementation Plan — M0..M6+ 详细分解

> **Status**: Working planning doc — 严格对位 `DESIGN.md` §21 顺序。
> **Purpose**: 把 §21 的 checkbox 展开到 actionable 粒度(Deliverable / Exit Criteria / Test ID / ADR / Deps),不引入新子项,不改顺序。
> **Update rule**: §21 改了,本文件跟着同步;两者必须保持一致。

## Checkbox 约定

- **`[x]`** 已完成 — 实现 / 测试 / commit / evidence 都齐
- **`[ ]`** 未开始 — 等上一个子项的 Deps 满足才能开始
- **顶部 `M_x Exit`** 是聚合退出条件(不是单个任务),由其下所有子项完成来满足

完成一个子项时:
1. 跑通 Exit Criteria 验证命令
2. 收集测试 ID / commit hash / evidence
3. 改 `[ ]` → `[x]`
4. 在文件底部"决策记录"区追加 evidence + 任何偏差

## 标记约定

- ✅ = 已完成(`[x]`)
- 🟦 = 进行中
- ⬜ = 未开始(`[ ]`)
- 每个子项展开成 5 段:`Deliverable` / `Exit Criteria` / `Test ID` / `ADR` / `Deps`
- **Test ID** 对位 `DESIGN.md` §19 测试矩阵
- **ADR** 对位 `DESIGN.md` §25 决策记录
- **Deps** 写明此子项依赖的前面子项或外部条件

---

## M0：包结构与 Resilience 合并

### M0.1 [x] 确认统一 Sentinel 产品边界
- **Deliverable**: 决策记录
- **Exit Criteria**: DESIGN.md §1 明确写 "Atlas Richie Sentinel" 产品定位
- **Test ID**: —
- **ADR**: ADR-SEN-001 前提
- **Deps**: 无

### M0.2 [x] 确认核心不引入 stamina/aiolimiter
- **Deliverable**: DESIGN.md ADR-SEN-003
- **Exit Criteria**: 主 wheel `pyproject.toml` `dependencies` 仅允许 `atlas-richie-contracts` 移除;`stamina` / `aiolimiter` 字段不存在
- **Test ID**: —
- **ADR**: ADR-SEN-003
- **Deps**: M0.1

### M0.3 [x] 确认采用 Facade、责任链、State、Strategy、Adapter、Observer
- **Deliverable**: DESIGN.md §4 章节
- **Exit Criteria**: 6 个 pattern 在 §4 各自有独立小节,且有"明确不采用"清单
- **Test ID**: SEN-CORE-001(Slot 逆序释放)
- **ADR**: ADR-SEN-004 ~ ADR-SEN-006
- **Deps**: M0.1

### M0.4 [x] 创建 atlas-richie-sentinel 主 wheel
- **Deliverable**:
  - `components/sentinel/sentinel/pyproject.toml` — name=`atlas-richie-sentinel`, `[project] version = "0.2.0"`, deps=空数组
    - **唯一版本源 = `pyproject.toml` 的 `[project] version`**;`__init__.py` 不再硬编码。
  - `components/sentinel/sentinel/src/atlas_richie/sentinel/__init__.py` — 公开 Facade,版本走 PEP 562 `__getattr__` 懒加载:
    ```python
    from importlib.metadata import version as _pkg_version, PackageNotFoundError

    def __getattr__(name: str) -> str:
        if name == "__version__":
            try:
                return _pkg_version("atlas-richie-sentinel")
            except PackageNotFoundError:
                return "0.0.0+local"  # editable / 未 install 兜底
        raise AttributeError(f"module 'atlas_richie.sentinel' has no attribute {name!r}")

    __all__ = ["__version__"]  # 配合 __getattr__ 用
    ```
    - 编辑器/类型检查器友好:`__version__: str` 走 `__getattr__`,不会触发静态分析报错。
  - `components/sentinel/sentinel/README.md` — 4 段:What / Why / Compare / Quick Start
- **Exit Criteria**:
  - `uv build --package atlas-richie-sentinel` 成功
  - 在干净 venv `pip install` 后,`python -c "from importlib.metadata import version; assert version('atlas-richie-sentinel') == '0.2.0'"` 不报错(包内 `__version__` 与 distribution metadata 一致)
  - `python -c "import atlas_richie.sentinel; assert atlas_richie.sentinel.__version__ == '0.2.0'"` 不报错
  - `grep -E '^__version__\s*=\s*["'\'']' components/sentinel/sentinel/src/atlas_richie/sentinel/__init__.py` 返回 0 行(确认无硬编码)
  - `__init__.py` 不 import 任何第三方包(grep 验证)
  - **版本一致门禁**(M0.11 验证命令里体现;**不要**依赖 `uv publish` 自身做拒绝——`uv publish` 不校验包内 version):
    - 新增 `tools/release/check_version_consistency.py`(放在主仓 `tools/release/`,与 `verify_isolated_wheels.py` 同级):
      - **接口**:`check_version_consistency.py <release_dir>`(强制要求一个干净的专用输出目录;`release_dir` 不存在/为空 → 退出码 1)
      - 校验流程:
        1. 扫 `<release_dir>`,**严格要求**:`*.whl` 恰好 1 个 + `*.tar.gz` 恰好 1 个,其他多/少/类型错都失败
        2. 解析文件名,**wheel 和 sdist 都要求匹配 `atlas_richie_sentinel-*`**(PEP 625 规范化:连字符转下划线,跟仓库现有 `atlas_richie_sentinel_primitives-0.2.0.tar.gz` 等一致);包名不匹配 → 失败,防误发其它组件的产物
        3. 读 `components/sentinel/sentinel/pyproject.toml` 的 `[project] version` + `name` → `pyproject_version` / `pyproject_name`
        4. wheel:解 `*.dist-info/METADATA`,抓 `Version:` 字段 + `Name:` 字段 → `wheel_version` / `wheel_name`
        5. sdist:解 `*.tar.gz` 里的 `PKG-INFO`,抓 `Version:` 字段 + `Name:` 字段 → `sdist_version` / `sdist_name`
        6. 校验:`wheel_name == sdist_name == pyproject_name == "atlas-richie-sentinel"`,`wheel_version == sdist_version == pyproject_version`;任一不等 → 退出码 1 + 冲突报告
        7. 显式:不调用 `uv publish`;仅返回 0/1 + 冲突报告
    - 发布流程(写在 `components/sentinel/docs/RELEASE.md`,M0.11 同步创建):
      ```bash
      # 1. 专用干净目录,避免和根 dist/ 旧产物混合
      rm -rf /tmp/atlas-richie-sentinel-release
      # 2. --clear 重建 + --no-create-gitignore 禁止 uv 在输出目录写 .gitignore
      #    (默认 uv 会在 --out-dir 落 .gitignore,导致严格校验脚本 "恰好 1 wheel + 1 sdist" 假失败)
      uv build --package atlas-richie-sentinel \
               --out-dir /tmp/atlas-richie-sentinel-release \
               --clear \
               --no-create-gitignore
      # 3. 强制要求目录内恰好 1 wheel + 1 sdist + 文件名匹配 atlas_richie_sentinel-* + 三元组 name/version 一致
      python tools/release/check_version_consistency.py /tmp/atlas-richie-sentinel-release
      # 4. uv publish 接受文件路径列表(本机 uv publish --help 没有 --package);用 glob 避免再次硬编码规范化和版本号
      uv publish /tmp/atlas-richie-sentinel-release/*.whl \
                 /tmp/atlas-richie-sentinel-release/*.tar.gz
      ```
    - **PEP 625 规范化**:本仓所有现有 sdist 用下划线,例如 `atlas_richie_sentinel_primitives-0.2.0.tar.gz`、`atlas_richie_contracts-0.2.0.tar.gz`;新主包 sdist 必为 `atlas_richie_sentinel-0.2.0.tar.gz`(不是 `atlas-richie-sentinel-0.2.0.tar.gz`)。`Name:` / `Version:` 字段在 `METADATA` / `PKG-INFO` 内部保留原始 `atlas-richie-sentinel` / `0.2.0` 字符串,只有**文件名**按 PEP 625 规范化为下划线。
    - **为什么必须专用目录**:仓库根 `dist/` 已有 cache / secret / 其它组件的旧版本产物,直接扫描 `dist/` 或 `uv publish`(不带路径)会误发布;`--clear` 进一步保证 `--out-dir` 内只有本次构建的产物
    - CI 门禁:`check_version_consistency.py` 接进 M0.11 的 `tools/release/release_gate.sh`,作为发布前必经步骤
    - 三产物版本字段位置(wheel 与 sdist 路径不同,容易漏):
      - wheel 文件名: `atlas_richie_sentinel-0.2.0-py3-none-any.whl`(PEP 427/491 规范名)
      - wheel 内: `atlas_richie_sentinel-0.2.0.dist-info/METADATA` 里的 `Version: 0.2.0` + `Name: atlas-richie-sentinel`
      - sdist 文件名: `atlas_richie_sentinel-0.2.0.tar.gz`(PEP 625 规范名,下划线)
      - sdist 内: `atlas_richie_sentinel-0.2.0/PKG-INFO` 里的 `Version: 0.2.0` + `Name: atlas-richie-sentinel`
      - pyproject: `[project] name = "atlas-richie-sentinel"` + `version = "0.2.0"`
- **Test ID**: —
- **ADR**: ADR-SEN-002
- **Deps**: M0.1, M0.2, M0.3

### M0.5 [x] 使用 git mv 迁入 Resilience 源码和测试(保持现有公开 API,按目标结构重命名/拆分)
- **Deliverable**(实际文件名按 `ls components/resilience/src/atlas_richie/resilience/` 现状):
  - `git mv` + 原地重命名/拆分:
    - `retry.py` → `primitives/retry.py`(名称不变,**公开类名 `RetryPolicy` / `RetryExecutor` 保持** — M0 不重命名)
    - `circuit_breaker.py` → `primitives/circuit_breaker.py`(名称不变)
    - `bulkhead.py` → `primitives/bulkhead.py`(名称不变)
    - `idempotency.py` → `primitives/idempotency.py`(名称不变,**保留 `StatelessIdempotencyKey` / `NeverIdempotencyKey` / `CallableIdempotencyKey`**)
    - `errors.py` → `errors/__init__.py`(**目标位置是 `atlas_richie/sentinel/errors/`** 而不是 `primitives/`,见 M0.5-A "唯一异常层")
    - `rate_limit.py` → `primitives/token_bucket.py`(**重命名**,因为它内部 class 是 `TokenBucket`,跟 DESIGN.md §8.3 一致)
    - `clock.py` → 拆成:
      - `primitives/clock.py` — 只保留 `Clock` / `SystemClock` / `ManualClock` / `system_sleep`
      - `primitives/random_source.py` — `RandomSource` / `SystemRandom` / `DeterministicRandom`(新拆出)
  - 命名空间 `atlas_richie.resilience` → `atlas_richie.sentinel.primitives`(7 个 primitive 文件)
  - `errors.py` 命名空间 `atlas_richie.resilience.errors` → `atlas_richie.sentinel.errors`(独立子包)
  - `git mv components/resilience/tests/test_*.py` → `components/sentinel/sentinel/tests/`
  - 测试文件内 `from atlas_richie.resilience import ...` → `from atlas_richie.sentinel.primitives import ...` 或 `from atlas_richie.sentinel.errors import ...`
  - **M0 不改任何公开类名**(保留 `RetryPolicy` / `RetryExecutor` / `IdempotencyKey` / `StatelessIdempotencyKey` / `NeverIdempotencyKey` / `ResilienceError` / `CircuitOpen` / `BulkheadFull` / `RetryExhausted` / `RetryNotPermitted` / `RateLimitExceeded`)
- **Exit Criteria**(**只**检查源码迁移,目录删除归 M0.9):
  - `grep -r "atlas_richie.resilience" components/sentinel/sentinel/` 返回 0 行
  - `grep -r "atlas_richie.resilience" components/resilience/src/ components/resilience/tests/` 返回空(旧源码/测试已迁走)
  - `ls components/sentinel/sentinel/src/atlas_richie/sentinel/primitives/` 含 7 个 .py 文件(`token_bucket.py` 内 class 名 `TokenBucket` 与文件名一致)
  - `ls components/sentinel/sentinel/src/atlas_richie/sentinel/errors/` 含 `__init__.py` 一个文件
  - `ls components/resilience/` **仍存在**(README / pyproject.toml 没动,完整删除在 M0.9)
- **Test ID**: SEN-CORE-001(全逆向释放),SEN-CB-001(熔断状态机)
- **ADR**: ADR-SEN-001
- **Deps**: M0.4

### M0.5-A [x] 唯一异常层:`atlas_richie.sentinel.errors`(原语从其导入,零 3rd-party 兼容)
- **背景**: 现有 `errors.py` 继承 `atlas_richie.contracts.PlatformError`,这会让主包**反向依赖 contracts**,违反 §2.4 "Sentinel 不依赖 platform contracts"。此外,M0.5 必须建立**唯一异常树**,让所有 `except` 能跨原语和 engine 边界捕获。
- **决策**:**唯一异常层 = `atlas_richie.sentinel.errors`**,**所有原语模块从中导入**,**根异常 `SentinelError` 继承 stdlib `Exception`**(零依赖)
- **Deliverable**:
  - M0.5 把 `errors.py` 直接 `git mv` 到 `src/atlas_richie/sentinel/errors/__init__.py`(不是 `primitives/errors.py`)
  - **删除** `from atlas_richie.contracts.errors import PlatformError`,改为 `class SentinelError(Exception): ...` 内部定义
  - `class ResilienceError(SentinelError): ...`(原基类从继承 `PlatformError` 改为继承 `SentinelError`)
  - 5 个具体异常(`RetryExhausted` / `RetryNotPermitted` / `CircuitOpen` / `RateLimitExceeded` / `BulkheadFull`)继承 `ResilienceError`
  - `primitives/circuit_breaker.py` 等从 `from atlas_richie.sentinel.errors import CircuitOpen` 导入
- **唯一异常树**(单继承,不复用原语异常类):
  ```
  SentinelError(Exception)            ← 根,stdlib Exception(零 3rd-party)
  ├── ResilienceError(SentinelError)
  │   ├── RetryExhausted               ← 原语直接调用时使用
  │   ├── RetryNotPermitted
  │   ├── CircuitOpen                  ← 原语直接调用时使用(熔断器直接 throw)
  │   ├── RateLimitExceeded
  │   └── BulkheadFull                 ← 原语直接调用时使用(信号量直接 throw)
  ├── SentinelBlockedError(SentinelError)            ← M1.1 加,Engine 拒绝契约
  │   ├── FlowBlocked                  ← FlowSlot 拒绝
  │   ├── ParamFlowBlocked             ← ParamFlowSlot 拒绝
  │   ├── SystemBlocked                ← SystemSlot 拒绝
  │   ├── AuthorityDenied              ← AuthoritySlot 拒绝
  │   └── CircuitBlocked               ← DegradeSlot 拒绝(熔断开)
  ├── SentinelConfigurationError(SentinelError)      ← M1.1 加
  ├── SentinelLifecycleError(SentinelError)          ← M1.1 加
  └── RuleSnapshotError(SentinelLifecycleError)      ← M1.1 加
  ```
  - **不复用原则**:`CircuitOpen` / `BulkheadFull` 只属于 `ResilienceError` 分支;`CircuitBlocked` / `FlowBlocked` 等是**独立**类型,不能多重继承自 `CircuitOpen`。
  - **Engine 拒绝契约**:DegradeSlot 拒绝时**不是** `raise CircuitOpen()`,而是:
    ```python
    raise CircuitBlocked(
        resource=resource,
        retry_after=circuit.retry_after,
        state=circuit.state,
    ) from underlying_circuit_open
    ```
    - 复制可观察字段(`retry_after` / `state` / `rule`),但**不**伪装成原语异常。
  - 用户代码两种捕获方式:
    - `except CircuitOpen` / `except BulkheadFull` — 捕获直接调原语(`async with circuit_breaker:`)的拒绝。
    - `except SentinelBlockedError` / `except CircuitBlocked` — 捕获 Engine / Slot 的拒绝。
  - M1.1 退出条件:`SentinelBlockedError` 与 `ResilienceError` **互不为子类**;`isinstance(CircuitBlocked(), CircuitOpen) == False`。
- **Exit Criteria**:
  - `ls components/sentinel/sentinel/src/atlas_richie/sentinel/errors/__init__.py` 存在
  - `grep "from atlas_richie.contracts" components/sentinel/sentinel/src/atlas_richie/sentinel/errors/__init__.py` 返回 0 行(无 contracts 反向依赖)
  - `grep "from atlas_richie.sentinel.errors" components/sentinel/sentinel/src/atlas_richie/sentinel/primitives/` 返回 ≥ 5 行
  - `grep -E "^class (CircuitOpen|BulkheadFull|RetryExhausted|RetryNotPermitted|RateLimitExceeded|ResilienceError)" components/sentinel/sentinel/src/atlas_richie/sentinel/` 0 重复定义
  - 5 个具体异常 + `ResilienceError` 都在 `atlas_richie.sentinel.errors` 模块下,`isinstance(x, SentinelError)` 对原语异常为真
  - M1.1 实现 `sentinel/errors/{base,block,configuration,lifecycle}.py` 时**继承** M0.5-A 提供的 `SentinelError`,**不**新建同名根
- **Test ID**: —
- **ADR**: ADR-SEN-001, ADR-SEN-003(Sentinel 不依赖 platform)
- **Deps**: M0.5

### M0.6 [x] 删除 sentinel-primitives/core/rules 三个基础 wheel 骨架
- **Deliverable**:
  - `git rm -r components/sentinel/sentinel-primitives/`
  - `git rm -r components/sentinel/sentinel-core/`
  - `git rm -r components/sentinel/sentinel-rules/`
- **Exit Criteria**:
  - `ls components/sentinel/` 不再有 sentinel-primitives / sentinel-core / sentinel-rules
  - `grep -E 'sentinel-(primitives|core|rules)' pyproject.toml versions.toml` 返回空
- **Test ID**: —
- **ADR**: ADR-SEN-002
- **Deps**: M0.4(主 wheel 先建好)

### M0.7 [x] 去除主包对 atlas-richie-contracts 的依赖
- **Deliverable**:
  - 主 wheel `pyproject.toml` `dependencies` = 空数组
  - 内部异常、生命周期、事件、Protocol 全部在 `atlas_richie.sentinel.errors` / `.ports` 内部定义
- **Exit Criteria**:
  - `cat components/sentinel/sentinel/pyproject.toml | grep contracts` 返回空
  - 干净 venv 中 `pip show atlas-richie-sentinel` 显示 `Requires:` 为空
- **Test ID**: —
- **ADR**: ADR-SEN-003
- **Deps**: M0.5

### M0.7.1 [x] 唯一 `primitives/__init__.py` 集中 re-export 公开原语
- **背景**: M0 不改任何公开类名(`RetryPolicy` / `RetryExecutor` / `IdempotencyKey` / `StatelessIdempotencyKey` / `NeverIdempotencyKey` / `CallableIdempotencyKey` / `CircuitBreaker` / `TokenBucket` / `Bulkhead` / `Clock` / `SystemClock` / `ManualClock` / `RandomSource` / `SystemRandom` / `DeterministicRandom` / `system_sleep`),但需要 1 个入口让用户用 `from atlas_richie.sentinel.primitives import ...` 一次拿全。
- **Deliverable**:
  - `primitives/__init__.py` 内容:re-export 每个原语模块的**公开类型**
  - `__all__` 列完整清单
  - **不**引入任何额外类名(如不存在的 `Retry`,沿用 `RetryPolicy` + `RetryExecutor`)
- **Exit Criteria**:
  - `cat components/sentinel/sentinel/src/atlas_richie/sentinel/primitives/__init__.py` 含完整 re-export
  - `python -c "from atlas_richie.sentinel.primitives import RetryPolicy, RetryExecutor, CircuitBreaker, TokenBucket, Bulkhead, IdempotencyKey, Clock, SystemClock, ManualClock, RandomSource, StatelessIdempotencyKey, NeverIdempotencyKey, CallableIdempotencyKey"` 成功
  - `python -c "from atlas_richie.sentinel.primitives import Retry"` 抛 `ImportError`(确认 `Retry` 不存在,避免外部代码误用)
- **Test ID**: —
- **ADR**: ADR-SEN-001
- **Deps**: M0.5, M0.5-A

### M0.8 [x] 更新真实消费者依赖(全仓 grep 已验证)
- **背景**: 2026-09-13 `grep -rE "atlas_richie\.resilience|atlas-richie-resilience" components/ foundation/ --include="pyproject.toml" --include="*.py" | grep -v __pycache__` 的**实际命中**(排除 sentinel 自指):
  - `foundation/platform/pyproject.toml` 列出 `atlas-richie-resilience>=0.2.0,<0.3.0` 作为 platform 聚合依赖
  - `components/http/src/` 和 `components/mcp/src/` **不**直接 import resilience
  - `components/http/pyproject.toml` 和 `components/mcp/pyproject.toml` **不**列 resilience dep
- **Deliverable**:
  - `foundation/platform/pyproject.toml`: 删除 `atlas-richie-resilience>=0.2.0,<0.3.0` 行,加 `atlas-richie-sentinel>=0.2.0,<0.3.0`(M0.11 时调整版本)
  - 全仓 `from atlas_richie.resilience import ...` / `import atlas_richie.resilience` 必须为 0(目前确实为 0,但要保持)
- **Exit Criteria**:
  - `grep -rE "atlas_richie\.resilience" components/ foundation/ --include="*.py" --include="pyproject.toml" | grep -v sentinel/docs/ | grep -v __pycache__` 返回 0 行
  - `grep -E "atlas-richie-resilience" components/ foundation/ --include="pyproject.toml"` 返回 0 行
- **Test ID**: —
- **ADR**: ADR-SEN-001
- **Deps**: M0.7

### M0.8.1 [x] wheel 命名空间所有权 + 文件重叠校验(构建时检查)
- **Deliverable**:
  - 工具脚本:`tools/release/check_sentinel_namespace.py`
  - 校验:对每个 sentinel 扩展 wheel 跑 `python -c "import importlib.metadata; ...; print([f for f in m.files if 'atlas_richie/sentinel' in str(f)])"`,断言没有任何扩展 wheel 写 `atlas_richie/sentinel/__init__.py` 或 `atlas_richie/sentinel/engine/...`
  - 主 wheel 独占 `atlas_richie/sentinel/` 命名空间
  - 任何两个 wheel 的 `wheel` 文件清单有同名文件时 → 构建失败
- **Exit Criteria**:
  - `uv run --no-sync python tools/release/check_sentinel_namespace.py` 退出码 0
  - 故意制造一个冲突(临时在扩展 wheel 加一个文件)→ 工具检测到 → 退出码 1
- **Test ID**: —
- **ADR**: ADR-SEN-002(主 wheel 独占),DESIGN.md §3.1 命名空间所有权
- **Deps**: M0.5, M0.6

### M0.9 [x] 删除 components/resilience 及发布配置
- **Deliverable**:
  - `git rm -r components/resilience/`
  - 移除 workspace `pyproject.toml` 中 `components/resilience` member
  - 移除 `[tool.uv.sources]` 中 `atlas-richie-resilience` 引用
  - 移除 `versions.toml` 中 `atlas-richie-resilience` 条目
  - 移除 `tools/release/verify_isolated_wheels.py` 中 `(f"atlas-richie-resilience==...")` 行
  - 同步更新 `uv.lock`(`uv lock` 触发)
  - 同步更新根目录 `HANDOFF.md`:**历史验收事实保留**(Phase B.4 引入 resilience / Phase E E2E 等已 DONE 的记录),但 "当前架构" 章节中 resilience 描述改为"Sentinel 主包已收编"并指向 `components/sentinel/docs/DESIGN.md`;新增 `R-SENTINEL-M0-handoff.md` 占位段落
  - 同步更新 `components/resilience/README.md`(如果目录还在,虽然 `git rm` 会删整个目录,本条以防删失败)开头加 "DEPRECATED → see components/sentinel/"
- **Exit Criteria**:
  - `ls components/resilience/` 不存在
  - 下列**配置/发布/设计文档**中 `atlas-richie-resilience` 出现次数 = 0:
    - `pyproject.toml`(workspace member + sources)
    - `versions.toml`
    - `tools/release/verify_isolated_wheels.py`
    - `components/sentinel/docs/DESIGN.md`
    - `components/sentinel/docs/PLANNING.md`
  - 根目录 `HANDOFF.md` 验收用**确定性 sentinel 标记**(M0.9 实施时在 `## 2. 总体架构决策` 段的开头/结尾插入明确注释,避免"假绿"):
    - M0.9 实施时在 `HANDOFF.md` 写入:
      ```markdown
      ## 2. 总体架构决策
      <!-- SENTINEL_HANDOFF_CURRENT_ARCH_START -->

      ...(原"总体架构决策"内容,但 `atlas-richie-resilience` 描述替换为"Sentinel 主包已收编, 详见 components/sentinel/docs/DESIGN.md")...

      <!-- SENTINEL_HANDOFF_CURRENT_ARCH_END -->
      ```
    - 验收命令(基于明确注释区间,不依赖章节标题文案):
      ```bash
      awk '
        /<!-- SENTINEL_HANDOFF_CURRENT_ARCH_START -->/{in=1; next}
        /<!-- SENTINEL_HANDOFF_CURRENT_ARCH_END -->/{in=0; next}
        in && /atlas-richie-resilience/{print FILENAME":"NR":"$0; found=1}
        END{exit found?1:0}
      ' HANDOFF.md
      ```
      返回码 0 + 输出 0 行 = 当前架构段已无 `atlas-richie-resilience` 字样。
    - 显式确认历史验收章节(Phase B.4 / Phase E E2E 等)仍可读、可检索 `atlas-richie-resilience` 字符串(事实记录保留):
      ```bash
      awk '/^## 15\. R-220/{found=1} found && /atlas-richie-resilience/{c++} END{exit c>=1?0:1}' HANDOFF.md
      ```
      返回码 0 = 历史事实保留成功。
    - 检查完后追加 commit message 一句:"HANDOFF.md 历史事实保留,当前架构段已切换到 Sentinel(sentinel 标记区间无 resilience 引用)"
  - `uv lock` 成功
  - 全仓 release/verify 脚本不引用 `atlas-richie-resilience`
  - `HANDOFF.md` 仍包含历史 Phase B-E 验收事实(事实保留),但"当前架构"段落已更新
- **Test ID**: —
- **ADR**: ADR-SEN-001
- **Deps**: M0.8(consumer 已迁走),M0.8.1(命名空间检查工具就位)

### M0.9.1 [x] DESIGN.md §19 测试矩阵补 SEN-SYSTEM-001 + SEN-AUTH-001
- **背景**: 现有 §19 矩阵只有 SEN-CORE-001/002 / SEN-CB-001 / SEN-FLOW-001 / SEN-PARAM-001 / SEN-RULE-001 / SEN-ASGI-001 / SEN-HTTPX-001 / SEN-MP-001 / SEN-DASH-001 / SEN-CLUSTER-001 / SEN-PERF-001。SystemRule 和 AuthorityRule 没有专属 Test ID。
- **Deliverable**:
  - DESIGN.md §19.1 表格新增:
    - `SEN-SYSTEM-001` 系统级保护(2 策略 + CPU/load/event-loop-lag/in-flight + 暂时失败降级)→ 至少 1 行 entry,最低证据 = 「确定性时钟 + 2 策略 + sampler 失败降级测试」
    - `SEN-AUTH-001` 黑白名单 + 可信 origin resolver(默认不可信)→ 至少 1 行 entry,最低证据 = 「origin 不可信测试 + ALLOW/DENY 互斥测试 + 配置错误拒绝」
  - 引用这两个 ID 到 M2.4 / M2.5 子项
- **Exit Criteria**:
  - `grep "SEN-SYSTEM-001\|SEN-AUTH-001" components/sentinel/docs/DESIGN.md` 返回 ≥ 2 行(定义 + 引用)
- **Test ID**: SEN-SYSTEM-001, SEN-AUTH-001(新定义)
- **ADR**: —
- **Deps**: M0.6(主 wheel 骨架就位)

### M0.10 [x] 现有 67 个 Resilience 测试迁移后全部通过(按现状 7 文件 + 1 helpers)
- **Deliverable**(测试文件**按现状 7 个 + 1 helpers**,不预先拆分):
  - `git mv components/resilience/tests/test_retry.py` → `components/sentinel/sentinel/tests/test_retry.py`
  - `git mv components/resilience/tests/test_rate_limit.py` → `.../test_rate_limit.py`(**测试文件名不变**,只 import 改;`rate_limit.py` 源码改名为 `token_bucket.py` 是源码侧,测试侧保持 `test_rate_limit.py` 与历史一致)
  - `git mv components/resilience/tests/test_circuit_breaker.py` → `...`
  - `git mv components/resilience/tests/test_bulkhead.py` → `...`
  - `git mv components/resilience/tests/test_idempotency.py` → `...`
  - `git mv components/resilience/tests/test_composition.py` → `...`
  - `git mv components/resilience/tests/test_e2e_resilience.py` → `...`
  - `git mv components/resilience/tests/_helpers.py` → `.../tests/_helpers.py`
  - **不**预先拆分出 `test_clock.py` / `test_random_source.py` / `test_errors.py` 等(clock / random_source / errors 是源码侧的拆分,不是测试侧的拆分;M0 阶段保留单一 `test_retry.py` 等)
  - 每个测试 import 改成 `from atlas_richie.sentinel.primitives import ...` 或 `from atlas_richie.sentinel.errors import ...`
  - 测试用例本身不改(只改 import + namespace 字符串)
  - 如果 `from atlas_richie.resilience import errors` 这类集合 import 改成 `from atlas_richie.sentinel import errors` 或 `from atlas_richie.sentinel.errors import ...`
- **Exit Criteria**:
  - `uv run --no-sync pytest components/sentinel/sentinel/tests/ -q` 显示 ≥ 67 passed
  - 无 1 个 skipped / failed / error
  - `ls components/sentinel/sentinel/tests/` 含 7 个 `test_*.py` + 1 个 `_helpers.py`,**不**含 `test_token_bucket.py` / `test_clock.py` / `test_random_source.py` / `test_errors.py`(后三者是计划虚构的,会随 M1.x 真实拆分时再产生)
- **Test ID**: SEN-CORE-001, SEN-CB-001
- **ADR**: —
- **Deps**: M0.9

### M0.11 [x] 主 wheel 独立构建、安装和 public import 验证通过
- **Deliverable**:
  - 干净 venv(无任何 atlas-richie-* 包预装)中:
    - `uv build --package atlas-richie-sentinel` 产出 wheel
    - `uv venv /tmp/sentinel-m0-test`
    - `VIRTUAL_ENV=/tmp/sentinel-m0-test uv pip install /path/to/atlas_richie_sentinel-0.2.0-py3-none-any.whl`
    - `python -c "import atlas_richie.sentinel"` 不报错
    - `python -c "from atlas_richie.sentinel.primitives import RetryPolicy, RetryExecutor, CircuitBreaker, TokenBucket, Bulkhead, IdempotencyKey, Clock; print(RetryPolicy, RetryExecutor, CircuitBreaker, TokenBucket, Bulkhead, IdempotencyKey, Clock)"` 全部成功
    - `python -c "from atlas_richie.sentinel.errors import SentinelError, ResilienceError, CircuitOpen, BulkheadFull, RetryExhausted, RetryNotPermitted, RateLimitExceeded"` 全部成功
    - `pip show atlas-richie-sentinel` 显示 `Requires:` 为空
- **Exit Criteria**:
  - `Requires:` 行为空(确认零依赖,无 contracts 反向依赖)
  - 4 个 import 测试全过(主 facade + 7 个原语 + 7 个异常)
  - `python -c "from atlas_richie.sentinel.primitives import Retry"` 抛 `ImportError`(确认 `Retry` 不存在,守住公开 API 边界)
- **Test ID**: —
- **ADR**: ADR-SEN-002, ADR-SEN-003
- **Deps**: M0.10, M0.7.1

### M0 Exit [x] (M0.1-M0.11 全部完成)
- **Exit Criteria**(由 §21 + 11 个子项汇总):
  - 仓库只有一份原语实现
  - 不再存在 Resilience 产品或兼容 shim
  - `atlas-richie-sentinel` 主 wheel 零 3rd-party 运行时依赖
  - 67 个 primitive 测试全过
  - 内部 consumer (http / mcp) 全部迁完
- **验证命令**:
  - `git grep "atlas_richie.resilience" -- ':!docs'` 返回 0 行
  - `git grep "atlas-richie-resilience" -- ':!docs' ':!*.md'` 返回 0 行
  - `uv lock` 通过
  - 主 wheel build + 干净 venv install + import 测试全过

---

## M1：Engine、生命周期和指标内核

### M1.1 [x] 实现领域模型和异常体系(基于 M0.5-A 已有异常层)
- **背景**(M0.5-A): M0.5 已经把 5 个原语具体异常(`CircuitOpen` / `BulkheadFull` / `RetryExhausted` / `RetryNotPermitted` / `RateLimitExceeded`)+ 基类 `ResilienceError` 移到 `atlas_richie/sentinel/errors/__init__.py`,根异常 `SentinelError(Exception)` 已定义。M1.1 **不再新建同名类**,只补 M0 还没建的部分。
- **Deliverable**:
  - `model/`:
    - `resource.py` — `Resource` / `ResourceKind` / `TrafficType`
    - `context.py` — `SentinelContext`(frozen,无 put)
    - `argument.py` — `InvocationArguments`
    - `outcome.py` — `OutcomeKind` 枚举(ADMITTED/SUCCEEDED/FAILED/CANCELLED/BLOCKED) + `Outcome` dataclass
    - `decision.py` — `SlotLease` Protocol + `NoopSlotLease` 不可变
    - `enums.py` — `BlockReason` / `RuleMatchKind` / `EngineState`
  - `errors/` 拆分(复用 M0.5 已有根 + 5 个具体异常):
    - `__init__.py` — re-export 全部公开异常(根 + ResilienceError + 5 原语 + SentinelBlockedError + 6 子类 + SentinelConfigurationError + SentinelLifecycleError + RuleSnapshotError)
    - `base.py` — **新文件,集中定义** `SentinelError(Exception)`,**从 M0 errors/__init__.py 迁出**;`__init__.py` 仅 re-export(避免两个地方定义根异常)
    - `block.py` — 新增 `SentinelBlockedError(SentinelError)` + 6 子类(`FlowBlocked` / `ParamFlowBlocked` / `SystemBlocked` / `CircuitBlocked` / `AuthorityDenied`);`CircuitBlocked` 暴露 `retry_after` / `state` / `rule` 但**不是** `CircuitOpen` 子类(单继承不复用)
    - `configuration.py` — 新增 `SentinelConfigurationError(SentinelError)`
    - `lifecycle.py` — 新增 `SentinelLifecycleError(SentinelError)` + `RuleSnapshotError(SentinelLifecycleError)`
  - 完整异常树(M0.5-A 锁定,单继承,不复用原语异常):
    ```
    SentinelError(Exception)        ← 根,stdlib
    ├── ResilienceError(SentinelError)   ← 原语 throw
    │   ├── RetryExhausted
    │   ├── RetryNotPermitted
    │   ├── CircuitOpen
    │   ├── RateLimitExceeded
    │   └── BulkheadFull
    ├── SentinelBlockedError(SentinelError)    ← Engine 拒绝契约,独立分支
    │   ├── FlowBlocked
    │   ├── ParamFlowBlocked
    │   ├── SystemBlocked
    │   ├── CircuitBlocked                  ← 暴露 retry_after/state/rule 字段,非 CircuitOpen 子类
    │   └── AuthorityDenied
    ├── SentinelConfigurationError(SentinelError)
    ├── SentinelLifecycleError(SentinelError)
    └── RuleSnapshotError(SentinelLifecycleError)
    ```
- **Exit Criteria**:
  - `from atlas_richie.sentinel.model import Resource, SentinelContext, Outcome, ...` 成功
  - `from atlas_richie.sentinel.errors import SentinelBlockedError, FlowBlocked, ...` 成功
  - 全部 frozen dataclass,`__init__` 拒绝可变默认值
  - `CircuitOpen` 和 `CircuitBlocked` **不是** 同一个类(单继承不复用,符合 M0.5-A);`isinstance(CircuitBlocked(), CircuitOpen) == False`
  - `SentinelBlockedError` 与 `ResilienceError` 互不为子类
  - 异常有 `stable_code` / `BlockReason` / `resource` / `rule_id` / `retry_after` / `message` 字段
  - `grep -E "^class (SentinelError|ResilienceError)" components/sentinel/sentinel/src/atlas_richie/sentinel/errors/` 只有 1 处定义(SentinelError 在 base.py,ResilienceError 在 __init__.py)
- **Test ID**: SEN-CORE-001(part:outcome 5 种区分)
- **ADR**: ADR-SEN-001, ADR-SEN-006
- **Deps**: M0.5-A

### M1.2 [x] 实现 SentinelEngine、EntryLease、Slot/SlotLease、SlotChain
- **Deliverable**:
  - `engine/sentinel_engine.py` — `SentinelEngine`(async context manager,6 状态机)
  - `engine/entry.py` — `EntryRequest` / `EntryLease`
  - `engine/slot.py` — `Slot` Protocol + 7 个内置 Slot 的协议/接口骨架(NodeSelector / Statistic / Authority / System / Flow / ParamFlow / Degrade)
  - `engine/slot_chain.py` — `SlotChain` + Order 常量 100-700
- **Exit Criteria**:
  - `async with engine.entry(Resource("test")):` 通过(5 状态 Outcome 都测试)
  - 7 个 Slot 的 `enter` / `complete` / `release` 协议签名锁定
  - 状态机非法迁移抛 `SentinelLifecycleError`
- **Test ID**: SEN-CORE-001(全部)
- **ADR**: ADR-SEN-004, ADR-SEN-005
- **Deps**: M1.1

### M1.3 [x] 实现原子回滚、取消和关闭语义
- **Deliverable**:
  - `SlotLease` 实际释放逻辑:逆序 + idempotent + 一个 Lease 失败不阻止其他
  - `CancelledError` 处理:`Outcome.CANCELLED` 不计入异常比例,不重试
  - `engine.close(graceful_timeout)`:取消等待中的 Entry,清理后台任务
  - `fail-safe` 三种策略:fail closed(reject)/ fail open(observe)/ fail fast(启动时拒绝)
- **Exit Criteria**:
  - 故障注入测试:每个 Slot 拒绝时,后续 Lease 全部 release,permit 不泄漏
  - `asyncio.CancelledError` 在 3 个点(等待 / 业务 / 流式)分别测试 → Outcome.CANCELLED
  - 重复 release 调用幂等
  - `aclose` 后拒绝新 Entry
- **Test ID**: SEN-CORE-001(完整), SEN-CORE-002(Cancelled)
- **ADR**: ADR-SEN-004, ADR-SEN-005
- **Deps**: M1.2

### M1.4 [x] 实现环形 SlidingWindow、MetricRegistry、ResourceRegistry
- **Deliverable**:
  - `metrics/sliding_window.py` — **stdlib ring buffer**(`array.array('q')` 或 list + 索引),**不引入 sortedcontainers**
  - `metrics/registry.py` — `MetricRegistry`(admitted / blocked / success / failure / cancelled / RT)
  - `metrics/snapshot.py` — `MetricSnapshot` frozen dataclass
  - `metrics/sink.py` — 内部 sink(默认 Noop)
  - `engine/resource_registry.py` — max_resources / idle_ttl / cleanup / overflow policy
- **Exit Criteria**:
  - SlidingWindow 桶索引由 monotonic clock 计算,过期桶原地重置
  - Metric label 只允许 resource / resource_kind / traffic_type / rule_kind / block_reason / outcome(低基数)
  - **禁止** user_id / order_id / token 入 label
  - ResourceRegistry 超过 max_resources 触发 `ResourceCardinalityExceededEvent`
- **Test ID**: SEN-CORE-001(MetricSnapshot), SEN-PARAM-001(part: overflow)
- **ADR**: ADR-SEN-007
- **Deps**: M1.2
- **不做硬性性能断言**:SlidingWindow 的写入延迟、Memory 占用、p99 等**不**在 M1 设绝对阈值。先用 `tests/benchmark/test_sen_perf.py` 收集数据,作为"原始基线"提交。阈值审批延后到 M5 1.0 前 + 真实下游场景验证后再设。DESIGN.md §19.5 已明确:"M1 建立基线,后续里程碑只能在批准阈值内回归。首次基线未完成前,文档不声称具体 QPS。"

### M1.5 [x] 实现 RuleSnapshot、RuleRepository、ResourceSelector/RuleIndex
- **Deliverable**:
  - `rules/snapshot.py` — `RuleVersion` / `RuleSnapshot` / `RuleSnapshotAppliedEvent`
  - `rules/repository.py` — `RuleRepository` 校验 + 编译索引 + 原子替换 + last-known-good
  - `rules/selector.py` — `ResourceSelector`(EXACT/GLOB/PREFIX,1.0 不支持任意正则)
  - `rules/index.py` — `RuleIndex`(EXACT > PREFIX > GLOB 优先级,同类型 priority 降序,rule_id 升序)
- **Exit Criteria**:
  - 8 步更新流程(完整读取 → 解析 → 映射 → 校验 → 编译索引 → 不可变快照 → 原子交换 → 事件)全部实现
  - 解析失败保留 last-known-good,不先清空旧规则
  - 同一 epoch 同 revision 不同 checksum 拒绝 + 报警
  - epoch+revision 排序不能从字符串大小推断
- **Test ID**: SEN-RULE-001(全部:解析失败 / 乱序 / 重复 / 原子交换)
- **ADR**: ADR-SEN-007
- **Deps**: M1.4

### M1.6 [x] 完成 SEN-CORE、SEN-RULE、SEN-PERF 测试基线(不设绝对阈值)
- **Deliverable**:
  - `tests/test_sen_core.py` — Slot 逆序释放 + CancelledError + 故障注入(30 / 30)
  - `tests/test_sen_rule.py` — RuleSnapshot 校验 / 原子替换 / 乱序(36 / 36)
  - `tests/benchmark/test_sen_perf.py` — **收集数据,不是断言**:跑 5 个场景(无规则准入 / 单 FlowRule / 5 类规则同时 / 1000 条 exact 索引命中 / 1000 条索引未命中),输出 commit / Python / OS / CPU / 规则数 / 资源数 / 并发度 / p50 p95 p99 max / CPU RSS alloc GC
  - **基线报告**:`docs/acceptance/R-SENTINEL-M1-baseline.md`,只报告**观测到的数据**,不写"通过/不通过"硬阈值
- **Exit Criteria**:
  - SEN-CORE-001 / SEN-CORE-002 / SEN-RULE-001 全部 test pass
  - 10 分钟 load + spike + 1 小时 soak **数据归档**(M5 审批时引用)
  - **不**做"p99 < 1ms"等硬性断言
  - 10 分钟内无崩溃(M2-M5 过程中作为 sanity check;内存泄漏证据延后)
- **Test ID**: SEN-CORE-001~002, SEN-RULE-001, SEN-PERF-001(数据采集,无阈值)
- **ADR**: 全部
- **Deps**: M1.5
- **实现中修复的真 bug**:
  - 并发 entry 共享 `_context_token` 导致 `ValueError: Token was created
    in a different Context` → token 改存 `EntryLease._context_token`(per-entry)
  - lease 释放异常完全不可观测 → 新增 `EntryLease.last_release_error()`,
    `SentinelEngine._finalize_entry` 把它写到 `engine.last_error`

### M1 Exit [ ] (子项全部完成)
- **Exit Criteria**(§21 + 修正 4):
  - 无具体协议框架时,可通过公开 API 保护一个 async 业务资源
  - **demo 脚本 `examples/protect_async_business.py` 只能证明 Engine / 生命周期 / 指标 / 无规则 Entry;不能演示 FlowRule(M2 才有)**
  - Demo 内容:不开 ASGI/不用 HTTPX/不用任何 rule 文件,只手动构造 `SentinelEngine(rules=())` 空规则集 + `async with engine.entry(Resource("demo"))` 保护一段 `await asyncio.sleep(0.01)` 业务代码,验证 Outcome.ADMITTED/SUCCEEDED
- **验证命令**:
  - `uv run --no-sync python examples/protect_async_business.py` 跑通
  - `uv run --no-sync pytest components/sentinel/sentinel/tests/test_sen_core.py -v` 全过

---

## M2：五类规则

### M2.1 [x] FlowRule/FlowSlot,覆盖 direct/origin/associated/call-path
- **Deliverable**:
  - `rules/flow.py` — `FlowRule` + `FlowGrade` / `FlowBehavior` / `FlowScope` 枚举
  - `slots/flow.py` — `FlowSlot`(Order=500),4 种 scope 各自实现
  - 校验规则:threshold > 0;WARM_UP 必须 warm_up_period;QUEUE 必须 max_queueing_time ≥ 0;CONCURRENCY 不接受 WARM_UP;ASSOCIATED_RESOURCE/CALL_PATH 必须 scope_reference
- **Exit Criteria**:
  - 4 种 scope 都有测试(每种至少 3 个场景)
  - 构造校验(违规抛 `SentinelConfigurationError`)
  - 取消等待 → 撤销队列占位或保证调度不泄漏
- **Test ID**: SEN-FLOW-001
- **ADR**: ADR-SEN-006
- **Deps**: M1.6

### M2.2 [x] DegradeRule/DegradeSlot,并复用唯一 CircuitBreaker
- **Deliverable**:
  - `rules/degrade.py` — `DegradeRule` + `DegradeStrategy` 枚举
  - `slots/degrade.py` — `DegradeSlot`(Order=700),复用 `primitives.CircuitBreaker` 状态机
  - SLOW_CALL_RATIO 需要 slow_call_threshold;ERROR_RATIO 0..1;ERROR_COUNT 是绝对值
  - `minimum_request_count` 不足时不打开
  - HALF_OPEN 探测成功数 = `half_open_probe_count` 才恢复
  - 强制 open / close / reset 仅通过管理 API
- **Exit Criteria**:
  - 状态机所有合法迁移 + 非法迁移抛错
  - 强制 open 产生 `CircuitStateChangedEvent`
  - HALF_OPEN 任一失败立刻重 OPEN
- **Test ID**: SEN-CB-001
- **ADR**: ADR-SEN-006
- **Deps**: M2.1(共享 SlotChain 框架)

### M2.3 [x] ParamFlowRule/ParamFlowSlot 和基数治理
- **Deliverable**:
  - `rules/param_flow.py` — `ParamFlowRule` + `ParameterSpec` + `ParameterOverride` + `ParameterSource` 枚举
  - `slots/param_flow.py` — `ParamFlowSlot`(Order=600)
  - 校验:POSITIONAL 用 int,KEYWORD/HEADER/QUERY/COOKIE 用 str,CUSTOM 必须 extractor_id
  - 基数治理:max_distinct_values + idle_ttl + overflow policy
- **Exit Criteria**:
  - 6 种 source 各有测试
  - 基数达到 max_distinct_values → overflow bucket 或拒绝
  - idle TTL 触发自动淘汰
- **Test ID**: SEN-PARAM-001
- **ADR**: —
- **Deps**: M2.1

### M2.4 [x] SystemRule/SystemSlot/SystemMetricSampler,覆盖 direct 和 adaptive capacity
- **Deliverable**:
  - `rules/system.py` — `SystemRule`(直接继承 `Rule`,**不是** `ResourceRule`)
  - `slots/system.py` — `SystemSlot`(Order=400),**只对 INBOUND 资源生效**
  - `ports/system_metric_sampler.py` — `SystemMetricSampler` Protocol
  - 两种 strategy:DIRECT(任一硬阈值触发)和 ADAPTIVE_CAPACITY(Little's Law 估算)
  - 主包默认不安装 psutil;`system` extra 才装
- **Exit Criteria**:
  - DIRECT 模式:CPU > 0.8 / Load > 4.0 / event_loop_lag > 阈值 / in-flight > max 各自测试
  - ADAPTIVE_CAPACITY:`estimated_capacity = max(1, completed_qps * min_stable_rt)` 公式验证
  - SystemMetricSampler 暂时失败 → 跳过依赖指标,标记 degraded health,不影响其他规则
  - INTERNAL / OUTBOUND 资源不触发 SystemSlot
- **Test ID**: **SEN-SYSTEM-001**(新定义,见 M0.9.1);**不**挂 SEN-CB-001(熔断语义无关)
- **ADR**: ADR-SEN-014, ADR-SEN-015
- **Deps**: M2.1

### M2.5 [x] AuthorityRule/AuthoritySlot
- **Deliverable**:
  - `rules/authority.py` — `AuthorityRule` + `AuthorityStrategy` 枚举(ALLOW_LIST / DENY_LIST)
  - `slots/authority.py` — `AuthoritySlot`(Order=300)
  - origin 必须来自受信任的 `OriginResolver`(JWT / mTLS / 网关验签 / 内部服务账号)
  - 直接读 `X-Origin` 仅作为显式启用的不可信示例
- **Exit Criteria**:
  - ALLOW_LIST 通过 / 不在列表 → 通过/拒绝
  - DENY_LIST 在列表 → 拒绝
  - 默认禁用客户端自报身份;`OriginResolver` 配置错误 → 拒绝 + 审计
- **Test ID**: **SEN-AUTH-001**(新定义,见 M0.9.1);**不**主要依赖 SEN-DASH-001(那是 dashboard 测试)
- **ADR**: —
- **Deps**: M2.1

### M2.6 [x] 完成所有规则边界、状态、并发和组合测试
- **Deliverable**:
  - 每类规则:边界、状态、并发 3 类测试
  - 组合测试:Flow + Degrade + ParamFlow + Authority + System 同 resource 触发
  - 覆盖 `RuleIndex` 查询路径
- **Exit Criteria**:
  - 5 类规则都有稳定契约
  - 组合行为有证据
  - 全部 deterministic(Monotonic Clock)
- **Test ID**: SEN-CORE-001(完整),SEN-CB-001(完整),SEN-FLOW-001, SEN-PARAM-001, SEN-SYSTEM-001, SEN-AUTH-001
- **ADR**: 全部
- **Deps**: M2.1-M2.5 全部

### M2.7 [x] 定义无第三方依赖的 `TokenService` Protocol + 本地默认实现
- **背景**: DESIGN.md ADR-SEN-011 要求 1.0 主包**必须预留** `TokenService` Port,Cluster M6+ 填入实现。若 M2 阶段不预留,FlowSlot 完成后再加会重写 FlowSlot。
- **Deliverable**:
  - `ports/token.py` — 冻结值对象,无 3rd-party 依赖(`dataclasses.dataclass(frozen=True, slots=True)`):
    ```python
    class TokenDecision(StrEnum):
        LOCAL_GRANTED   = "local_granted"     # 本地默认实现直接放行(单进程常态)
        REMOTE_GRANTED  = "remote_granted"    # 集群 token 服务返回 permit
        FAIL_OPEN       = "fail_open"         # 远端不可达,本地策略性放行(降级事件)
        DENIED          = "denied"            # 拒绝(配合 deny_reason 看为什么)

    class TokenDenyReason(StrEnum):
        QUEUE_FULL          = "queue_full"          # 等待队列满
        REMOTE_UNAVAILABLE  = "remote_unavailable"  # 集群 token 服务不可达
        RATE_LIMITED        = "rate_limited"        # 集群 rate-limit 拒绝
        SHUTTING_DOWN       = "shutting_down"       # 节点关闭中
        UNKNOWN             = "unknown"             # 兜底
        # 注:授权拒绝不属于 TokenService,AuthoritySlot 走 SentinelBlockedError.AuthorityDenied

    @dataclass(frozen=True, slots=True)
    class Token:
        resource: str
        permits: float
        issued_at_ns: int        # SystemClock 纳秒
        ttl_ns: int              # 0 = 永久

        def is_expired(self, now_ns: int) -> bool: ...

    @dataclass(frozen=True, slots=True)
    class TokenResponse:
        decision: TokenDecision                 # 必填,4 选 1
        token: Token | None                     # 强制不变量(见 __post_init__)
        deny_reason: TokenDenyReason | None     # 强制不变量(见 __post_init__)
        wait_ns: int                            # 0 = 立即;>0 = 建议等待纳秒

        def __post_init__(self) -> None:
            if self.decision is TokenDecision.DENIED:
                if self.token is not None:
                    raise ValueError("TokenResponse: DENIED 必须 token is None")
                if self.deny_reason is None:
                    raise ValueError("TokenResponse: DENIED 必须 deny_reason is not None")
            else:  # LOCAL_GRANTED / REMOTE_GRANTED / FAIL_OPEN
                if self.token is None:
                    raise ValueError(f"TokenResponse: {self.decision.value} 必须 token is not None")
                if self.deny_reason is not None:
                    raise ValueError(f"TokenResponse: {self.decision.value} 必须 deny_reason is None")

        def is_granted(self) -> bool:
            return self.decision in (TokenDecision.LOCAL_GRANTED, TokenDecision.REMOTE_GRANTED, TokenDecision.FAIL_OPEN)
    ```
    - **拆分语义**:`decision` 描述"放行还是拒绝";`deny_reason` 只在 `decision is DENIED` 时存在。
    - **强制不变量**:`__post_init__` 兜底所有错误组合,违反即 `ValueError`(测试覆盖四种非法组合:granted+deny_reason、granted+token=None、denied+token!=None、denied+deny_reason=None)。
    - **授权拒绝不在本层**:`TokenDenyReason` 不含 `AUTHORITY_DENIED`;黑白名单/授权拒绝由 `AuthoritySlot` 在 `SentinelBlockedError` 树上独立表达,`TokenService` 只管配额/限流/集群协调。
    - **永不暴露裸字符串**:`decision` / `deny_reason` 必传 `StrEnum` 成员。
    - **`FAIL_OPEN` ≠ `LOCAL_GRANTED`**:正常单进程默认 `LocalTokenService.acquire()` 走 `LOCAL_GRANTED`;只有集群模式远端不可达、本地策略降级放行时才是 `FAIL_OPEN`(会被 metrics 标成降级事件)。
    - **`None` 的合法用法**:`deny_reason: None` 表示"没有拒绝原因",不是"原因未知";`UNKNOWN` 是真存在但不可分类。审计代码用 `if response.deny_reason is not None` 而不是 `is TokenDenyReason.UNKNOWN`。
  - `ports/token_service.py` — `TokenService` Protocol,无 3rd-party 依赖
    ```python
    @runtime_checkable
    class TokenService(Protocol):
        async def acquire(self, resource: Resource, permits: float) -> TokenResponse: ...
        async def release(self, token: Token) -> None: ...
    ```
  - `ports/__init__.py` re-export `Token` / `TokenResponse` / `TokenService` / `Resource`
  - `slots/_local_token_service.py` — `LocalTokenService`,永远 grant permit(单进程不需要 token 协调)
  - `SlotChain` 默认用 `LocalTokenService`;`SentinelEngine(token_service=...)` 可注入其他实现
  - FlowSlot 在 acquire 资源时调用 `token_service.acquire()`;若 TokenService 暂时不可用(集群模式)按 fail-safe 策略:1.0 fail-open(单进程 = 永远能拿 token)
- **Exit Criteria**:
  - `from atlas_richie.sentinel.ports import Token, TokenResponse, TokenService, Resource, TokenDecision, TokenDenyReason` 成功
  - `LocalTokenService().acquire(...)` 永远返回 `TokenResponse(decision=TokenDecision.LOCAL_GRANTED, token=Token(...), deny_reason=None, ...)`
  - `LocalTokenService` 产生的响应**绝不**带 `decision=FAIL_OPEN` 标记(只有集群降级路径才用)
  - FlowSlot 测试用 mock TokenService 验证「token 申请/释放」调用路径,且同时验证 `decision` 流转(本地 grant / 远端 grant / fail-open / denied 4 路)
  - `Token` / `TokenResponse` 是 frozen + slots,`__hash__` 稳定,可放进 set / dict
  - `TokenResponse.deny_reason` 字段类型是 `TokenDenyReason | None`,不接受裸字符串(类型检查 + 测试覆盖)
  - **不**依赖任何网络 / 进程间通信(零 3rd-party 兼容 1.0 主包约束)
- **Test ID**: SEN-CORE-001(part:flow)
- **ADR**: ADR-SEN-011
- **Deps**: M2.1

### M2 Exit [ ] (子项全部完成)
- **Exit Criteria**(§21 + ADR-SEN-011):
  - 五类规则均有稳定契约、确定性测试和组合行为证据
  - 全部 `Outcome` 区分在测试中验证(ADMITTED vs BLOCKED)
  - 状态机非法迁移 0 例外
  - **`TokenService` Port 已在主包定义 + `LocalTokenService` 默认实现就位**(M2.7 退出条件)

---

## M3：File Source 与 ASGI

### M3.1 [x] 实现 RuleSource contract test kit(M3 仅供 File Source 使用)
- **Deliverable**:
  - `tests/contract/test_rule_source.py` — 公用的 RuleSource 契约测试集
    (实际放在 `tests/test_sen_rule_source.py`,带 `_RuleSourceContractBase`
    基类 + `__test__ = False` 不被自动 collect)
  - 覆盖:首次迭代成功/失败、迭代结束 / 监听退出 / 重连、指数退避 + jitter、消费速度慢于更新速度的合并/背压、stale 状态、aclose 幂等、凭证脱敏
  - **M3 阶段只跑 File Source 接入同一套 contract**(M3.2 交付)
  - **Nacos / Redis 在 M6+ 才加入**同一套 contract suite(M6.1 / M6.2 任务里跑)
- **Exit Criteria**:
  - Contract test 包含「协议满足性」「错误恢复」「资源清理」三组 — ✅ 25/25 通过
  - File Source(M3.2)通过 contract test — ✅ 18/18 通过(含额外 7 个)
  - M3 退出时 Nacos / Redis Source 还未实现
- **Test ID**: SEN-RULE-001
- **ADR**: ADR-SEN-007
- **Deps**: M1.6
- **实现说明**:
  - 契约基类:`_RuleSourceContractBase(unittest.TestCase)` + `__test__ = False`
    + 子类 `__test__ = True` 重新启用 collection
  - 覆盖 Port identity (`isinstance(RuleSource)`) / start 幂等 / stop 幂等 /
    start 推 repository / missing file / 解析失败 / mtime cache / mtime 变更 /
    YAML 解析 / poll loop 健壮 / event-loop lifecycle
  - 测试 fixtures 包含 `_TestRule` 包装器(让 RuleIndex 编译)和
    `_WrappingFileRuleSource` 子类(把 JSON 包装成 Rule 对象)
  - 已知 mtime 文件系统分辨率限制:同一秒内 rewrite 产生相同 epoch;
    测试用 `os.utime` 强制改 mtime 来验证版本变化路径

### M3.2 [x] 实现 JSON/YAML File Source 和 last-known-good 热更新
- **Deliverable**:
  - 新 wheel `components/sentinel/sentinel-source-file/`
  - JSON 规范 + YAML 便捷两种 codec
  - 文件写入:临时文件 + 原子 rename
  - watchfiles 监听 + 去抖
  - 读取到半文件 → 保留旧快照 + 重试
  - 文件不存在 / 权限 / 语法 / 规则校验错误分别报告
  - **不**由 ASGI Adapter 自动启动
- **Exit Criteria**:
  - 通过 M3.1 contract test(File Source)
  - 真实临时文件 + 多次写 + rename 测试
  - YAML 和 JSON 都能 round-trip
- **Test ID**: SEN-RULE-001(part:file)
- **ADR**: ADR-SEN-007
- **Deps**: M3.1, M1.6

### M3.3 [x] 实现纯 ASGI Middleware
- **Deliverable**:
  - 新 wheel `components/sentinel/sentinel-adapter-asgi/`
  - `SentinelASGIMiddleware`:**纯 ASGI callable,不继承 Starlette / FastAPI**,不强制任何 web framework
  - **不**自动启动 File Source(用户显式接入 RuleSource)
  - lifespan 永不进入业务流控
  - 默认 HTTP 映射:FLOW/PARAM_FLOW/CONCURRENCY → 429;SYSTEM_OVERLOAD → 503;CIRCUIT_OPEN → 503 + retry-after;AUTHORITY_DENIED → 403;INTERNAL_CONFIGURATION → 500
  - 响应体:稳定 code / resource / reason / request_id;**不**暴露规则全文 / 阈值 / 堆栈
- **Exit Criteria**:
  - **测试方式二选一,不要混写**:
    - (A) 单元 / 集成:直接驱动 ASGI callable — 调用方提供 `scope` dict + `receive` async generator + `send` async collector,手工 `await middleware(scope, receive, send)` 验证(http 场景用 `httpx.AsyncClient(transport=ASGITransport(app=middleware))` 是 httpx 的 ASGI 适配,**不**是直接 ASGI 协议测试,可选)
    - (B) 端到端:`uvicorn` 子进程拉起服务 + `httpx.AsyncClient` 通过真实 HTTP 请求验证
  - **不**用 `starlette.testclient.TestClient` / `fastapi.testclient.TestClient`(违反纯 ASGI 约束)
  - lifespan scope 不被 ingress QPS 计入
  - 5 种 BlockReason 的 HTTP 状态 + body 正确
  - 客户端断连 → CANCELLED,不计入业务异常
- **Test ID**: SEN-ASGI-001
- **ADR**: ADR-SEN-008
- **Deps**: M1.6, M2.5(Authority)

### M3.4 [x] 实现资源命名、可信 origin 和参数提取 Strategy
- **Deliverable**:
  - `components/sentinel/sentinel-adapter-asgi/src/atlas_richie/sentinel/adapters/asgi/strategies/`:
    - `resource_name.py` — `MethodRouteResolver`("POST /orders")等
    - `origin.py` — `AuthenticatedScopeOriginResolver`(默认不可信,要求显式配置)
    - `parameter_extractor.py` — `HeaderExtractor` / `QueryExtractor` / `CookieExtractor`
  - 动态路径(订单号等)必须归一化,禁止作为 resource name
- **Exit Criteria**:
  - 6 种 strategy 实现 + 各自测试
  - 不可信 origin 默认拒绝
  - 路径模板变量({order_id})不进入 resource name
- **Test ID**: SEN-ASGI-001(part),SEN-CORE-001(part)
- **ADR**: ADR-SEN-008
- **Deps**: M3.3

### M3.5 [x] 验证普通响应、流式响应、断连、取消、异常、lifespan
- **Deliverable**:
  - `sentinel-adapter-asgi/tests/test_asgi.py` — 21 个 ASGI 协议测试
  - 6 个 ASGI 协议场景测试:
    1. 普通响应(返回 200 + body) — 5 tests
    2. 流式响应(more_body=True 直到 EOF,Entry 不能在第一个 body 后释放) — 2 tests
    3. 客户端断连(EOF / CancelledError 注入) — 2 tests
    4. cancel(scope.receive 抛 CancelledError / task cancel during app) — 1 test
    5. 业务异常(Outcome.FAILED,HTTP 5xx) — 2 tests
    6. lifespan(lifespan start / shutdown 不被业务流控) — 2 tests
  - 额外: BLOCKED 路径(503) / origin 解析(5 tests) / websocket 透传(1 test)
- **Exit Criteria**:
  - 6 个场景 permit 都正确释放 — ✅ 21/21 通过
  - 流式响应 body EOF 才 release(非首次 send) — ✅
  - 业务异常不吞,响应能 close — ✅
- **Test ID**: SEN-ASGI-001
- **ADR**: ADR-SEN-008
- **Deps**: M3.3, M3.4
- **真实修复**(测试中暴露):middleware 之前
  `entry.__aexit__(None, None, None)` 永远传 None,导致 engine 永远看不到
  CANCELLED / FAILED outcome。改为按实际异常类型传参:
  asyncio.CancelledError → CANCELLED,BaseException → FAILED。

### M3.6 [x] 完成真实多 worker 语义测试
- **Deliverable**:
  - `tests/test_sen_multiprocess.py` — 3 个测试
  - 用 `multiprocessing.get_context("spawn")` 启动 2 个真子进程,
    各自独立创建 Engine / RuleRepository
  - **不**走 uvicorn / gunicorn(测试不引入 web server 依赖)
- **覆盖**:
  - `test_two_workers_have_independent_state` — 2 个进程独立 Engine,
    验证 PID 不同 + admitted 计数独立(5 / 7 都返回,无 cross-talk)
  - `test_two_workers_do_not_share_repository_state` — Worker A apply
    快照,Worker B 看到自己空 repo
  - `test_two_engines_have_independent_inflight` — In-process 类比:
    engine_a.in_flight 增 1 不影响 engine_b.in_flight
- **测试重点**:每个 worker 的规则和指标**彼此隔离**(per-process 语义)
  - **不**断言"configured threshold × worker count = capacity"
  - 文档明确说明 per-process 语义,Cluster 模式下才有跨 worker 精确总量
  - Dashboard 不会把单 worker 数据描述成整个服务
- **Exit Criteria**:
  - 2 个独立 worker 状态完全隔离 — ✅ 3/3 通过
  - per-process 文档明确 — ✅ PLANNING §M3.6 + DESIGN §M3.6
  - 2 worker 跑 30s 持续,每个 worker 的 metric 报告**独立**正确
  - 同一 resource 在 worker A 累计的 pass_count + worker B 累计的 pass_count ≠ 全局 pass_count(各自独立)
  - 同一 resource 触发的 BlockReason 在两个 worker 中分别记录
  - 测试输出明确说明 per-process 语义
- **Test ID**: SEN-MP-001
- **ADR**: ADR-SEN-008
- **Deps**: M3.5

### M3 Exit [ ] (子项全部完成)
- **Exit Criteria**(§21):
  - 任意 asyncio ASGI 应用无需依赖 FastAPI/Starlette 即可接入
  - 一个 demo:`uvicorn examples.asgi_demo:app --workers 4` 跑通
  - 6 种 ASGI 协议场景都验证过(普通/流式/断连/取消/异常/lifespan)
  - 多 worker per-process 语义清楚(无虚假容量保证)

---

## M4：HTTPX 出站保护

### M4.1 [x] 实现 SentinelAsyncTransport
- **Deliverable**:
  - 新 wheel `components/sentinel/sentinel-adapter-httpx/`
  - `SentinelAsyncTransport`:**只读公开的 `httpx.AsyncBaseTransport`**,**不**碰 `httpcore` 私有属性
  - 能力名:`OutboundConcurrencyGuard`(**不是** PoolGuard)
  - 包装默认或用户提供的 transport
  - 资源命名:`httpx:{scheme}://{host}:{port}`
- **Exit Criteria**:
  - `grep -rE "httpcore\._|httpcore\.[a-z]+_" sentinel-adapter-httpx/` 返回 0 行(httpcore 私有字段禁用)
  - 公开 AsyncBaseTransport API 调用通过
  - aclose 幂等且只调用一次
- **Test ID**: SEN-HTTPX-001
- **ADR**: ADR-SEN-009
- **Deps**: M1.6

### M4.2 [x] 实现全局和 per-origin 并发/排队保护
- **Deliverable**:
  - per-origin key:scheme + normalized host + effective port
  - 全局和 per-origin 都有 permit 上限
  - permit 在响应流 EOF 或 aclose 后释放(不是 `handle_async_request` 返回时)
  - 等待被取消时撤销 permit
- **Exit Criteria**:
  - 真实下游服务测试:per-origin 超额 → 拒绝 / 排队
  - permit 释放时机正确(测试中验证)
  - 取消 / 异常都不泄漏 permit
- **Test ID**: SEN-HTTPX-001(part)
- **ADR**: ADR-SEN-009
- **Deps**: M4.1

### M4.3 [x] 包装响应流并在 EOF/aclose 释放
- **Deliverable**:
  - 包装 response stream,**在 EOF 或 `aclose()` 时释放 permit**(不是 `__aexit__` —— HTTPX 用户常用 `await response.aread()` 读 body,不需要 `__aexit__` 入口)
  - permit 释放是 idempotent,多个 aclose 调用只释放一次
  - 提供 `__aenter__` / `__aexit__` 是为了在 `async with client.stream(...) as response` 模式下也能正确释放
- **Exit Criteria**:
  - 流式响应(分多次 `aread()`)期间 permit 持锁
  - **EOF(流读完)** → 释放 permit
  - **`aclose()`** 调用 → 释放 permit;第二次 aclose 幂等
  - **异常** → 释放 permit
  - 测试用 `httpx.AsyncClient` + 流式 response 验证 4 种释放路径
- **Test ID**: SEN-HTTPX-001
- **ADR**: ADR-SEN-009
- **Deps**: M4.2

### M4.4 [x] 实现 OutcomeClassifier
- **Deliverable**:
  - 把连接错误 / 超时 / 5xx / 4xx / 2xx / 取消分别映射 Outcome
  - **HTTPX 实际语义**:响应 5xx **不会**自动抛 `httpx.HTTPStatusError`;只在调用方 `raise_for_status()` 时才抛。OutcomeClassifier 必须**显式**读取 `response.status_code`,**不**依赖 `raise_for_status()` 已调用
  - 默认:只把连接错误、超时、5xx 计为下游故障;4xx 不自动计为
  - 策略可注入(用户可自定义哪些 HTTP 状态算失败)
- **Exit Criteria**:
  - 6 种 outcome 各自测试 — ✅ 26/26
  - **测试用 `httpx.Response(503)` 构造,显式断言 Classifier 读 status_code 判定失败**(不是 `raise_for_status` 路径) — ✅
  - 4xx 默认不触发 circuit breaker — ✅
  - 自定义 classifier 可注入 — ✅
- **Test ID**: SEN-CB-001(part:http)
- **ADR**: ADR-SEN-009
- **Deps**: M4.3
- **实现说明**:
  - 新增 `OutcomeClassifier` Protocol (`@runtime_checkable`) +
    `DefaultOutcomeClassifier` 默认实现(2xx/3xx/4xx → SUCCEEDED,
    5xx → FAILED,网络异常 → FAILED, CancelledError → CANCELLED,
    其它 Exception → FAILED, status_code=None → FAILED)
  - `classify_outcome(response)` 是 `DefaultOutcomeClassifier().classify()`
    的**兼容 shim**,返回值从 `str` 改成 `OutcomeKind.value` (`"succeeded"` /
    `"failed"` / `"cancelled"` / `"blocked"`)
  - **不**调用 `response.raise_for_status()`(显式 `MagicMock` 测试断言)
  - 覆盖文件: `sentinel-adapter-httpx/tests/test_outcome_classifier.py` (26 tests)

### M4.5 [x] 与 Retry/CircuitBreaker 组合测试(默认不重试)
- **背景**(DESIGN.md §12.3 + §8.1):
  - HTTPX Adapter **默认不重试**;Adapter 自身不在 `handle_async_request` 内 retry
  - 只有调用方**显式组合 `RetryPolicy`**(从 `primitives.retry`)+ `IdempotencyKey` 显式允许 + 把 retry 接入到出站调用链中,5xx 才触发重试
  - 重试时每次真实网络 attempt 重新走 SentinelAsyncTransport 的 permit / 流控 / 熔断
  - 4xx 不视为下游失败(默认),不触发任何 retry/CB
  - **现有 `IdempotencyKey` 实现是 `StatelessIdempotencyKey` / `NeverIdempotencyKey` / `CallableIdempotencyKey`**(M0.5 保留),**不**是 M4.5 之前假设的 `.always` / `.never`
- **Deliverable**:
  - `tests/test_sen_retry_cb_compose.py`: 11 个测试覆盖 5 场景
- **覆盖矩阵**:
  - 默认不重试 (2): 5xx + 无 raise_for_status 不抛 / 5xx + raise_for_status 抛但不 auto-retry
  - 4xx 不计下游失败 (2): Classifier 4xx → SUCCEEDED / 不参与 CB 失败计数
  - RetryPolicy 组合 (4): 5xx + StatelessKey 重试 3 次 / 5xx + NeverKey 抛 RetryNotPermitted / 4xx 默认被 retry(用户责任过滤) / CallableKey 返回 None 拒绝重试
  - CircuitBreaker 集成 (2): 连续 5xx 触发 DegradeRule 短路 / 连续 success 重置
  - Classifier + CB 端到端 (1): 5xx 触发 classifier → CB 计数 → threshold 后短路
- **Exit Criteria**:
  - 默认行为测试断言"5xx + 无 raise_for_status 不抛"为真 — ✅
  - 默认行为测试断言"5xx + raise_for_status 抛但不自动 retry"为真 — ✅
  - 显式 `RetryPolicy` + `StatelessIdempotencyKey` 组合测试断言"5xx 重试 N 次"为真 — ✅
  - 4xx 默认被 retry(RetryPolicy 默认 retriable_exceptions=(Exception,));
    用户需自定义 policy 来排除 4xx — 已文档化
  - CircuitBreaker 连续失败 → 短路 — ✅
  - 测试 11/11 通过
  - 显式 `RetryPolicy` + `NeverIdempotencyKey` 组合测试断言"5xx 不重试"为真
  - 4xx 在所有路径下都不重试
  - 真实下游服务测试
- **Test ID**: SEN-HTTPX-001(part),SEN-CB-001(part)
- **ADR**: ADR-SEN-009
- **Deps**: M4.4

### M4.6 [x] 禁止任何 httpcore 私有 API 使用
- **Deliverable**:
  - `tests/test_no_httpcore_private.py` — 静态扫描所有 sentinel-adapter-httpx 源码,断言没有任何 `httpcore._xxx` 或私有 attr 访问
  - CI lint 规则(可选,grep 也可以)
- **Exit Criteria**:
  - 测试通过
  - 文档明确「不读 httpcore 私有」是设计约束
- **Test ID**: SEN-HTTPX-001
- **ADR**: ADR-SEN-009
- **Deps**: M4.5

### M4 Exit [ ] (子项全部完成)
- **Exit Criteria**(§21):
  - 受控真实下游服务上的正常 / 失败 / 超时 / 流式 / 取消 场景通过
  - 一个 demo:examples/httpx_demo.py 跑 5 种场景

---

## M5：Embedded Dashboard、文档和 1.0

### M5.1 [x] 实现 per-process embedded 管理 API
- **Deliverable**:
  - 新 wheel `components/sentinel/sentinel-dashboard/`
  - REST API:
    - `GET /api/v1/resources`
    - `GET /api/v1/metrics`
    - `GET /api/v1/rules`
    - `PUT /api/v1/rule-snapshots/{source}`(完整快照提交)
    - `GET /health/live`
    - `GET /health/ready`
  - 不提供 `POST /rules` 逐条修改(只完整快照)
- **Exit Criteria**:
  - 6 个 endpoint 全部实现
  - PUT 完整快照 + 走 RuleRepository 原子更新(不是 ad-hoc)
- **Test ID**: SEN-DASH-001
- **ADR**: ADR-SEN-010
- **Deps**: M1.6, M3.1(依赖 RuleRepository)

### M5.2 [x] 默认 loopback/read-only,写操作认证授权审计
- **Deliverable**:
  - 默认绑定 127.0.0.1
  - 默认 read-only
  - 写操作要求显式配置认证 + 授权(mTLS / OAuth / API key,任一)
  - 所有 PUT 请求记录 principal / source / old_version / new_version / checksum / 结果
  - 不记录规则中敏感扩展字段
  - 健康检查不泄露文件路径 / Redis/Nacos 地址 / 凭证
- **Exit Criteria**:
  - 无认证 → 401(写操作)
  - 错误认证 → 403
  - 越权 → 403
  - 审计日志记录全字段
- **Test ID**: SEN-DASH-001
- **ADR**: ADR-SEN-010
- **Deps**: M5.1

### M5.3 [x] 完成中英文 Quick Start、规则手册、扩展开发、运维边界文档
- **Deliverable**:
  - `docs/QUICKSTART.md`(中英)
  - `docs/RULES.md` — 5 类规则详解
  - `docs/EXTENDING.md` — 写自定义 Slot / Rule / Source / EventSink
  - `docs/OPERATIONS.md` — per-process 语义、集群未实现边界、升级路径
- **Exit Criteria**:
  - 4 个文档每篇 ≥ 3 页
  - 中英双语
  - 全部 M0-M5 已实现功能覆盖
  - 明确列出未实现边界
- **Test ID**: —
- **ADR**: 全部
- **Deps**: M5.2

### M5.4 [x] 完成 Python/OS matrix、isolated wheel、性能和 soak 门禁
- **Deliverable**:
  - CI matrix:Python 3.12 / 3.13 / 3.14 × Linux / macOS
  - **1.0 只发布 5 个 wheel**:main + asgi + httpx + source-file + dashboard
    - Nacos / Redis / Cluster / observability **不参与 1.0**,留 1.x 评估
  - 5 个 wheel 干净 venv install + import + smoke test
  - 性能基线报告(p50/p95/p99/CPU/RSS/alloc/GC,5 种场景)
  - 10 分钟 load + spike + 1 小时 soak 数据
- **Exit Criteria**:
  - CI 全部 pass
  - 性能报告归档
  - soak 无内存泄漏证据(RSS 斜率稳定)
- **Test ID**: SEN-PERF-001
- **ADR**: —
- **Deps**: M4.6, M5.3
- **observability 处理**(M5 决策):若要 1.0 含 observability,**必须先**补 ADR + DESIGN.md §3.1 发行包表行,且实现满足 SEN-PERF-001 label 约束。否则推迟到 1.x。**不**发空 wheel。

### M5.5 [x] 完成 API review、CHANGELOG、迁移说明和 SBOM
- **Deliverable**:
  - API review checklist
  - `CHANGELOG.md`(M0-M5 每阶段一条)
  - `MIGRATION.md`(从 atlas-richie-resilience / Java Sentinel 迁过来)
  - `SBOM`(cyclonedx 或 spdx)
  - 公开 API 列表(`__all__.py` + 文档索引)
- **Exit Criteria**:
  - 4 个文档齐全
  - 公开 API 清单与文档一致
- **Test ID**: —
- **ADR**: —
- **Deps**: M5.4

### M5.6 [x] 发布 1.0.0(只发 5 个已实现 wheel)
- **Deliverable**:
  - 5 个 wheel 发到 PyPI:
    - `atlas-richie-sentinel`(主)
    - `atlas-richie-sentinel-asgi`
    - `atlas-richie-sentinel-httpx`
    - `atlas-richie-sentinel-source-file`
    - `atlas-richie-sentinel-dashboard`
  - **不**发 `sentinel-{source-nacos,source-redis,cluster,observability}`(M6+ 才发,符合 DESIGN.md "不发布空 wheel" 约束)
  - GitHub release tag
  - release notes 链接 CHANGELOG
- **Exit Criteria**:
  - `pip install atlas-richie-sentinel` 在干净环境成功
  - 1.0.0 不可变(后续 1.0.x 修复 bug,1.x 加 feature,2.0 破坏性)
- **Test ID**: —
- **ADR**: —
- **Deps**: M5.5

### M5 Exit [ ] (子项全部完成)
- **Exit Criteria**(§21 + §24):
  - 主包和已实现扩展达到公开 API 稳定承诺
  - 所有未验证边界明确列出
  - §24 1.0 Definition of Done 全部满足

---

## M6+：集群与聚合控制面

### M6.1 [ ] Nacos Source
- **Deliverable**: `components/sentinel/sentinel-source-nacos/` 实际实现
- **Exit Criteria**: 跑 M3.1 contract test + 真实 Nacos 服务器
- **Test ID**: SEN-RULE-001(part:nacos)
- **ADR**: ADR-SEN-007
- **Deps**: M3.1

### M6.2 [ ] Redis 可恢复 Source
- **Deliverable**: `components/sentinel/sentinel-source-redis/` 实际实现 + key 存储 + pub/sub 通知
- **Exit Criteria**: pub/sub 不能保证消息补偿,选 key+stream 二选一
- **Test ID**: SEN-RULE-001(part:redis)
- **ADR**: ADR-SEN-007
- **Deps**: M3.1

### M6.3 [ ] Token Server/Client
- **Deliverable**:
  - `components/sentinel/sentinel-cluster/` 实际实现
  - 1.0 预留的 `TokenService` Port 填入实现
  - 两种模式:Token Server + Embedded Server
- **Exit Criteria**: 单进程启动后,FlowSlot 走 token service 路径
- **Test ID**: SEN-CLUSTER-001
- **ADR**: ADR-SEN-011
- **Deps**: M5.6(主包先稳定)

### M6.4 [ ] 双实例故障和恢复验收
- **Deliverable**:
  - 2 个真实进程互发 token 同步
  - 覆盖:crash / 网络分区 / 超时 / 恢复 / 重复请求 / 规则版本切换
  - stale owner fencing 测试
- **Exit Criteria**:
  - 6 种场景全过
  - 容量不超发 / 不欠发
- **Test ID**: SEN-CLUSTER-001
- **ADR**: ADR-SEN-011
- **Deps**: M6.3

### M6.5 [ ] Agent Reporting Protocol
- **Deliverable**:
  - 协议:instance_id + 启动纪元 + 指标序号 + 重复/乱序/离线处理 + 频率 + 背压 + mTLS
  - client(报告方)+ server(聚合方)SDK
- **Exit Criteria**:
  - 协议 spec 文档化
  - 跨进程指标聚合 demo
- **Test ID**: SEN-CLUSTER-001
- **ADR**: —
- **Deps**: M6.3

### M6.6 [ ] 聚合 Dashboard 和 Web UI(1.x 评估,不在 M6 默认范围)
- **背景**: `sentinel-dashboard-aggregator` 是新发行包,DESIGN.md 没批准。**从 M6 默认范围中删除**。若要纳入 M6,必须先:
  - 补 ADR(M6 范围内需要用户签字)
  - 更新 DESIGN.md §3.1 发行包表加一行
  - 在 §25 决策记录中加 ADR-016
- **Deliverable**:**默认无**(M6 退出不要求)
- **推迟到 1.x**(`M5.4.1` 候选任务,需用户单独批准)
- **Test ID**: —
- **ADR**: 待用户签字才存在
- **Deps**: M6.5(协议)

### M6.7 [ ] WSGI/同步阻塞引擎可行性评估
- **Deliverable**:
  - 调研报告(同步 API、asyncio.run、threading 风险)
  - 决策:1.x 是否做?2.0 怎么做?
- **Exit Criteria**:
  - 报告归档
  - 明确决策 + 后续 milestone
- **Test ID**: —
- **ADR**: —
- **Deps**: M5.6

### M6+ Exit [ ] (M6.1-M6.5 全部完成;M6.6 默认不在范围)
- **Exit Criteria**(隐含):M6.1-M6.5 完成 + 双实例 + 跨进程验收;M6.6 聚合 dashboard 默认不在范围

---

## 跨 Milestone 依赖图(简)

```
M0 (包结构 + Resilience 合并)
  ↓
M1 (Engine / 生命周期 / 指标)
  ↓
M2 (5 类规则)  ──需要 M1 完整退出──
  ↓
M3 (File Source + ASGI)  ──需要 M2 完整退出──
  ↓
M4 (HTTPX 出站)  ──需要 M1 退出(用 Engine) + M2 CB 规则──
  ↓
M5 (Dashboard + 1.0)  ──需要 M3+M4 退出──
  ↓
M6+ (集群 / 聚合)  ──需要 M5 1.0 稳定──
```

---

## 决策记录(待填)

每次完成 M-阶段,在这里追加:
- 完成时间
- 与原计划偏差(若有)
- ADR 落地证据(测试 ID + commit hash)
- 已知限制
- 下个 milestone 准备
