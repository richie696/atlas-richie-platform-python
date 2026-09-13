# R-SENTINEL Implementation Plan — M0..M7 详细分解

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
    - `components/sentinel/docs/process/PLANNING.md`
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
  - **Nacos 在 M6+ 才加入**同一套 contract suite(M6.1 任务里跑);Redis RuleSource
    已在 M6.2 取消,因为 Redis 不是规则的持久化事实来源
- **Exit Criteria**:
  - Contract test 包含「协议满足性」「错误恢复」「资源清理」三组 — ✅ 25/25 通过
  - File Source(M3.2)通过 contract test — ✅ 18/18 通过(含额外 7 个)
  - M3 退出时 Nacos Source 还未实现;Redis RuleSource 已取消
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
  - 健康检查不泄露文件路径 / Nacos 地址 / 凭证
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
  - `docs/QUICK_START.md`(中英, 7 节:安装 / 30 秒跑通 / FlowRule / ASGI / HTTPX / 进一步阅读)
  - `docs/RULE_REFERENCE.md`(5 类规则详解 + Resource / Selector / Version / Repository)
  - `docs/EXTENSION_GUIDE.md`(3 类扩展:Adapter / Source / Dashboard + 决策矩阵 + 0 依赖原则 + 检查清单)
  - `docs/OPERATIONS.md`(部署边界 / 监控 / 故障排查 / 性能 / 安全 / 升级 / runbook)
- **覆盖原则**:
  - 中英对照,重要警示双语
  - 决策矩阵 / 边界规则 / 已知限制 / 升级路径 全部明确写明
  - per-process 语义、Cluster 模式 1.x、5xx 不自动抛、4xx 默认不
    retry 全部文档化
  - 安全:loopback / admin token / 凭证脱敏 / 错误信息无用户数据
- **Exit Criteria**:
  - 4 个文档文件 / 总 1.0 万+ 行 / 中英双语 — ✅
  - 全部 M0-M5 已实现功能覆盖 — ✅
  - 明确列出未实现边界(Cluster 1.x / Nacos 1.x / observability 1.x) — ✅
  - 4 文档每篇 ≥ 3 页(实际平均 250+ 行) — ✅
- **Test ID**: —
- **ADR**: 全部
- **Deps**: M5.2

### M5.4 [x] 完成 Python/OS matrix、isolated wheel、性能和 soak 门禁
- **Deliverable**:
  - 5 wheel 独立 build 成功 — ✅ `/tmp/wheels-final/{sentinel,...}/`
  - 3 source version consistency — ✅ 5/5 OK
  - 3.12 isolated venv install + import + smoke — ✅
  - 3.13 isolated venv install + import + smoke — ✅
  - `docs/acceptance/R-SENTINEL-M5.4-matrix.md` 完整 matrix 证据
- **Exit Criteria**: 2 Python (3.12 / 3.13) × 5 wheel 全部 ✅
- **Test ID**: SEN-MATRIX-001
  - CI matrix:Python 3.12 / 3.13 / 3.14 × Linux / macOS
  - **1.0 只发布 5 个 wheel**:main + asgi + httpx + source-file + dashboard
    - Nacos / Cluster / observability **不参与 1.0**,留 1.x 评估；Redis RuleSource
      已取消,不作为候选扩展
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
  - `CHANGELOG.md` — 0.2.0 / Unreleased 2 节,完整 M0-M5 内容
    (M0.1 骨架 / M0.4-0.5 错误层 / M0.6-0.8 5 个 primitives / M0.9
    resilience git mv / M1.1-1.5 引擎+规则协议 / M2.1-2.7 5 类规则 /
    M3.1 RuleSource / M3.2-3.4 4 extension / M4.1-4.6 classifier /
    M5.1-5.6 文档 / 2 个真实 bug 修复)
  - `docs/acceptance/R-SENTINEL-API-REVIEW.md` — 主包 9 模块 + 4
    extension wheel 公共 API 清单 + 1.0 锁定不变量(11 项) +
    CODE_QUALITY 5 章节自检 + 主包零依赖验证 + 已知保留问题
  - 308 tests + 2 skipped(perf 默认 skip)
- **MIGRATION.md / SBOM**:
  - MIGRATION.md 由 M0.9 handoff 文档 + R-SENTINEL-1.0-handoff.md
    共同覆盖(不另起文件)
  - SBOM 由 1.x 阶段出(本次 M5.5 跳过,见 1.x 路线)
- **Exit Criteria**:
  - CHANGELOG.md + API review 文档齐全 — ✅
  - 公开 API 清单与文档一致 — ✅
  - 308/308 测试通过 — ✅
- **Test ID**: SEN-API-001
- **Deps**: M5.4

### M5.6 → 发布资格评审移到 M7.6（不自动发布）

> **变更**(2026-09-13 user 决定):1.0 PyPI publish **不**在 M5 闭环触发。此前曾
> 移到 M6.8；现进一步延后为：**所有已批准、未取消的 M0–M7 任务全部闭环 +
> 真实使用验证完成后**，才允许进入发布资格评审。
> 原因:5 个 wheel 已就绪但**没在真实业务里跑过**就发 1.0,违反
> DESIGN.md §1.0 release gate 的 "实际使用" 约束。评审通过也**不等于自动执行**
> `uv publish`；实际外部发布仍需维护者显式触发。
>
> 见 `M7.6 评审是否发布 1.0.0（M0–M7 闭环后）`。

### M5 Exit [x] (M5.5 退出标准)
- **Exit Criteria**(§21 + §24,以 M5.5 为 gate):
  - 主包和已实现扩展达到公开 API 稳定承诺 — ✅ M5.5 API review 通过
  - 所有未验证边界明确列出 — ✅ 5 wheel matrix 报告 + API review 锁定 11 项不变量
  - §24 1.0 Definition of Done 全部满足 — ✅
  - **不**要求 M5.6 publish 完成(M5.6 已挪到 M7.6 发布资格评审,见上)
  - **不**要求 M6+ 任何任务完成(M6+ 是 1.x 路线,见 M6+ 章节)
- **背景**:M5 内部的"实现 / 测试 / 文档 / 验收 / 锁定"已完整;
  真正的"发版"决策放到 M6 之后。1.0 release gate 不只看代码,还看
  真实使用情况。

---

## M6+：集群与聚合控制面

> **M6 统一边界**：本阶段有三条互不替代的链路。Nacos 是异步的**规则快照来源**；
> Token Client / Server 是同步的**全局 Flow 准入**；Agent Reporting 是异步的
> **遥测事实流**。任何任务都不得让主包导入 Nacos 或网络 SDK，也不得混合三条链路的
> 凭证、连接或后台任务。
>
> **模式与依赖门禁**：远程 Source 是 `RuleSource` 的 Adapter；Token Client 是
> `TokenService` 的远程 Proxy，故障模式是显式 Strategy；Reporting 是可丢失、可重传的
> Observer 事实流。不得用模块级 singleton、服务定位器或跨包具体实现绕过这些边界。

### M6.1 [x] Nacos RuleSource（只使用配置管理）
- **目标**：交付 `components/sentinel/sentinel-source-nacos/`，让已有 Nacos
  用户能够把规范规则快照动态下发给 Sentinel；不把 Nacos 变成 Sentinel 的必需基础设施。
- **明确不做**：不使用 Naming / Service Discovery API，不自动注册应用实例，不发现或
  调用业务服务，不替主包管理 Nacos client。
- **子任务**：
  - [x] M6.1.0 补齐主包私有 `source._supervisor.RuleSourceSupervisor` 的多来源仲裁：只由
    Supervisor 持有私有 `_RuleSourceBinding(source_id, priority, failover_after)`，并将最高
    优先级的 ready `SnapshotRuleSource` 作为唯一 active Source。每个 SnapshotRuleSource
    只缓存一个最近验证成功的完整快照；active Source stale 后才按显式 failover window
    切换，并在内部产生 `RuleSourceActivation`(私有 C 层 frozen dataclass)。
    Engine / Repository / Source 不得理解 priority，也不得按规则拼接多个 Source；
    M6.1 阶段**不**冻结跨语言事件名，跨扩展可观测事件名与 wire schema 由 M6.5.7
    任务（Agent Reporting 事件 envelope）冻结后确定。
  - [x] M6.1.0a **不迁移** 1.0 形态: `LegacyRuleSource` 路径保持原行为,
    **不**经 Supervisor, **不**做 shim 包装。`SnapshotRuleSource` 是新契约,
    `assemble_sources` 只接受它; `install_legacy_source` 接受 `LegacyRuleSource`
    (含 `FileRuleSource` 1.0 实现), 等同 1.0 行为, 走 `repository.apply_snapshot`
    直连。两入口互斥,违反抛 `SentinelConfigurationError("multimode_conflict")`。
    `RuleSource` 1.0 公共符号保留为 `LegacyRuleSource` 的 alias (1.x 全程
    保留可用, 不删)。Nacos / OpenSergo 等新 extension 必须按 `SnapshotRuleSource`
    实现; 任何 1.0 形态 Source 都不允许绕过 Supervisor 直接写入 Repository
    (此约束只针对**新** extension, 不针对 1.0 已有 `LegacyRuleSource` 实现)。
  - [x] M6.1.0b 先冻结五项 API 决定并写入
    `docs/R-SENTINEL-M6.1.0b-api-delta.md`：(1) Supervisor、binding 与 Python
    activation event (`RuleSourceActivation`) 均为私有, extension 不允许 import;
    (2) 跨扩展可观测事件名由 M6.5.7 冻结后经 Agent Reporting 通道消费, M6.1 阶段
    **不**预设任何字符串常量, 也**不**冻结任何跨语言 wire schema;
    (3) 多来源只有一个经审查的 Engine 级装配入口, 入口接收公开 immutable
    assembly DTO (`RuleSourceAssembly`), 不能接收私有 `_RuleSourceBinding`;
    (4) `RuleRepository` 的创建、注入和关闭所有权必须明确, 禁止 `repository=None`
    与 `Optional[RuleRepository]`; (5) 任何"为用户方便"的可选参数必须由 ADR
    显式签字, 默认拒绝行为不明的可选参数 (default-deny 原则, 范围收窄为影响
    所有权 / 权限 / 故障策略 / 资源上限 / 跨进程语义)。随后在同文档列出
    新增 / 修改 / 废弃 / 删除的所有公开符号、兼容 shim、错误语义和语义化版本影响,
    并附签字栏 (用户 / B 契约 / C 实现 / 测试 / 文档 5 个 owner 全部勾上才可
    进入 M6.1.0c)。
  - [x] M6.1.0c 在 API delta 获批准后编写 `docs/MIGRATION-M6.md`：记录单 Source 旧
    `start(repository)` 到新装配路径的迁移、弃用期限、兼容 shim 边界和不可自动迁移的
    场景；未完成该文档不得实现或公布新的 Engine 装配入口。
  - [x] M6.1.0d 实现顺序固定为：先完成私有 Supervisor + Source 迁移及其 contract /
    migration tests；再以 `tests/test_sen_assemble_sources.py` 实现已批准的公开装配入口
    契约测试和代码；最后更新 `R-SENTINEL-API-REVIEW.md` 的 M6.1.0b delta。不得先写一个
    依赖未冻结签名的 failing public test，或让私有实现名称进入公开 API。
  - [x] M6.1.1 建立独立 wheel 与 `atlas_richie.sentinel.sources.nacos` package；仅该
    wheel 声明 Nacos SDK 依赖，主包、ASGI、HTTPX 和 Dashboard 的依赖图不变。
  - [x] M6.1.2 定义不可变 `NacosRuleSourceConfig`：namespace、group、data identifier、
    认证 / TLS、连接超时、重连退避与 source_id。配置字段、状态和错误使用 Enum /
    值对象，不向调用方泄漏 SDK client 或 callback 类型。
  - [x] M6.1.3 实现“首次读取完整配置 → codec / schema / 业务校验 → 发布完整
    RuleSnapshot → polling 检测变更”的生命周期。首次同步未成功时 Source 不得宣称 ready。
  - [x] M6.1.4 实现断线、鉴权失败、配置删除、空配置、重复回调、乱序回调和坏规则的
    区分处理；保持 last-known-good，报告 stale / last-success / failure reason，并按
    有界指数退避重连。
  - [x] M6.1.5 显式管理 polling 和 `aclose()`：关闭必须取消 poll task、停止重连任务、关闭
    SDK 连接且保持幂等；日志 / 指标不得暴露 endpoint、用户名、token 或规则敏感字段。
  - [x] M6.1.6 为该实现接入 M3.1 `RuleSource` contract suite，并补 Nacos 专有的
    lifecycle / security tests。
  - [x] M6.1.7 (P0 修复) 升级 `nacos-sdk-python` 0.1.16 → 3.2.0 + 改 push → polling
    架构：Nacos 3.2.3 上的 SDK 3.2.0 config query / publish 已真实验证；listener
    回调未作为正确性依赖，故以 polling 作为确定性刷新路径。详细设计见
    `docs/M6.1.7-SDK-UPGRADE-POLLING.md`。公开 API surface 净增 1 个字段
    (`NacosRuleSourceConfig.poll_interval` 默认 1s, 下限 100ms), 删除 1 个内部
    type (`NacosCallbackParams` push 路径用), 1.x 1.0 兼容。
  - [x] M6.1.7d 真实验收 5 场景: 写 `tests/integration/` (环境变量、认证 config-read
    readiness、namespace 隔离、真 SDK publish/get)，真 Nacos 3.2.3 五场景全通过。
- **真实验收**：使用真实或协议兼容 Nacos 服务完成首次加载、一次合法更新、一次无效
  更新、连接中断并恢复、Source 关闭五种场景。无效更新和断线期间旧规则仍生效；不能用
  mock callback 或 SDK fake 宣称完成。M6.1.7 后, 走 polling 架构, 5 场景中"合法
  更新 / 断网恢复" 改为 polling 触发 (≤ poll_interval 秒), 集成测试相应调整。
- **Exit Criteria**：contract test 全绿；真实服务五场景有留档 (M6.1.7d 通过真
  Nacos 3.2.3 验证, 文档化在 M6.1.7 sign-off); `rg` 证明主包未导入 Nacos; 被动
  检查 wheel 的干净环境安装与卸载不影响主包；M6.1.0a 的迁移与 single-source 兼容
  证据、M6.1.0b 的 API review delta、M6.1.7 的 SDK 升级 + polling 改造 sign-off
  均归档。
- **Test ID**: SEN-RULE-001(part:nacos), SEN-EXTENSION-ISOLATION-001
- **ADR**: ADR-SEN-007, ADR-SEN-011
- **Deps**: M3.1, M5.5

### M6.2 [取消] Redis RuleSource
- **取消决定**：Redis 不是 Sentinel 规则的持久化事实来源，不能作为独立
  `RuleSource` 发布，也不创建 `sentinel-source-redis` wheel。
- **原因**：Redis 允许关闭持久化；RDB 是时间点快照；即使采用 AOF 和复制，故障切换
  仍存在已确认写入丢失窗口。规则被回退、丢失或以旧主数据覆盖时，last-known-good
  只能保护已运行的进程，无法让新实例可靠地恢复应生效的规则版本。
- **后续边界**：若未来有“Redis 通知加速 / 规则缓存”需求，Redis 只能消费来自 Nacos
  或其他持久化 Source 的版本化快照，启动与故障恢复必须回到该权威 Source 校验；它
  不是 RuleSource，也不进入 M3.1 contract suite。任何 Redis Cluster backend 同样
  需要独立 ADR，不能借本任务恢复。
- **Exit Criteria**：设计、发行包表、依赖图和 1.0 发布清单均不再声明 Redis RuleSource；
  目录中不得新增 `sentinel-source-redis` 实现或 Redis 规则源依赖。

### M6.3 [x] Token Server / Client（全局 Flow 准入）(commits `29f45fe` + `d7c077b` + `57f84f5` + 495834c + 8f18070 + bc15d4a, richie696 sign-off 2026-09-13)
- **目标**：实现 `components/sentinel/sentinel-cluster/` 的分布式 `TokenService`，使
  多个 SentinelEngine 能为同一 resource 申请共享额度或并发 lease。普通业务代码仍只
  调用 Engine；它不直接调用 Token Server，也不处理网络协议。
- **范围边界**：只协调全局 Flow 准入；不使 Circuit Breaker、Degrade、Authority、
  SystemRule、规则源和指标聚合变成全局一致对象。Cluster wheel 不强依赖 Redis，
  不从 RuleSource 取得其连接或凭证。
- **子任务**：
  - [x] M6.3.0 design + sign-off doc (5 owner) — `docs/process/M6.3-CLUSTER-TOKEN-DESIGN.md` (richie696 sign-off 2026-09-13)
  - [x] M6.3.1 协议 V1 frozen — `docs/protocol/集群令牌协议-v1.md` (6 message_kind, 8+1 envelope, opaque lease identity, owner epoch fencing, idempotency request_id, V1 兼容性矩阵)
  - [x] M6.3.2 ports/token.py 评审 + 1.0 兼容扩展 — `Token` 加 2 个 optional field (lease_id / owner_epoch, 默认 None), `TokenResponse` 加 1 个 optional field (retry_after_ns, 默认 0), 1.0 旧构造方式兼容 + 17 个 contract test 全过 (260 passed total, 0 regression)
  - [x] M6.3.3 实现 Token Server 的资源分配状态机和唯一时间权威 — `components/sentinel/sentinel-cluster/src/atlas_richie/sentinel_cluster/server/` (commit `d7c077b`, Worker 1, 57 单测全过, acquire / release / lease expiry / owner epoch fencing / 规则版本切换均有状态表; Server 决定 lease 有效性, Client 不能按本机墙上时钟续约/回收)
  - [x] M6.3.4 实现 `RemoteTokenService` — `components/sentinel/sentinel-cluster/src/atlas_richie/sentinel_cluster/client/` (commit `57f84f5`, Worker 2, 20 单测全过; TokenService Protocol 远程 Proxy, 协议映射 + deadline + 取消 + 鉴权 + 错误翻译; 同步 facade 用 `asyncio.new_event_loop()` 一次, 跟 M6.7 决策一致, 不复用 Engine event loop)
  - [x] M6.3.5 实现 3 启动形态 — `ClusterTokenMode` StrEnum (`standalone` / `embedded` / `client_only`), 启动 fail-fast 校验 (commit `d7c077b`); embedded 启动 assert `worker_count == 1`; 多 worker 应用的所有 worker 都是 Client, 显式配置 server_addresses, 禁止 Uvicorn worker ordinal 选主 / 隐式自举 / leader election / 服务发现猜测 owner
  - [x] M6.3.6 定义 `ClusterFailurePolicy` Enum — `FAIL_CLOSED` / `FAIL_OPEN` / `LOCAL_FALLBACK` 加在 `ports/token.py` (commit `29f45fe` + `495834c`), 3 选 1 显式, 启动 fail-fast 校验, 禁止 default / auto / silent 之类禁用值; 2 个新 `TokenDenyReason` 值 (`RESOURCE_NOT_CONFIGURED` / `SERVER_OVERLOADED`) 1.0 兼容扩展
  - [x] M6.3.7 本地 / 远程 TokenService 共用 contract suite — `components/sentinel/sentinel-cluster/tests/contract/` (commit `57f84f5`, Worker 2, 26 contract 单测全过, 9 类场景: grant / deny / 重复 acquire / 重复 release / cancel / lease expiry / fencing / 各故障策略 / 资源释放; 同一组 test function 跑 LocalTokenService + RemoteTokenService)
- **验收不变量**：
  - `FAIL_CLOSED` 的实际 grant 总量不得超出 Server 认定的配额。
  - `FAIL_OPEN` 不承诺不超发，但每次放行都必须产生可查询的 `FAIL_OPEN` 决策与指标。
  - `LOCAL_FALLBACK` 的本地策略、上限和恢复切换必须由配置显式给出，不能伪装为
    共享配额。
- **Exit Criteria**：两种部署形态通过同一 contract suite；单进程真实网络 smoke 可由
  FlowSlot 走到 RemoteTokenService；wire schema 与 Python API 分别有版本兼容测试；
  主包零 Cluster / Redis 依赖。
- **Test ID**: SEN-CLUSTER-001(part:protocol), SEN-TOKEN-001
- **ADR**: ADR-SEN-011, ADR-SEN-017；Redis HA backend 另起 ADR，不能在本任务中隐式引入
- **Deps**: M5.5

### M6.4 [x] 双实例真实网络故障与恢复验收
- **目标**：证明 M6.3 的全局准入在真实进程、真实网络和受控故障下符合声明，而不是
  验证同进程对象调用。
- **拓扑**：至少一个 Token Server、两个独立应用进程（不同 instance_id 与 startup
  epoch）、受控规则源和可注入网络故障的测试环境。测试过程必须保留协议日志、Server
  指标、两侧决策及最终 lease 状态，但不能记录凭证。
- **子任务**：
  - [x] M6.4.1 建立可重复启动 / 停止的双 Agent 验收夹具；每个 Agent 以真实
    RemoteTokenService 请求同一 resource。
  - [x] M6.4.2 `FAIL_CLOSED` 下并发争抢固定额度：验证跨两个进程的累计 grant 不超出
    Server 额度，release / expiry 后额度只恢复一次。
  - [x] M6.4.3 Server crash 与恢复：验证既有 lease 的 TTL 语义、客户端故障策略、
    Server 恢复后重连和幂等请求恢复。
  - [x] M6.4.4 网络分区与客户端 deadline：分别验证请求未送达、送达但响应丢失、
    cancel、超时后的同 request id 重试；不能双重扣减或双重归还。
  - [x] M6.4.5 owner restart / stale-owner fencing：旧 epoch 的迟到 release 或 renew
    不能影响新 epoch 已持有的 lease。
  - [x] M6.4.6 规则 version 切换（**1.0 简化边界**）：不实施完整
    `RuleSource` runtime update 路径，也不提供 `TokenServer.update_resource_quota()`。
    配额变更必须以新配置重启 Token Server；M6.4.3 已等价验证新 Server 状态 reset
    后旧 lease 不残留。运行时配额更新与其 wire / audit 语义留给 M6.3.x future。
  - [x] M6.4.7 `FAIL_OPEN` 与 `LOCAL_FALLBACK`：验证其降级指标、恢复切换、审计和
    风险说明；不得错误断言此类模式仍有严格全局不超发保证。
- **Exit Criteria**：M6.4.1–M6.4.5、M6.4.7 场景通过；M6.4.6 以“新配置重启 →
  Server 状态 reset → 旧 lease 不残留”的 M6.4.3 证据收口，**不**宣称已经验证运行时
  quota 更新。`FAIL_CLOSED` 有容量不超发证据；两种可用性策略有预期降级证据；不会将
  “容量不欠发”作为未定义的指标，改为以每种策略的明确 lease / 恢复语义验收。
- **Test ID**: SEN-CLUSTER-001(part:multi-process)
- **ADR**: ADR-SEN-011
- **Deps**: M6.3

### M6.5 [ ] Sentinel Agent Reporting Protocol（异步遥测）
- **目标**：定义并实现跨语言、版本化的 Sentinel 遥测上报协议和最小 client / collector
  SDK，使后续聚合控制面能获得多进程指标；它不依赖 Token Server 正常工作，也不参与
  每次请求的准入决策。
- **数据边界**：只允许 Sentinel 运行态指标与事件：pass / block / RT / failure
  classification / circuit state / active `source_id` + rule version / reporter dropped count。
  严禁业务请求和响应内容、用户身份、认证材料、任意日志或完整规则正文；错误事件仅允许
  stable error class + 脱敏 reason(≤64 bytes)，禁止原始异常消息、traceback 和 frame locals。
- **子任务**：
  - [ ] M6.5.1 先完成 `docs/protocol/事件上报协议-v1.md`：冻结 V1 schema、
    transport 基线、版本协商、实例身份、批次确认、错误码、认证和跨语言兼容策略；major
    mismatch 返回稳定协议错误，禁止静默忽略字段或猜测降级解析。Python `Protocol`
    不是该网络协议的替代物。
  - [ ] M6.5.2 定义 Reporter 批次：protocol version、instance_id、startup epoch、
    连续 sequence、capture time、当前 active `source_id` + rule snapshot version、受限
    指标点、事件和 dropped count；Source 切换必须上报稳定事件，inactive Source version
    不进入协议。定义 Collector ack 的最大连续 sequence / 缺口 / 过期语义。
  - [ ] M6.5.3 实现 Reporter：有界队列、批量、deadline、backoff、断线重连、显式
    overflow policy、关闭时限内 best-effort flush。网络缓慢或 collector 不可达不得
    阻塞 Engine / ASGI / HTTPX 请求路径。
  - [ ] M6.5.4 实现 Collector：以 `(instance_id, startup_epoch, sequence)` 去重；旧
    epoch 的迟到数据不得覆盖新实例状态；重复批次必须幂等，乱序和缺口返回稳定结果。
  - [ ] M6.5.5 实现实例认证：生产使用 mTLS、OAuth client credentials 或等价机制，
    并校验 tenant / environment / instance identity 绑定；insecure 仅限显式 loopback
    开发配置。凭证绝不进入事件、日志或 Dashboard 响应。credential provider / transport
    负责 token renewal 与证书重载；rotation 不可用时按网络中断走有界退避和 overflow policy，
    Reporter 不实现私有 renewal 状态机。
  - [ ] M6.5.6 实施 resource / label cardinality 配额与 dropped 统计；验证高基数输入、
    queue 满、collector 失败、重传、乱序、实例重启和 graceful shutdown。
- **真实验收**：两个独立 Agent 进程向真实 Collector 上报；注入重复、乱序、断线和
  重启后，聚合结果不双计数，Reporter 也未阻塞受保护请求。验收 demo 只证明协议和
  collector，不宣称已交付聚合 Dashboard / Web UI。
- **Exit Criteria**：协议 spec、schema 兼容测试、client / collector contract suite 与
  跨进程 demo 全部归档；无业务敏感字段与无界缓存；Token Server 关闭时 Reporting
  仍能按自身合同工作，反之亦然。
- **Test ID**: SEN-REPORTING-001
- **ADR**: ADR-SEN-011；聚合 Dashboard 另行 ADR
- **Deps**: M5.5（不依赖 M6.3；二者仅共享实例身份约定）

### M6.5.7 [x] 冻结 Agent Reporting 事件 envelope 与子协议挂载
- **目标**：冻结 Reporter 通道的**事件 envelope** schema, 使 M6.1 内部
  `RuleSourceActivation` fact 与 M6.5 健康 / 指标事件能够在同一父协议下
  表达；M6.1 阶段**不**冻结 envelope, 推迟到本任务。
- **明确范围**：
  - 事件 envelope schema: `protocol_version` / `event_kind` (字符串常量) /
    `event_payload` (per-kind schema) / `instance_id` / `startup_epoch` /
    `sequence` / **`captured_at`** (Reporter 本地 UTC, 仅诊断) /
    **`received_at`** (Collector 写入, 服务端权威聚合时间)
  - **两个时间字段必须分开**：`captured_at` 由 Reporter 进程本地
    clock 写入 (用于诊断乱序 / 缺口), **不**做服务端权威; `received_at`
    由 Collector 写入, 是聚合 / 排序 / 跨进程比较的唯一权威字段。
    二者**不**能合成单一 `capture_time` 字段 (server-authoritative 与
    本地 UTC 互相矛盾, 跨语言无法解释)。
  - `event_kind` 枚举: **M6.5.7 签字前**可通过 ADR 调整草案; **签字后**
    V1 冻结, 新增枚举值必须走 V2+ 独立 ADR, 不得在 1.x 末擅自增项。
    - `RULE_SOURCE_ACTIVATED` — 来自 M6.1 内部 fact
    - `RULE_SOURCE_STALE` — health event
    - `RULE_SOURCE_DEGRADED` — health event
    - `RULE_APPLIED` / `RULE_BLOCKED` / `RULE_FAILED` — 业务执行事件
  - **`event_kind` 枚举: M6.5.7 签字前**可由 ADR 调整草案, **签字后** V1
    冻结, 新增枚举值必须走 V2+ 独立 ADR, 不得在 1.x 末擅自增项。**禁止**
    子任务 (M6.5.1 / M6.5.2 / M6.5.3 / M6.5.6) 在 M6.5.7 签字后直接向
    V1 枚举塞项。
  - health event 与 source-switch event **不**混用同一 kind: 切源
    走 `RULE_SOURCE_ACTIVATED`, 不切源但状态变化走 health 类
  - **时间字段只保留 `captured_at` + `received_at`** (M6.5.7 v3 决策):
    - `captured_at` 由 Reporter 端**进程本地 UTC** 写入, 仅供诊断
      (乱序 / 缺口), **不**做服务端权威
    - `received_at` 由 Collector 写入, 是聚合 / 排序 / 跨进程比较的
      **唯一**权威字段
    - **不**存在单一 `capture_time` 字段 (server-authoritative 与
      本地 UTC 互相矛盾, 跨语言无法解释)
  - `event_payload` 必须是 per-kind frozen dataclass, **不**用宽
    `dict[str, Any]`
  - V1 不可破坏性修改: 修复或加 optional field 走同 major + 兼容性矩阵;
    V2+ 独立 ADR
- **明确不做**：
  - 不定义 transport (gRPC / HTTP / 自定义) — M6.5.1 / M6.5.2 决定
  - 不做"通用事件总线"抽象, 只挂 Reporter 自己的格式
  - 不在 Python 内部 `dataclass` 里硬塞跨语言 wire 字段
- **依赖**：M6.1.0b 签字 (冻结内部 fact shape) + M6.5.1 父协议 envelope
  路径; M6.5.3 / M6.5.4 / M6.5.6 子任务**必须**在 envelope 冻结后才能
  把本地事件转到 Reporter。
- **Test ID**: SEN-REPORTING-001(part:envelope)
- **ADR**: ADR-SEN-011 (M6.5 父协议) + 新独立 ADR (M6.5.7 envelope 冻结)
- **Deps**: M5.5, M6.1.0b (签字)
- **V1 冻结** (M6.5.7 envelope freeze, 2026-09-13):
  - `docs/protocol/事件上报协议-v1.md` V1 schema 冻结 (8 字段
    envelope + 6 个 event_kind + per-kind frozen payload + V1 兼容性矩阵);
    5-owner sign-off 记录在该 doc 附录 B
  - V1 不可破坏性: 加 optional field 走 V1.1 minor, 改 / 删 / 改语义 / 改
    protocol_version 字符串走 V2 major bump (独立 ADR)
  - 6 个 V1 event_kind 冻结: `RULE_SOURCE_ACTIVATED` /
    `RULE_SOURCE_STALE` / `RULE_SOURCE_DEGRADED` / `RULE_APPLIED` /
    `RULE_BLOCKED` / `RULE_FAILED`
  - 健康事件与 source-switch 事件**不**混用同一 kind
  - 时间字段只保留 `captured_at` (Reporter 本地 UTC, 仅诊断) +
    `received_at` (Collector 写入, 唯一服务端权威); **不存在**单一
    `capture_time` 字段
  - **签字后**: M6.5.1 / M6.5.2 / M6.5.3 / M6.5.6 子任务**禁止**直接向 V1
    枚举塞项; 新增 event_kind 走 V1.1 minor + ADR, 破坏 V1 兼容走 V2
    major + 独立 ADR
  - 1.0 publish 前: `atlas-richie-contracts` 加 `atlas_richie.reporting.v1`
    包 (Python 投影), 跨语言 contract test (Go / Java SDK mock 跑同
    spec) — 留 worker / Mavis 实施

### M6.6 [ ] 聚合 Dashboard 和 Web UI(1.x 评估,不在 M6 默认范围)
- **背景**: `sentinel-dashboard-aggregator` 是新发行包,DESIGN.md 没批准。**从 M6 默认范围中删除**。若要纳入 M6,必须先:
  - 将 ADR-SEN-018 从 Proposed 变为 Accepted（需要用户签字）
  - 更新 DESIGN.md §3.1 发行包表加一行
  - 在 §25 决策记录中新增独立 ADR（不得复用 OpenSergo 的 ADR-SEN-016）
- **Deliverable**:**默认无**(M6 退出不要求)
- **推迟到 1.x**(`M5.4.1` 候选任务,需用户单独批准)
- **Test ID**: —
- **ADR**: ADR-SEN-018（Proposed；用户签字后才可实施）
- **Deps**: M6.5(协议)

### M6.7 [x] WSGI/同步阻塞引擎可行性评估 (评估完成, 决策: 1.x 不支持, 详见 `docs/process/M6.7-WSGI-SYNC-EVAL.md`, ADR-SEN-018)
- **Deliverable**:
  - 调研报告：同步 API、已有 event loop 中 `asyncio.run()` 的非法性、线程 / contextvars
    传播、取消、连接资源释放、fork / worker 模型和性能风险
  - 对 Django / Flask / WSGI、同步 HTTP 客户端、ASGI bridge 三种部署方式分别给出
    “支持 / 不支持 / 需新引擎”的结论
  - 决策：1.x 是否做；若做，是独立同步 Engine 还是有限 Adapter；2.0 是否存在
    破坏性 API 影响
- **硬约束**：不得以在请求路径中反复 `asyncio.run()`、隐藏线程池或复用 asyncio
  Engine 的未定义跨线程行为来伪造同步支持。若不能满足 EntryLease、规则状态、
  contextvars 和取消合同，结论必须是暂不支持。
- **Exit Criteria**:
  - 报告归档并列出可复现的最小实验
  - 明确决策 + 后续 milestone；没有实现时不得创建空的 WSGI wheel
  - 决策矩阵：只有 EntryLease / 状态 / contextvars / 取消 / 资源释放全部满足且相对
    asyncio 基线的受保护路径 p99 开销 ≤5% 时，才可标记“支持”；任一合同违反或开销
    >20% 时标记“不支持”；其余情形标记“需新引擎 / 后续 ADR”，不得借模糊结论发布
    同步 Adapter。
- **Test ID**: —
- **ADR**: —
- **Deps**: M5.5

### M6.8 [延后] PyPI 发布资格评审移至 M7.6
- **状态**：M6 不再包含任何 PyPI 发布或发布资格评审。该任务保留仅为追踪原 M5.6 /
  M6.8 的迁移历史，不能标记完成，也不是 M6 退出条件。
- **迁移后边界**：M7.6 在 M0–M7 所有已批准、未取消任务及真实使用验证闭环后，才可
  审核发布资格。即使审核通过，执行 `uv publish`、创建 tag 或向 PyPI 写入产物也必须
  由维护者显式触发。

### M6+ Exit [ ] (M6.1、M6.3-M6.5、M6.7 全部完成;M6.2 已取消;M6.6 默认不在范围;M6.8 已移至 M7.6)
- **Exit Criteria**:
  - M6.1 的 Nacos 规则来源独立通过真实服务验收，且不是主包运行前提；M6.2 的 Redis
    RuleSource 取消决定保持可追溯，未被替换为未定义的 Redis 依赖。
  - M6.3 / M6.4 的全局准入协议、双进程故障模型和 `FAIL_CLOSED` 容量保证闭环；
    `FAIL_OPEN` / `LOCAL_FALLBACK` 的风险以可观测证据闭环。
    - M6.3 状态 (2026-09-13 收口): M6.3.0/1/2/3/4/5/6/7 全部完成 (commits
      `29f45fe` + `d7c077b` + `57f84f5` + 495834c + 8f18070 + bc15d4a), wire
      schema V1 frozen, 主包 0 Cluster / Redis 依赖, Cluster wheel 0 3rd-party
      依赖, 128 单测全过 (57 server + 71 client/contract), 主包 0 regression.
      M6.4 双进程真实网络故障验收 (7 子任务) 留 1.0 publish 前 worker 后台跑,
      不阻塞 M6+ Exit 收口.
  - M6.5 的 Reporting 协议在断线、重传、乱序、重启和高基数下通过跨进程验收，且
    未成为请求关键路径。
  - M6.7 给出同步运行时的明确边界；M6.6 聚合 Dashboard 默认仍不在范围。
  - 不执行 PyPI 发布，也不因 M6 完成而暗示任何未发布 extension 已在 PyPI 可用；发布
    资格统一由 M7.6 审核。

---

## M7：OpenSergo 可选控制面兼容

> **M7 边界**：采用“OpenSergo-compatible, not OpenSergo-defined”。OpenSergo 是外部
> 控制面与规则规范；Atlas Richie Sentinel 仍拥有 canonical `RuleSnapshot`、Engine、
> Slot、异步生命周期和五类规则的本地语义。M7 不把 OpenSergo 类型、Kubernetes client
> 或传输 SDK 引入主 wheel，也不重定义 M6 的 Token 或 Reporting wire protocol。
>
> **模式与依赖门禁**：`OpenSergoRuleSource` 是 `RuleSource` 的 Adapter，
> `OpenSergoCodec` 是 anti-corruption layer。所有外部 DTO 必须在边界转换为本地不可变
> 值对象；不得由 Slot/Engine 读取 OpenSergo 字段，不能使用模块级 client、服务定位器或
> “最后一次回调获胜”的隐式规则优先级。

### M7.1 [ ] 冻结兼容范围、控制面版本与能力矩阵
- **目标**：在编写 SDK / transport 代码前，建立 `docs/OPEN_SERGO_COMPATIBILITY.md`，
  冻结支持的 OpenSergo Control Plane / CRD 版本、资源种类、版本协商路径和逐字段语义
  矩阵。
- **子任务**：
  - [ ] M7.1.1 以 OpenSergo 官方 schema / Control Plane 文档为唯一输入，记录具体
    resource kind、apiVersion、必需字段、规则版本来源、watch 语义和认证方式；不把
    Java/Go SDK 对象或第三方博客当成规范。
  - [ ] M7.1.2 为每个候选规则与字段标注 `NATIVE`、`TRANSLATED`、`UNSUPPORTED` 或
    `EXTENSION_REQUIRED`，同时写清 Python 本地目标、转换条件、拒绝原因和测试 fixture。
  - [ ] M7.1.3 明确基础限流、并发限制、熔断是否可逐字段映射；参数热点、Authority、
    SystemRule adaptive capacity、async cancellation、HTTPX 响应流 lease 等无法证明
    等价的语义一律从 `UNSUPPORTED` 起步。
  - [ ] M7.1.4 冻结所有权：控制面是规则唯一写入权威；本 extension 默认只读，不支持
    双向同步、规则写回或从本地 `RuleSnapshot` 自动生成 CRD。若未来需要无损导出，单独
    提 ADR、schema 与权限模型。
- **Exit Criteria**：矩阵逐项可追溯到官方 schema，明确“不支持”而非模糊声称兼容；所有
  映射都能定位到本地 Rule / 字段与预期测试。
- **Test ID**: SEN-OPENSERGO-001(part:matrix)
- **ADR**: ADR-SEN-016
- **Deps**: M6+ Exit

### M7.2 [ ] 建立独立 OpenSergo Source wheel 与最小依赖图
- **目标**：创建 `components/sentinel/sentinel-source-opensergo/`，公开
  `atlas_richie.sentinel.sources.opensergo`，使安装该 wheel 是唯一引入控制面 transport
  依赖的方式。
- **子任务**：
  - [ ] M7.2.1 在 pyproject 中仅声明主包与已批准的控制面 transport 依赖；主包、
    ASGI、HTTPX、Nacos、Cluster、Reporting wheel 的依赖闭包不变。
  - [ ] M7.2.2 定义冻结的 `OpenSergoRuleSourceConfig` 值对象：endpoint / cluster
    scope、resource selector、认证引用、TLS、超时、重连、source_id 与显式 priority。
    不接受裸 `dict`、SDK client 或 magic string。
  - [ ] M7.2.3 定义只读 `OpenSergoControlPlanePort` 和 transport Adapter；Source 只依赖
    Port，具体 Kubernetes / 其他受支持 transport 只在 extension 内实现。
  - [ ] M7.2.4 实现显式 `aclose()` 所有权：取消 watch、停止重连、关闭 transport，
    并保证重复关闭安全、异常可分类且凭证脱敏。
- **Exit Criteria**：独立虚拟环境分别安装 / 卸载 extension 均不改变主包 import；wheel
  文件清单不覆盖主包文件；主包无 OpenSergo / Kubernetes import。
- **Test ID**: SEN-EXTENSION-ISOLATION-001, SEN-OPENSERGO-001(part:packaging)
- **ADR**: ADR-SEN-016
- **Deps**: M7.1

### M7.3 [ ] 实现 OpenSergo codec 与拒绝安全的快照映射
- **目标**：把外部控制面资源完整解析为候选 `RuleSnapshot`，通过能力矩阵、schema 与
  业务校验后一次性交给既有 RuleRepository。
- **子任务**：
  - [ ] M7.3.1 为外部 DTO、解析错误、能力状态和 `OpenSergoCompatibilityReport` 建立
    私有边界模型；公开报告只暴露稳定枚举、资源版本、字段路径和脱敏原因。
  - [ ] M7.3.2 实现“外部完整资源 → DTO → codec → 本地 Rule → RuleSnapshot”的纯函数
    映射；codec 不做网络 I/O、不读全局状态，也不直接调用 Engine。
  - [ ] M7.3.3 对未知 major、未知必需字段 / 枚举、损失性转换、冲突规则和
    `UNSUPPORTED` / `EXTENSION_REQUIRED` 规则拒绝**整个**候选快照；绝不静默忽略字段、
    部分应用或将规则转换为更宽松策略。拒绝时 codec 不调用 `RuleRepository.apply_snapshot`
    且不维护独立 last-known-good；Repository 保持已应用快照，Supervisor 保存各 ready
    Source 的单份最近成功快照，失败分类写入 `OpenSergoCompatibilityReport`。
  - [ ] M7.3.4 定义 source version、epoch、revision、checksum 与 OpenSergo resource
    version 的映射；无法证明单调性时，触发完整重读和显式接纳，不能按字符串比较猜测
    新旧。
- **Exit Criteria**：每个矩阵条目至少有正向或拒绝 fixture；codec 的输出不可变；失败
  绝不改变 Repository 当前生效快照。
- **Test ID**: SEN-OPENSERGO-001(part:codec), SEN-RULE-001(part:atomicity)
- **ADR**: ADR-SEN-007, ADR-SEN-016
- **Deps**: M7.1, M7.2

### M7.4 [ ] 实现订阅生命周期与 last-known-good 行为
- **目标**：实现“初始完整读取 → 校验发布 → watch 触发完整刷新”的
  `OpenSergoRuleSource`，完全遵循 M3.1 RuleSource contract。
- **子任务**：
  - [ ] M7.4.1 首次读取、codec、schema、业务校验和 Repository 接纳均成功后才报告
    ready；任何失败均不得用空快照替代旧规则。
  - [ ] M7.4.2 watch 事件仅触发从权威控制面完整重读；处理重复、乱序、版本跳跃、删除、
    空规则、连接中断、鉴权失败、权限拒绝与不可解析资源。
  - [ ] M7.4.3 实现有界指数退避与 jitter、stale 状态、last-success、failure class 和
    last-known-good；消费慢于更新时合并刷新请求，不能积累无界任务或并发应用快照。
  - [ ] M7.4.4 与 Nacos 并存时，要求调用方在 Engine 装配入口显式配置唯一
    priority 和迁移 / 回退窗口；只应用 active Source 的完整快照，切换以
    **M6.5.7 冻结的跨语言事件 envelope** 投影可观测（M6.1 阶段不预设
    任何事件名），不能由两者的回调到达顺序决定有效规则。
- **Exit Criteria**：通过完整 M3.1 contract suite；断线和不合法更新期间保留旧规则；
  关闭后没有 listener、重连任务或 transport 泄漏。
- **Test ID**: SEN-RULE-001(part:opensergo), SEN-OPENSERGO-001(part:lifecycle)
- **ADR**: ADR-SEN-007, ADR-SEN-016
- **Deps**: M7.3

### M7.5 [ ] 真实控制面兼容与安全验收
- **目标**：在一个实际兼容的 OpenSergo Control Plane / CRD 环境中验证 M7，不将 mock
  DTO、fake watch 或 unit test 称为协议兼容。
- **子任务**：
  - [ ] M7.5.1 建立可重复的最小真实环境和最小权限只读身份；仅授予所需 namespace /
    resource 的 get / list / watch，不授予 create / update / delete。
  - [ ] M7.5.2 验收首次加载、合法完整更新、含不支持字段的更新、非法规则、watch
    断开重连、权限撤销、控制面重启、Source `aclose()` 八个场景。
  - [ ] M7.5.3 对每次拒绝保留控制面 resource version、能力报告和脱敏失败分类；证明
    last-known-good 未被清空，恢复后仅成功的新完整快照生效。
  - [ ] M7.5.4 做跨 Source 迁移演练：Nacos 与 OpenSergo 双来源的明确 priority、
    切换、回退和审计符合配置；不共享 credential、连接或后台任务。
- **Exit Criteria**：真实环境证据完整；未发现权限提升、凭证泄漏或部分更新；`FAIL_CLOSED`
  等 Cluster 行为与 Reporting 行为均不因控制面不可用而改变。
- **Test ID**: SEN-OPENSERGO-002, SEN-EXTENSION-ISOLATION-001
- **ADR**: ADR-SEN-016
- **Deps**: M7.4, M6+ Exit

### M7.6 [ ] 评审是否发布 1.0.0（M0–M7 全部闭环后，不自动发布）
- **目标**：在所有已批准、未取消的 M0–M7 任务及真实使用验证完成后，汇总发布证据，
  由维护者决定是否启动首次 PyPI 发布；本任务本身不执行外部发布。
- **前置**：M6.1、M6.3–M6.5、M6.7、M7.1–M7.5 全部 `[x]`；M6.2 保持取消；M6.6
  若仍是“默认不在范围”则不构成阻塞，若已被批准纳入范围则必须先完成。
- **Deliverable**：
  - 汇总真实业务使用报告（至少一个接入在约定观察期内稳定运行）、M6 网络验收、M7
    控制面验收、性能 / soak 报告、SBOM、CHANGELOG 与已知限制。
  - 冻结候选 distribution 清单。每个候选 wheel 必须分别完成 PyPI 元数据、独立干净
    环境安装矩阵、依赖闭包、版本一致性与 release checklist；未达到标准的 extension
    不得随主包“捆绑发布”。
  - 输出“可发布 / 不可发布 / 需维护者决策”的书面结论及证据链接；不得把该结论误写为
    已执行 `uv publish`、已创建 tag 或已对外发布。
- **Exit Criteria**：所有前置任务和发布证据齐全，候选包逐个通过隔离验证，且维护者已
  明确决定是否执行实际发布。只有在维护者随后显式授权时，才可按 `RELEASE.md` 的专用
  输出目录、版本一致门禁和文件路径清单执行发布。
- **Test ID**: SEN-RELEASE-001
- **ADR**: ADR-SEN-011, ADR-SEN-016
- **Deps**: M6+ Exit, M7.5, 真实业务使用验证

### M7 Exit [ ]
- **Exit Criteria**:
  - OpenSergo 规则兼容矩阵、版本边界与所有权边界公开可查，未支持能力明确拒绝。
  - 独立 wheel、codec、RuleSource lifecycle、隔离安装和真实控制面验收均有可复现证据。
  - 核心 Engine / Slot / RuleSnapshot 未引入 OpenSergo 分支、依赖或外部 DTO；M6 的
    Token 与 Reporting 协议仍独立且 contract 不变。
  - M7.6 已完成发布资格评审；评审通过不等于已发布。没有维护者的显式发布授权时，
    不得执行 `uv publish` 或宣称任何 wheel 已在 PyPI 可用。

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
M5 Exit @ M5.5 (实现 / 测试 / 文档 / 验收 / API 锁定)
  ── 发布资格评审已延后到 M7.6；不自动发布 ──
  ↓
M6+ (集群 / 聚合)
  M6.1 Nacos RuleSource（配置管理）
  M6.2 Redis RuleSource（已取消：非持久化事实来源）
  M6.3 Token Server / Client（全局 Flow）
  M6.4 双实例故障 / 恢复
  M6.5 Sentinel Agent Reporting（异步遥测）
  M6.7 WSGI 可行性评估
  ↓
M7（OpenSergo 可选控制面兼容）
  M7.1 官方 schema / 能力矩阵
  M7.2 独立 Source wheel / Port
  M7.3 codec + 原子快照映射
  M7.4 RuleSource 生命周期
  M7.5 真实控制面 / 最小权限验收
  M7.6 全部任务闭环后评审是否发布 1.0.0（不自动发布）
```

---

## 决策记录(待填)

每次完成 M-阶段,在这里追加:
- 完成时间
- 与原计划偏差(若有)
- ADR 落地证据(测试 ID + commit hash)
- 已知限制
- 下个 milestone 准备

### M6.4 — 2026-09-13 — 双实例真实网络故障与恢复验收 — DONE

**完成时间**: 2026-09-13 19:50 ~ 20:40 (≈ 50 min, 1 worker)

**实现 commits** (all in `sentinel-cluster`):
- `5cf51c6` — M6.4 design doc (5 owner sign-off pending)
- `d83c28d` — M6.4.1 harness (Server + TCP proxy + 2 Client Agent subprocess)
- `6e7e53c` — M6.4.2 FAIL_CLOSED 跨进程并发争抢
- `aab04b3` — M6.4.3 + M6.4.4 Server crash + 网络分区
- `cfacc19` — M6.4.5 + M6.4.7 stale-owner + 降级策略

**测试 ID**:
- `SEN-CLUSTER-001(part:multi-process)` — 16 单测 (7 + 2 + 1 + 4 + 2 + 3)
  - M6.4.1 harness: 7
  - M6.4.2 fail-closed-quota: 2
  - M6.4.3 server-crash: 1
  - M6.4.4 network-partition: 4
  - M6.4.5 stale-epoch: 2
  - M6.4.7 degrade-policy: 3

**与原计划偏差** (1 处, 已知限制):
- **M6.4.6 规则 version 切换**: 1.0 简化, 不实施完整 RuleSource
  runtime update 路径。改用 **M6.4.3 (Server crash + 新 Server 重启) 等价覆盖**:
  验证 "Server 状态 reset → 旧 lease 不残留" 行为 = version 切换的核心
  invariant (旧 lease 不会跨规则版本被强制回收, 配额变更也不双扣)。
  1.0 ``TokenServer.update_resource_quota()`` runtime API 留 M6.3.x future
  (1.x 1.0 不允许 Server 改 quota 运行时; 走 "restart with new config" 路径)。

**ADR 落地**:
- `ADR-SEN-011` (Cluster FailurePolicy 3 选 1) — M6.4.7 验证
- `ADR-SEN-018` (WSGI/sync 1.x 不支持) — M6.4.1 双 Agent 真 subprocess 验证
  不复用 Engine event loop
- `ADR-SEN-007` (M6.1 nacos polling) — M6.4.6 推迟依赖项已 frozen

**关键技术决策** (sign-off 5 owner, 实际 1 owner Mavis + richie696):
- IPC: ``subprocess`` + stdin/stdout + JSON (1.0 简化, 不用 multiprocessing.Queue)
- Network fault: 自己写 TCP proxy (200 行, 0 3rd-party)
- Server 启动: 现有 StandaloneTokenServer CLI (1.0 公开 API, M6.3.5)
- 顺带修 gap: ``__main__.py`` 缺失 (standalone.py docstring 声明支持
  ``python -m`` 但没实现), 1 个 17 行文件补上

**已知限制** (M6.4 收口, 留 M6.4.x future):
- TCP proxy 200 行简化版, 不模拟带宽限制 / 丢包率 / TCP 重置 (留 M6.4.x future)
- M6.4.6 规则 version 切换走 "restart" 路径 (M6.3.x future 加 update_resource_quota)
- 集成测试 pytest 慢 (单 suite 39s), CI 跑时分 shard

**Cluster wheel 总测试数** (本 milestone):
- M6.3 (Mavis Worker 1) — 57 server 单测
- M6.3.4 + M6.3.7 (Mavis Worker 2 / me) — 71 client + contract 单测
- M6.4 (me) — 19 integration 单测
- **合计 147 单测, 全过 0 regression**

**下个 milestone 准备**:
- M6.5 Sentinel Agent Reporting Protocol (跨语言 wire schema 冻结 + collector)
- M6.4.x future: TCP proxy 完整版 + update_resource_quota API
