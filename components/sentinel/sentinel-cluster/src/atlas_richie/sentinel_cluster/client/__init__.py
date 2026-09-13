"""Atlas Richie Sentinel Cluster — Client 端公开 API (M6.3.4).

中文
----
Client 端 (sentinel-cluster wheel) 1.0 公开 API surface。

**导出** (1.0 公开, 跟 IMPLEMENTATION-PLAN §4.3 一致):

- ``RemoteTokenService`` — ``TokenService`` Port 的远程实现 (同步 facade)
- ``ClientIdentity`` — Client 端身份 (frozen slots dataclass)

**不导出** (1.0 内部, 显式不暴露):

- ``HttpTransportClient`` — 内部 transport, 1.0 不开放构造
- ``auth`` / ``retry`` / ``policy`` 模块的内部 helper
- 内部异常类 ``_TransportUnretryable`` / ``_TransportInternalError``

English
--------
Client-side (sentinel-cluster wheel) 1.0 public API surface.

Exports (1.0 public, per IMPLEMENTATION-PLAN §4.3):

- ``RemoteTokenService`` — ``TokenService`` Port remote impl (sync facade)
- ``ClientIdentity`` — Client-side identity (frozen slots dataclass)

Not exported (1.0 internal, explicitly not exposed):

- ``HttpTransportClient`` — internal transport, 1.0 not constructible by user
- ``auth`` / ``retry`` / ``policy`` module internal helpers
- Internal exception classes ``_TransportUnretryable`` / ``_TransportInternalError``
"""

from __future__ import annotations

from .remote_token_service import ClientIdentity, RemoteTokenService

__all__ = [
    "ClientIdentity",
    "RemoteTokenService",
]
