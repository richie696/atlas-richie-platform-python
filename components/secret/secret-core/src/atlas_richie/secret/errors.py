"""Secret 组件失败类型集合。

中文
----
`SecretException` 是 secret 子系统的根异常,继承自
`atlas_richie.contracts.PlatformError`,保持组件级错误分类与全框架
一致的契约(代码 / 消息 / 原因链)。

按 Java 端 `cn.richie696.component.secret.exception` 子包 1:1 对位:

- `SecretException` — 所有 secret 错误的基类
- `SecretConfigurationException` — 配置不合法(provider 启动期失败)
- `SecretCryptoException` — 加密 / 解密 / 签名 / 验签失败
- `SecretBootstrapException` — 启动期 secret 注入失败
- `SecretIntegrityException` — 完整性校验失败(签名 / checksum / version 不匹配)

错误分类原则(沿用 R-218 决定):

1. 公开异常的字段(`code` / `message` / `cause`)稳定;私有异常(`_*Error`)
   标记为不承诺 API。
2. 不吞异常 — provider / bootstrap / crypto 任意环节失败都向上抛;
   facade 层的 try/except 只在"用户配置了 retry"时启用,默认快速失败。
3. 不跨组件借异常类型 — secret 子系统不抛 `OAuthError` /
   `CacheError`,即使语义相似;反之亦然(由调用方在自己层做翻译)。

English
--------
Secret component failure taxonomy.

`SecretException` is the root error type, derived from
`atlas_richie.contracts.PlatformError` for component-level error
classification that matches the rest of the framework. The 1:1 mapping
to the Java `cn.richie696.component.secret.exception` sub-package:

- `SecretException` — base class for all secret errors.
- `SecretConfigurationException` — invalid provider configuration.
- `SecretCryptoException` — encryption / decryption / signing failure.
- `SecretBootstrapException` — startup-time secret injection failure.
- `SecretIntegrityException` — integrity check failure (signature /
  checksum / version mismatch).
"""

from __future__ import annotations

from atlas_richie.contracts import PlatformError


class SecretException(PlatformError):
    """Base class for all secret component errors."""


class SecretConfigurationException(SecretException):
    """Invalid or missing provider configuration."""


class SecretCryptoException(SecretException):
    """Encryption, decryption, signing or verification failure."""


class SecretBootstrapException(SecretException):
    """Startup-time secret injection failure."""


class SecretIntegrityException(SecretException):
    """Integrity check failure: signature mismatch, checksum mismatch, version drift."""


__all__ = [
    "SecretException",
    "SecretConfigurationException",
    "SecretCryptoException",
    "SecretBootstrapException",
    "SecretIntegrityException",
]
