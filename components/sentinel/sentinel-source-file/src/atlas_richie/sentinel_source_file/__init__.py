"""Sentinel source-file wheel (M3.2) — FileRuleSource adapter.

中文
----
``sentinel-source-file`` 包装主包的 ``FileRuleSource``;**不**添加新
逻辑,只是提供一个独立的 wheel 给"只需要文件源"的用户,避免拉
整个主包 + Nacos/Redis 等其他 source。

扩展 wheel 依赖主包 ``atlas-richie-sentinel>=0.2.0,<0.3.0``;
**不**拉 pyyaml(JSON-only 时是 0 dep)。

English
--------
``sentinel-source-file`` wraps main package's ``FileRuleSource``;
**adds no new logic**, just provides a standalone wheel for "file
source only" users, avoiding pulling the whole main package +
Nacos/Redis etc.

Extension wheel depends on main package
``atlas-richie-sentinel>=0.2.0,<0.3.0``; **does not** pull pyyaml
(0 dep when JSON-only).
"""

from __future__ import annotations

from atlas_richie.sentinel.source.rule_source import FileRuleSource

__all__ = ["FileRuleSource"]
