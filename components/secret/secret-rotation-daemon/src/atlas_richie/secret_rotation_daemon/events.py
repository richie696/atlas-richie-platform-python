"""Secret rotation event types — `SecretRotated` event + `SecretRotationCallback`。

中文
----
对位 Java `cn.richie696.component.secret.api.bootstrap.RotationPublisher`
+ `RotationEvent`。Python 端用 frozen dataclass 表示事件,callback
类型是 `Callable[[SecretRotated], None]`,framework 调度 callback
时**同步**调用,consumer 在 callback 里重新 `get(reference)` 即可。

English
--------
Event type for the rotation daemon. `SecretRotated` is a frozen
dataclass carrying the `SecretReference` and the **new** version
the daemon just observed. Callbacks are plain
`Callable[[SecretRotated], None]` invoked synchronously on the
daemon's polling thread.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas_richie.secret.reference import SecretReference, SecretVersion


@dataclass(frozen=True, slots=True)
class SecretRotated:
    """Fired when the daemon observes a new `SecretVersion` for
    a registered `SecretReference`.

    Attributes:
        reference: The reference whose version changed.
        old_version: The previously-observed version. `None` if
            this is the first poll (cold start).
        new_version: The newly-observed version.
    """

    reference: "SecretReference"
    old_version: "SecretVersion | None"
    new_version: "SecretVersion"


SecretRotationCallback = Callable[[SecretRotated], None]


__all__ = [
    "SecretRotated",
    "SecretRotationCallback",
]
