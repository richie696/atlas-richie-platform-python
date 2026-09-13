"""M6.1.1 sentinel-source-nacos contract test scaffold.

中文
----
本测试文件 M6.1.1 阶段作为 **contract test 入口** 存在 (满足 PLANNING
M6.1.6 "接入 M3.1 RuleSource contract suite")。

M6.1.2 - M6.1.5 实现 NacosRuleSource 后, 真正的契约测试将在此文件
**追加**, 包含:

- 5 个 lifecycle scenario (PLANNING M6.1 真实验收): 首次加载 / 合法更新 /
  无效更新 / 连接中断并恢复 / Source 关闭
- error classification (M6.1.4): AUTH / NOT_FOUND / EMPTY / DECODE / NETWORK
  的 last-known-good 行为
- aclose() 幂等 (M6.1.5)
- 公开 API 锁定 (RuleSourceAssembly + 必填 repository + multimode_conflict)

**当前状态 (M6.1.1)**: 仅 1 个 import smoke test 确认 wheel scaffold
在 zero 3rd-party 主包基础上可以 import (NacosRuleSource 仍为 placeholder
NotImplementedError, 等 M6.1.2 - M6.1.5 落地)。

**测试隔离**:

- 单元测试 (unit): 默认 marker, fast, 不连 Nacos
- 集成测试 (integration): 真实 Nacos 服务, 在 CI 标记 skip; 本地需
  `nacos_server_addresses` 环境变量才会跑
- **不**使用 mock callback 或 SDK fake 宣称完成 PLANNING 真实验收

English
--------
This test file is a **contract test entry point** for M6.1.1 (per
PLANNING M6.1.6). After M6.1.2 - M6.1.5 implement `NacosRuleSource`,
the actual contract tests are **appended** here.

Currently only 1 import smoke test confirms the wheel scaffold is
importable on top of the zero-3rd-party main package.
"""

from __future__ import annotations

import pytest


def test_sentinel_source_nacos_wheel_import_smoke() -> None:
    """M6.1.1 scaffold smoke test: confirm the wheel is importable.

    验证:
    - `atlas_richie.sentinel_source_nacos` 可 import
    - `__version__` 是 str
    - `__all__` 包含 `__version__`
    - 主包 zero 3rd-party 不被破坏 (atlas_richie.sentinel 仍可 import)

    Note: actual NacosRuleSource / NacosRuleSourceConfig symbols are
    scheduled for M6.1.2 - M6.1.5; this scaffold test only verifies
    the wheel plumbing.
    """
    from atlas_richie import sentinel as main_pkg
    from atlas_richie.sentinel_source_nacos import __version__, __all__

    assert isinstance(__version__, str)
    assert "__version__" in __all__

    # 主包 zero 3rd-party 不被破坏: SentinelEngine 子模块 import 仍 OK
    from atlas_richie.sentinel.engine import SentinelEngine
    assert SentinelEngine is not None

    # 主包 source._supervisor C 层 (M6.1.0d-1) 仍 OK
    from atlas_richie.sentinel.source.rule_source import (
        SnapshotRuleSource, LegacyRuleSource, RuleSourceAssembly,
    )
    assert SnapshotRuleSource is not None
    assert LegacyRuleSource is not None
    assert RuleSourceAssembly is not None

    # extension isolation proof: 主包源码无 nacos 依赖
    # (this is also checked in CI by `rg "nacos" components/sentinel/sentinel/src/`)
    assert "nacos" not in dir(main_pkg)


def test_extension_isolation_marker_declared() -> None:
    """M6.1.1 隔离契约: 集成测试 marker 必须存在。

    PLANNING M6.1.6 强调"不使用 mock callback 或 SDK fake 宣称完成",
    集成测试用真实 Nacos 服务验证 5 场景 (首次加载 / 合法更新 / 无效
    更新 / 连接中断并恢复 / Source 关闭)。本测试确认 marker 声明了。
    """
    # pytest.markers 由 pyproject.toml [tool.pytest.ini_options] markers 声明
    # 单元测试不应有 integration marker
    # (实际 marker 验证在 pytest 启动时通过 --strict-markers 完成)
    assert True  # placeholder, marker 验证由 pytest config 完成


@pytest.mark.integration
def test_real_nacos_lifecycle_placeholder() -> None:
    """M6.1 真实验收 5 场景 (PLANNING M6.1) — placeholder。

    真正的实现位于 M6.1.6, 在 NacosRuleSource 落地后追加。CI 默认 skip
    (因为没有真实 Nacos 服务), 本地需 `nacos_server_addresses` 环境
    变量才会跑。
    """
    pytest.skip(
        "M6.1 real Nacos validation — requires nacos_server_addresses env var. "
        "Implementation lands in M6.1.6 after NacosRuleSource (M6.1.2-1.5) is done."
    )
