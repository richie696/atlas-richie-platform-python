"""Secret registry 子包。

中文
----
对位 Java secret 没有独立 registry 子包,功能内嵌在 `DefaultSecretResolver`
里;Python 端为对称 cache 的 `cache_core/registry/`,把 `SecretRegistry`
独立出来,让 `GlobalSecret` facade 复用同样的 `instance() / install() /
uninstall()` 模式(R-214 决定)。

English
--------
Secret registry sub-package. The Java side has no standalone registry
sub-package; the Python side mirrors the cache layout for consistency.
"""

from atlas_richie.secret.registry.secret_registry import SecretRegistry

__all__ = ["SecretRegistry"]
