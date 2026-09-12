"""OpenBao secret backend properties.

中文
----
对位 Java `cn.richie696.component.secret.provider.openbao.OpenBaoSecretProperties`。

OpenBao 与 Vault 在 HTTP API 层是 1:1 兼容的(KV v2 + Transit),所以
OpenBao 的属性就是 Vault 属性的子集 — 暂时**不**新增任何 OpenBao 特有字段。
未来 OpenBao 偏离(比如 `bao_namespace` 多租户 / audit log 客户端 ID
header / `seal wrap` 硬件根令牌)时,在 `OpenBaoSecretProperties` 上加
字段即可,不影响 `atlas-richie-secret-vault` 的 API surface。

`OpenBaoSecretProperties` 继承 `VaultSecretProperties` 但**不**重写
任何字段,目的是:

1. 外部 type-check 看到 `OpenBaoSecretProperties` 时立刻知道这是
   走 OpenBao wheel 的 config
2. 后续加 OpenBao 特有字段时不用改 `atlas-richie-secret-vault`

English
--------
OpenBao is API-compatible with Vault (KV v2 + Transit), so the
properties class is currently identical to
`VaultSecretProperties`. The subclass exists for branding /
future divergence: if OpenBao ever adds a feature that is
genuinely OpenBao-only (e.g. `bao_namespace`, hardware-seal-wrap
root tokens, custom audit headers), it can land here without
modifying the upstream Vault wheel.
"""

from __future__ import annotations

from atlas_richie.secret_vault.properties import VaultSecretProperties


class OpenBaoSecretProperties(VaultSecretProperties):
    """Properties for the OpenBao backend.

    Inherits every field from `VaultSecretProperties` unchanged.
    Kept as a distinct type so the secret registry can
    differentiate OpenBao sessions from Vault sessions at the
    static type level.
    """

    pass


__all__ = ["OpenBaoSecretProperties"]
