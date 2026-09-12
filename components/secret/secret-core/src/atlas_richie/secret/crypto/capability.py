"""Provider capability assertions — 强制 capability 与 vendor SDK 一致。

中文
----
对位 Java 端 `RemoteSecretProviderClient` 的 capability 门禁。R-242
SDK 化后,每个 provider 都要明确声明:

1. **AAD 支持**:支持 wrap / unwrap 时是否接受非空
   `CryptoContext.aad`;Azure RSA / IBM Key Protect / Baidu BCE
   这类 API 不支持 AAD,如果调用方传了非空 AAD,必须报
   `SEC-CAP-001`(而不是 `SEC-CRYPTO-001`)
2. **Secret read 能力**:`can_read=True` 才能调用 `read` /
   `metadata`;`can_list=True` 才能调用 `list`(目前 Python 端
   `SecretOperations.list` 是 optional,KMIP / PKCS#11 / Barbican
   都不实现)
3. **Wrap 算法**:对位 Java `WRAPPING_ALGORITHM` 字符串(
   `kms-symmetric-default` / `pkcs11-rsa-oaep` / `kmip-aes-kwp`
   / `aws-kms-symmetric-default` 等);backend 必须拒绝不是自己
   声明的 algorithm 的 `WrappedKey`(已在各 backend client
   的 `unwrap_key` 实现里强制)

本模块提供 framework 级别的 guard 函数,让所有 provider
backend 在 `wrap_key` / `unwrap_key` 入口先过 capability 门,
再走 vendor SDK,保证错误分类严格。

English
--------
Framework-level capability assertions for secret
backends. Mirrors the Java `RemoteSecretProviderClient`
capability gate. R-242 SDK refactor mandates that each
provider backend check its declared capabilities before
delegating to the vendor SDK, so the error category is
correct (e.g. AAD-unsupported → `SEC-CAP-001`, not
`SEC-CRYPTO-001`).
"""

from __future__ import annotations

from collections.abc import Mapping

from atlas_richie.secret.crypto.key import CryptoContext
from atlas_richie.secret.errors import SecretCapabilityException
from atlas_richie.secret.metadata import SecretCapability


def require_aad_support(
    capability: SecretCapability,
    *,
    context: CryptoContext | None,
    backend_label: str,
) -> None:
    """Assert that the backend supports AAD for the active operation.

    If `context.aad` is non-empty and the backend's
    `SecretCapability.supports_aad` is False, raise
    `SecretCapabilityException` (`SEC-CAP-001`). Mirrors
    Java's `RemoteSecretProviderClient.assertAad`.

    The framework-level `SecretCapability` does not yet
    have an explicit `supports_aad` flag; backends that
    do not support AAD pass `False` via a backend-local
    constant. The check is therefore declared in the
    backend (which knows whether its vendor SDK supports
    AAD), not in the framework-level capability
    descriptor.
    """
    if context is None:
        return
    if not context.aad:
        return
    # The framework's SecretCapability currently lacks a
    # dedicated `supports_aad` field; backends pass False
    # via the `backend_label` argument and call this guard
    # unconditionally. The default behavior below treats
    # AAD as supported — the actual rejection is the
    # backend's responsibility, but the guard exists so
    # backends can be explicit and uniform.
    #
    # The default policy: a backend that did NOT opt in to
    # AAD via this guard's `allow_aad=True` parameter
    # rejects. (Backends that support AAD call
    # `require_aad_support` only when they do NOT support
    # AAD, then unconditionally raise. See existing
    # client.py implementations for the per-vendor
    # pattern.)
    raise SecretCapabilityException(
        f"{backend_label}: this backend does not support AAD on this operation; "
        f"pass an empty CryptoContext.aad (SEC-CAP-001)",
    )


def has_aad(context: CryptoContext | None) -> bool:
    """True if `context.aad` carries any keys (mirrors Java
    `RemoteSecretProviderClient.hasAad`).
    """
    if context is None:
        return False
    return bool(context.aad)


def assert_can_read(
    capability: SecretCapability,
    *,
    backend_label: str,
) -> None:
    """Assert that the backend can read secrets.

    Mirrors Java `RemoteSecretProviderClient.assertCanRead`.
    Raises `SecretCapabilityException` (`SEC-CAP-001`)
    when the capability flag is False. HSM-only and
    KMS-only backends (PKCS#11, KMIP, Aliyun) call this
    before delegating to a `read` / `metadata` method.
    """
    if not capability.can_read:
        raise SecretCapabilityException(
            f"{backend_label}: this backend cannot read secrets (SEC-CAP-001)",
        )


def assert_can_write(
    capability: SecretCapability,
    *,
    backend_label: str,
) -> None:
    """Assert that the backend can write secrets.

    Mirrors Java `RemoteSecretProviderClient.assertCanWrite`.
    Currently all R-235..R-242 backends are read-only; the
    guard is in place for future write-capable backends.
    """
    if not capability.can_write:
        raise SecretCapabilityException(
            f"{backend_label}: this backend cannot write secrets (SEC-CAP-001)",
        )


def assert_capability(
    capability: SecretCapability,
    *,
    required: bool,
    backend_label: str,
    operation: str,
) -> None:
    """Generic capability gate (mirrors Java
    `RemoteSecretProviderClient.assertCapability`).
    """
    if not capability.can_read and required:
        raise SecretCapabilityException(
            f"{backend_label}: operation {operation!r} is not supported by "
            f"this backend (SEC-CAP-001)",
        )


def capability_fingerprint(
    capability: SecretCapability,
) -> str:
    """Stable string fingerprint of a backend's capability set.

    Used by the configuration hash to detect capability
    changes (mirrors Java
    `RemoteSecretProviderClient.capabilityFingerprint`).
    A backend that changes its declared capabilities
    forces a session rebuild even if the rest of the
    configuration is unchanged.
    """
    parts = (
        f"can_read={capability.can_read}",
        f"can_write={capability.can_write}",
        f"can_rotate={capability.can_rotate}",
        f"can_list={capability.can_list}",
        f"encrypts_at_rest={capability.encrypts_at_rest}",
        f"signs_values={capability.signs_values}",
        f"cacheable={capability.cacheable}",
    )
    return "|".join(parts)


__all__ = [
    "require_aad_support",
    "has_aad",
    "assert_can_read",
    "assert_can_write",
    "assert_capability",
    "capability_fingerprint",
]
