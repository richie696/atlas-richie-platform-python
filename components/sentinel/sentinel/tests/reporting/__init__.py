"""Atlas Richie Sentinel — Agent Reporting V1 tests (M6.5.1-6).

中文
----
Reporting V1 单元测试集, ≥ 34 个 test. **不**碰主包 Engine / Source /
Slots / Cluster / extensions, 只测新增 ``reporting/`` sub-package.

测试覆盖:

- ``test_config.py`` (3+) — frozen slots 锁死 + fail-fast 校验 + 默认值
- ``test_reporter.py`` (12+) — emit() 同步 facade + sequence 严格递增 +
  重试 + 错误码映射 + aclose() 幂等 + drain
- ``test_outbox.py`` (6+) — sequence 串行化 + overflow 3 选 1 + dropped_count
  + batch 累积触发 + 单一 identity 校验
- ``test_transport.py`` (5+) — HTTP/1.1 round-trip + token header + 401 +
  Content-Length + 4xx/5xx 区分
- ``test_event_builder.py`` (4+) — 6 个 kind 各自 1 测试
- ``test_integration_facts.py`` (4+) — activation / health / exec 集成

English
--------
Reporting V1 unit test set, ≥ 34 tests. Does not touch main-package
Engine / Source / Slots / Cluster / extensions; only tests the new
``reporting/`` sub-package.
"""

from __future__ import annotations

__all__: list[str] = []
