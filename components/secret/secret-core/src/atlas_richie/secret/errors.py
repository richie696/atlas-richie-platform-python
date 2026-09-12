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
- `SecretCapabilityException` — 能力不支持(R-242 引入,对位 Java
  `SEC-CAP-001`;典型场景:vendor 不支持 AAD 但 `CryptoContext.
  associated_data` 非空,必须明确报 `SEC-CAP-001` 而不是
  `SEC-CRYPTO-001`,防止能力差异被误归类为"加密失败")

错误分类原则(沿用 R-218 决定 + R-242 SDK 化强化):

1. 公开异常的字段(`code` / `message` / `cause`)稳定;私有异常(`_*Error`)
   标记为不承诺 API。
2. 不吞异常 — provider / bootstrap / crypto 任意环节失败都向上抛;
   facade 层的 try/except 只在"用户配置了 retry"时启用,默认快速失败。
3. 不跨组件借异常类型 — secret 子系统不抛 `OAuthError` /
   `CacheError`,即使语义相似;反之亦然(由调用方在自己层做翻译)。
4. **NotFound 边界**(R-242 SDK 化强化):只有 vendor 明确的 "secret
   不存在" 异常才能被翻译成 `null` / `SecretIntegrityException`。
   权限拒绝、凭据失败、参数错误、网络错误、响应格式错误必须保持
   失败(`SEC-PROVIDER-001` / `SEC-AUTH-001` / `SEC-AUTHZ-001`),
   不能伪装成"secret 缺失"。

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
- `SecretCapabilityException` — capability unsupported (R-242 SDK
  refactor; mirrors Java `SEC-CAP-001`; typical case: vendor
  KMS does not support AAD but the caller supplied a non-empty
  `CryptoContext.associated_data`; the call must raise
  `SEC-CAP-001`, not `SEC-CRYPTO-001`, so the caller can
  distinguish "capability mismatch" from "encryption failure").

NotFound boundary (R-242 SDK refactor): only vendor-confirmed
"secret does not exist" exceptions may be translated to
`null` / `SecretIntegrityException`. Permission denied,
credential failure, parameter error, network error, and
response-format error must surface as failures
(`SEC-PROVIDER-001` / `SEC-AUTH-001` / `SEC-AUTHZ-001`); never
masquerade as "secret missing".
"""

from __future__ import annotations

from atlas_richie.contracts import PlatformError


class SecretException(PlatformError):
    """Base class for all secret component errors."""


class SecretConfigurationException(SecretException):
    """Invalid or missing provider configuration (mirrors Java `SEC-BOOT-003`)."""


class SecretCryptoException(SecretException):
    """Encryption, decryption, signing or verification failure.

    Typical codes:
    - `SEC-CRYPTO-001` — wrap / encrypt failure
    - `SEC-CRYPTO-002` — unwrap / decrypt failure
    """


class SecretBootstrapException(SecretException):
    """Startup-time secret injection failure (mirrors Java `SEC-STORE-001`)."""


class SecretIntegrityException(SecretException):
    """Integrity check failure: signature mismatch, checksum mismatch, version drift."""


class SecretCapabilityException(SecretException):
    """Capability not supported by the active backend.

    Mirrors Java `SEC-CAP-001`. Typical use: the caller
    passed a non-empty `CryptoContext.associated_data` (AAD)
    to a backend whose SDK does not support AAD on this
    operation; the request must fail with this exception
    (not `SecretCryptoException`) so the caller can
    distinguish "this backend cannot do what you asked"
    from "the backend tried and failed to encrypt".
    """


__all__ = [
    "SecretException",
    "SecretConfigurationException",
    "SecretCryptoException",
    "SecretBootstrapException",
    "SecretIntegrityException",
    "SecretCapabilityException",
]
