"""把 mfa-validation 的 `SecretRetriever` 桥接到 secret-core 的 `SecretOperations`。

对位关系：mfa-validation 定义了 `SecretRetriever` Protocol 但刻意不依赖任何
KMS/存储实现；本包是那根桥，使 TOTP 密钥可存放在任一 secret provider。

错误映射是本桥的关键决策：
- `SecretIntegrityException` → `None`。secret-core 的 provider 约定以它表达
  「未找到」，MFA 侧把 None 视为「该用户未配置 MFA」。
- 其它 `SecretException`（配置、解密失败）→ 原样上抛。把这些也吞成 None 会
  把基础设施故障伪装成「未配置」，排障时极具误导性。

已知失真：redis provider 把连接故障也包装为 IntegrityException，因此 outage
时返回 None、验证按「无密钥」失败关闭——安全但原因失真，这是该 provider
错误映射的既有问题，不在本桥修复。
"""

from __future__ import annotations

from atlas_richie.secret.errors import SecretIntegrityException
from atlas_richie.secret.operations import SecretOperations
from atlas_richie.secret.reference import SecretReference


class SecretStoreSecretRetriever:
    """`SecretRetriever` over any `SecretOperations` implementation."""

    def __init__(
        self,
        operations: SecretOperations,
        *,
        default_provider: str | None = None,
    ) -> None:
        if operations is None:
            raise ValueError("operations must not be None")
        self._operations = operations
        self._default_provider = default_provider

    @property
    def operations(self) -> SecretOperations:
        return self._operations

    def retrieve(self, secret_reference: str) -> str | None:
        reference = self._reference(secret_reference)
        try:
            value = self._operations.get(reference)
        except SecretIntegrityException:
            return None
        text = value.as_str().strip()
        return text or None

    def _reference(self, secret_reference: str) -> SecretReference:
        if not secret_reference:
            raise ValueError("secret_reference must not be blank")
        if ":" in secret_reference:
            provider, _, path = secret_reference.partition(":")
        elif self._default_provider is not None:
            provider, path = self._default_provider, secret_reference
        else:
            raise ValueError(
                f"secret_reference {secret_reference!r} has no provider prefix "
                f"and no default_provider is configured"
            )
        if not provider.strip() or not path.strip():
            raise ValueError(f"secret_reference {secret_reference!r} is malformed")
        return SecretReference(provider=provider.strip(), path=path.strip())


__all__ = ["SecretStoreSecretRetriever"]