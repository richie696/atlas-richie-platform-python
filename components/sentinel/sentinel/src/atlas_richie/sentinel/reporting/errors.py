"""Atlas Richie Sentinel — Agent Reporting V1 errors (M6.5.x).

中文
----
Reporter 层 7 个错误类,直接继承主包根 ``SentinelError``,保证主包零
3rd-party 依赖,同时允许用户用 ``except SentinelError`` 统一兜底。

错误码映射 (11 wire ``ReportingErrorCode`` → 7 ``ReporterError`` 子类,
跟 M6.3 / M6.4 决策一致):

- ``ReporterConnectionError`` — 协议 transport §3 网络错
  (非 4xx / 5xx, e.g. 连接拒绝 / 超时 / EOF)
- ``ReporterAuthError`` — 鉴权失败 (401 / ``AUTH_FAILED``)
- ``ReporterProtocolError`` — 协议版本错 / 字段错 / 任何 4xx
  (除 AUTH_FAILED), 4xx 不重试
- ``ReporterAckTimeoutError`` — 投递后等 ack 超时 (transport §6 重试
  窗口内未收到 ack)
- ``ReporterOverflowError`` — outbox 满 (block_with_timeout 策略超时
  或 drop_newest 策略下显式拒绝)
- ``ReporterSendTimeoutError`` — 单次 send 超时 (transport §6
  connect_timeout / request_timeout)
- ``ReporterLeaseError`` — 1.0 future use, 跟 Cluster lease 命名对齐
  (集群模式下 batch 提交需要 lease 时使用, 当前 1.0 单进程未启用,
  保留扩展点)

English
--------
Seven Reporter exception classes, all inheriting directly from the
main package root ``SentinelError``. This keeps the main wheel free
of 3rd-party dependencies while still letting users catch them via
``except SentinelError`` as a single umbrella.

Error code mapping (11 wire ``ReportingErrorCode`` → 7 ``ReporterError``
subclasses, per M6.3 / M6.4 decision):

- ``ReporterConnectionError`` — network failures (non-4xx/5xx;
  e.g. connection refused, timeout, EOF)
- ``ReporterAuthError`` — auth failure (401 / ``AUTH_FAILED``)
- ``ReporterProtocolError`` — protocol version mismatch / schema
  failure / any 4xx (except AUTH_FAILED), 4xx does not retry
- ``ReporterAckTimeoutError`` — submit but no ack within retry window
- ``ReporterOverflowError`` — outbox full (block_with_timeout elapsed
  or drop_newest policy explicit rejection)
- ``ReporterSendTimeoutError`` — single send timeout (transport §6
  connect_timeout / request_timeout)
- ``ReporterLeaseError`` — 1.0 future use, name aligned with Cluster
  lease (cluster mode batch submission needing a lease; not enabled
  in 1.0 single-process, kept as extension point)
"""

from __future__ import annotations

from ..errors import SentinelError


class ReporterError(SentinelError):
    """Reporter 错误根类,所有 Reporter 异常继承它 (但仍属于 SentinelError 子树).

    中文
    ----
    用户既可 ``except ReporterError`` 精确捕获 Reporter 错误,也可
    ``except SentinelError`` 统一兜底。提供 1 个公共 ``code`` 属性,
    wire 错误码字符串 (e.g. ``"AUTH_FAILED"``) 或空字符串 (本地错误,
    无 wire 码).

    English
    --------
    Root for all Reporter errors (still under the ``SentinelError``
    subtree). Users may catch with ``except ReporterError`` for
    precision or ``except SentinelError`` as a single umbrella. A
    single ``code`` attribute exposes the wire error-code string
    (e.g. ``"AUTH_FAILED"``) or empty string for local errors with
    no wire code.
    """

    code: str = ""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class ReporterConnectionError(ReporterError):
    """网络层失败 (连接拒绝 / EOF / 非 4xx-5xx).

    中文
    ----
    TCP / HTTP 传输层的连接错误。区别于 ``ReporterProtocolError``
    (协议字段错, 4xx), 本类表示根本未建立有效的 HTTP 响应。
    默认触发 exponential backoff 重试 (3 次: 50ms / 200ms / 1s + 抖动).

    English
    --------
    Transport-layer connection failure (refused / EOF / not 4xx-5xx).
    Differs from ``ReporterProtocolError`` (protocol schema failure,
    4xx) — this class signals no valid HTTP response was received.
    Triggers exponential backoff retry by default (3 attempts:
    50ms / 200ms / 1s + jitter).
    """


class ReporterAuthError(ReporterError):
    """鉴权失败 (401 / ``AUTH_FAILED``).

    中文
    ----
    协议 transport §5.1 ``X-Atlas-Reporting-Token`` 校验失败。
    Reporter **不**重试 (协议 §6); reporter 关闭以防错误循环。
    ``code`` 透传 wire 错误码 ``"AUTH_FAILED"``.

    English
    --------
    Auth failure (401 / ``AUTH_FAILED``). Reporter does **not** retry
    (protocol §6); reporter is closed to prevent an error loop.
    ``code`` mirrors wire error code ``"AUTH_FAILED"``.
    """

    code: str = "AUTH_FAILED"


class ReporterProtocolError(ReporterError):
    """协议字段错 / 任何 4xx (除 AUTH_FAILED).

    中文
    ----
    Server 返回 4xx 且错误码非 ``AUTH_FAILED`` (e.g. ``MALFORMED_ENVELOPE``
    / ``UNKNOWN_EVENT_KIND`` / ``SEQUENCE_NOT_MONOTONIC`` / ``STALE_EPOCH``).
    4xx 默认**不**重试; reporter 关闭. ``code`` 透传 wire 错误码.

    English
    --------
    Server returns 4xx with non-``AUTH_FAILED`` code (e.g.
    ``MALFORMED_ENVELOPE`` / ``UNKNOWN_EVENT_KIND`` /
    ``SEQUENCE_NOT_MONOTONIC`` / ``STALE_EPOCH``). 4xx does not
    retry by default; reporter is closed. ``code`` mirrors wire
    error code.
    """


class ReporterAckTimeoutError(ReporterError):
    """投递后等 ack 超时.

    中文
    ----
    transport §6 重试窗口内 (3 次) 收不到 Server ack. 触发 reporter
    关闭以防止 sequence gap. ``code`` 固定 ``"ACK_TIMEOUT"``.

    English
    --------
    No Server ack within transport §6 retry window (3 attempts).
    Triggers reporter close to prevent sequence gap. ``code`` is
    fixed as ``"ACK_TIMEOUT"``.
    """

    code: str = "ACK_TIMEOUT"


class ReporterOverflowError(ReporterError):
    """Outbox 满 (block_with_timeout 策略超时或 drop_newest 显式拒绝).

    中文
    ----
    ``outbox_max_size`` 上限 + 3 选 1 策略之一:
    - ``drop_oldest`` 永远不抛本错 (静默淘汰最老, 增 ``dropped_count``)
    - ``drop_newest`` 抛本错拒绝新 event (用户需 catch 处理)
    - ``block_with_timeout`` 在超时后抛本错 (默认 100ms, 跟 batch
      send interval 1:1)

    ``code`` 固定 ``"OUTBOX_OVERFLOW"``. 注意 ``drop_oldest`` 走
    ``ReporterOutboxDropped`` 内部 counter (不出现在 reporter 公开 API).

    English
    --------
    Outbox full (``block_with_timeout`` elapsed or ``drop_newest``
    explicit rejection). Combined with ``outbox_max_size`` and one
    of 3 explicit policies:

    - ``drop_oldest`` never raises this (silently evicts oldest, increments
      ``dropped_count``)
    - ``drop_newest`` raises this to reject new event (caller must handle)
    - ``block_with_timeout`` raises this after timeout (default 100ms,
      1:1 with batch send interval)

    ``code`` fixed as ``"OUTBOX_OVERFLOW"``. Note ``drop_oldest`` uses
    the internal ``ReporterOutboxDropped`` counter (not exposed in
    reporter public API).
    """

    code: str = "OUTBOX_OVERFLOW"


class ReporterSendTimeoutError(ReporterError):
    """单次 send 超时 (connect_timeout / request_timeout).

    中文
    ----
    跟 ``ReporterAckTimeoutError`` 区别: 本类表示**单次** send 没在
    ``connect_timeout_ns`` (5s) / ``request_timeout_ns`` (5s) 内完成.
    跟 ``ReporterConnectionError`` 区别: 本类表示**已建立**连接但
    响应没在 timeout 内到达.

    English
    --------
    Differs from ``ReporterAckTimeoutError``: this signals a single
    send that did not complete within ``connect_timeout_ns`` (5s) or
    ``request_timeout_ns`` (5s). Differs from
    ``ReporterConnectionError``: a connection was established but the
    response did not arrive in time.
    """


class ReporterLeaseError(ReporterError):
    """1.0 future use, 跟 Cluster lease 命名对齐.

    中文
    ----
    集群模式下 batch 提交需 lease 时使用 (1.0 单进程未启用, 保留扩展点).
    1.0 single process 永远不会抛本错; 引入是为 M6.6+ 集群模式时
    reporter 跟 cluster server lease 契约保持一致.

    English
    --------
    Reserved for cluster-mode batch submission (1.0 single-process
    never raises this; kept as an extension point so the reporter
    contract aligns with the cluster lease contract in M6.6+).
    """


__all__ = [
    "ReporterError",
    "ReporterConnectionError",
    "ReporterAuthError",
    "ReporterProtocolError",
    "ReporterAckTimeoutError",
    "ReporterOverflowError",
    "ReporterSendTimeoutError",
    "ReporterLeaseError",
]
