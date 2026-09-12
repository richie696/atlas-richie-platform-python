"""`atlas-richie-secret-rotation-daemon` — background rotation watcher。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.RotationPublisher`。
Python 端抽到独立 wheel,给所有 backend(Vault / OpenBao / AWS /
Azure / GCP / Redis / HSM 不支持)共用。

2 个 public symbol:`SecretRotationDaemon` + `SecretRotated` event。

English
--------
Background rotation watcher wheel. Mirrors Java's
`RotationPublisher` hook. Works against any backend that
implements `SecretOperations`. 2 public symbols.
"""

from atlas_richie.secret_rotation_daemon.daemon import SecretRotationDaemon
from atlas_richie.secret_rotation_daemon.events import (
    SecretRotated,
    SecretRotationCallback,
)

__all__ = [
    "SecretRotationDaemon",
    "SecretRotated",
    "SecretRotationCallback",
]
