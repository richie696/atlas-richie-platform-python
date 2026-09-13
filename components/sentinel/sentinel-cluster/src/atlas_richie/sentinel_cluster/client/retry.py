"""Atlas Richie Sentinel Cluster — Client 重试策略 (M6.3.4).

中文
----
同一 ``request_id`` 最多 retry 3 次, exponential backoff (50ms / 200ms / 1s).

**为什么 backoff 而不是恒定间隔**: Server 短时不可用 (如 GC pause / reload)
恒定间隔 retry 会放大压力; exponential backoff 给 Server 恢复窗口。

**实现要点**:

- 1.0 简化: 纯 sleep (不引入 jitter; 单测可精确验证 1.5s 总耗时)
- ``should_retry()`` 是纯函数, **不**抛异常
- **不**做跨 call 的 de-dup (每次重试用同 request_id 由调用方保证)
- 错误码映射在 ``policy.py`` 做, **不**在这里

**反例** (1.0 拒绝):

- ❌ 引入 jitter (单测难验证)
- ❌ retry 跨 call 共享 backoff 状态 (违反 stateless 原则)
- ❌ retry 4 次或以上 (server 恢复窗口足够, 多 retry 浪费)
- ❌ 用第三方 retry 库 (主包 0 依赖约束)

English
--------
Same ``request_id`` retries at most 3 times, exponential backoff
(50ms / 200ms / 1s).

Why backoff rather than constant interval: server brief unavailability
(e.g. GC pause / reload) with constant retry amplifies load; exponential
backoff gives server recovery window.

Implementation:

- 1.0 simplification: pure sleep (no jitter; unit tests can verify 1.5s
  total exactly)
- ``should_retry()`` is pure function, **does not** raise
- No cross-call de-dup (caller reuses same request_id)
- Error code mapping in ``policy.py``, **not** here

Anti-patterns (1.0 forbidden):

- ❌ Jitter (hard to test)
- ❌ Cross-call shared backoff state (violates stateless)
- ❌ 4+ retries (server recovery window suffices, more wastes)
- ❌ 3rd-party retry library (main wheel 0 deps)
"""

from __future__ import annotations

# 3 次 exponential backoff (M6.3.4 决策, IMPLEMENTATION-PLAN §1.1)
MAX_RETRIES = 3

# 退避序列: attempt 0 失败 → sleep 50ms; attempt 1 失败 → sleep 200ms;
# attempt 2 失败 → sleep 1s; attempt 3 失败 → 不再 retry (走 policy 决策).
_BACKOFF_SCHEDULE_S: tuple[float, ...] = (0.05, 0.20, 1.00)


def backoff_for_attempt(attempt: int) -> float:
    """返回第 ``attempt`` 次 retry 前应 sleep 的秒数.

    Args:
        attempt: 0-indexed retry attempt (0 = 第 1 次 retry, after first failure)

    Returns:
        sleep 秒数; ``attempt >= MAX_RETRIES`` 返回 0 (caller 不应再 retry)

    行为契约:
        - attempt=0 → 0.05s
        - attempt=1 → 0.20s
        - attempt=2 → 1.00s
        - attempt=3 → 0 (不 retry, 走 ClusterFailurePolicy 决策)
        - attempt<0 或 attempt>3 → ValueError
    """
    if attempt < 0 or attempt > MAX_RETRIES:
        raise ValueError(
            f"attempt must be in [0, {MAX_RETRIES}], got {attempt!r}"
        )
    if attempt >= MAX_RETRIES:
        return 0.0
    return _BACKOFF_SCHEDULE_S[attempt]


def should_retry(attempt: int) -> bool:
    """是否应该再 retry 一次.

    Args:
        attempt: 0-indexed retry attempt (与 ``backoff_for_attempt`` 同)

    Returns:
        True → 仍可 retry; False → 已到上限, 走 ClusterFailurePolicy
    """
    return 0 <= attempt < MAX_RETRIES


__all__ = ["MAX_RETRIES", "backoff_for_attempt", "should_retry"]
