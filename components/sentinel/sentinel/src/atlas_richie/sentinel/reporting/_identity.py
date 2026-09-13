"""Atlas Richie Sentinel — Agent Reporter Identity (M6.5.1).

中文
----
``ReporterIdentity`` 是 frozen slots dataclass, 公开 API.
拆出独立模块是为了打破 ``reporter`` 跟 ``event_builder`` 之间的
循环导入.

English
--------
``ReporterIdentity`` is a frozen slots dataclass, public API.
Extracted into its own module to break the circular import between
``reporter`` and ``event_builder``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ReporterIdentity:
    """Agent Reporter identity (frozen slots).

    中文
    ----
    - ``instance_id``: UUID v4 字符串, 进程启动时生成, 跨重启不变
      (走 ``instance_id_persistence_path`` 持久化)
    - ``startup_epoch``: int64, 跨重启单调递增 (持久化同路径);
      Reporter 内部用作 sequence 起点 + batch 身份

    English
    --------
    - ``instance_id``: UUID v4 string, generated at process start,
      unchanged across restarts (via ``instance_id_persistence_path``
      persistence)
    - ``startup_epoch``: int64, monotonically increasing across
      restarts (persisted at the same path); Reporter uses this as
      sequence base + batch identity
    """

    instance_id: str
    startup_epoch: int


__all__ = ["ReporterIdentity"]
