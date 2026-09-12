"""`atlas-richie-secret-kmip` — KMIP 2.1 backend (Key Management Interoperability Protocol)。

中文
----
对位 Java `cn.richie696.component.secret.provider.kmip.*`(6 个文件)。
1:1 功能对齐,Python 端按 R-232 决定压成单 wheel,内部子包:

- `ttlv.py` — KMIP 2.1 TTLV 编码 / 解码(对位 Java `KmipTtlv.java`)
- `properties.py` — `KmipSecretProperties`(pydantic-settings
  env 注入,前缀 `ATLAS_RICHIE_SECRET_KMIP_`)
- `configuration.py` — `KmipConfigurationResolver`,含
  endpoint / protocol version / key bindings 校验 +
  SHA-256 configuration hash
- `client.py` — `KmipSecretClient`,复合 2 个 SPI 角色
  (`KeyWrappingBackend` via AES-KWP + `SecretProviderSession`),
  **无** `SecretOperations` / `SecretListable` / `SecretWriter`
  / `SecretDeletable`(KMIP 是 key management 协议,不存 secret)
- `factory.py` — `KmipSecretProviderFactory`(framework 入口)
  + 内部 `KmipClientFactory`(`ssl.SSLContext` 构造)

无 SDK 依赖;纯标准库 + `pydantic` / `pydantic-settings`。
framework 端**不**看到 KMIP TTLV 细节 — Protocol 抽象掉。

English
--------
KMIP 2.1 backend wheel. Mirrors Java
`atlas-richie-secret-provider-kmip` 1:1. 4 source files
(ttlv / properties / configuration / client+factory). The
client is a 2-SPI composite (KeyWrappingBackend via
AES-KWP + SecretProviderSession); no secret read / list /
write / delete (KMIP is a key-management protocol).
"""

from atlas_richie.secret_kmip.client import (
    KmipSecretClient,
    _parse_endpoint,
    _parse_response,
    _build_encrypt_request,
    _build_decrypt_request,
    _send_request,
    _retry_io,
)
from atlas_richie.secret_kmip.configuration import (
    KmipConfigurationResolver,
    ResolvedKmipConfiguration,
)
from atlas_richie.secret_kmip.factory import (
    KmipClientFactory,
    KmipSecretProviderFactory,
)
from atlas_richie.secret_kmip.properties import KmipSecretProperties
from atlas_richie.secret_kmip.ttlv import (
    BYTE_STRING,
    ENUMERATION,
    INTEGER,
    STRUCTURE,
    TEXT,
    Element,
    bytes_,
    children,
    element,
    enumeration,
    first,
    integer,
    structure,
    text,
)

__all__ = [
    # properties
    "KmipSecretProperties",
    # configuration
    "ResolvedKmipConfiguration",
    "KmipConfigurationResolver",
    # SSL construction
    "KmipClientFactory",
    # framework entry
    "KmipSecretProviderFactory",
    # 2-SPI composite
    "KmipSecretClient",
    # TTLV codec
    "Element",
    "STRUCTURE",
    "INTEGER",
    "ENUMERATION",
    "TEXT",
    "BYTE_STRING",
    "element",
    "structure",
    "integer",
    "enumeration",
    "text",
    "bytes_",
    "children",
    "first",
    # transport / codec internals (re-exported for tests)
    "_parse_endpoint",
    "_parse_response",
    "_build_encrypt_request",
    "_build_decrypt_request",
    "_send_request",
    "_retry_io",
]
