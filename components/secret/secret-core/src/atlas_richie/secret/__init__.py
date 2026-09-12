"""`atlas-richie-secret-core` — 框架无关 secret 管理核心。

中文
----
对位 Java `atlas-richie-secret-parent`(21 个子模块),1:1 功能对齐但
单 wheel 内部子包分层(沿用 R-232 决定):

- 顶层 facade:`GlobalSecret` 静态外观 + `SecretRegistry` 互斥注册
- 读 / 写契约:`SecretResolver` / `SecretOperations` / `SecretWriter`
  / `SecretDeletable`
- 元数据 / 引用 / 值:`SecretMetadata` / `SecretReference` /
  `SecretValue` / `DestroyableSecretValue`
- Provider SPI:`SecretProviderConfiguration` / `SecretProviderDescriptor` /
  `SecretProviderFactory` / `SecretProviderSession`
- 本地 backend:`InMemorySecretProvider` / `EnvSecretProvider` /
  `FileSecretProvider`
- Crypto:`SecretCipher` / `SigningService` / `EnvelopeCrypto` +
  `ArseEnvelopeCodec`,带 `cryptography` 库可选依赖
- 启动期:`AtlasSecretEnvironmentPostProcessor` + catalog + policy +
  state + discovery + SPI + default client
- Snapshot:`SecretSnapshotManager` + listener + event
- Testkit:`StubSecretCallback` / `RecordingSnapshotListener` /
  `ProviderBundle`

后端(redis / vault / openbao / pkcs11 / aws / azure / gcp / 国内云 ...)
是独立 wheel(从 `atlas-richie-secret-redis` 开始),不在本包内。

English
--------
Framework-neutral secret management core. 1:1 functional parity with
the Java `atlas-richie-secret-parent` 21 sub-modules; the Python
side consolidates everything into one wheel with internal sub-
packages. Remote backends (redis / vault / openbao / pkcs11 / cloud)
live in separate wheels.
"""

from atlas_richie.secret.bootstrap import (
    AtlasSecretEnvironmentPostProcessor,
    BootstrapSecretProperties,
    DefaultBootstrapContext,
    DiscoveryResult,
    RequiredWhen,
    ResolverBackedBootstrapClient,
    SecretBinding,
    SecretBindingCatalog,
    SecretBindingCatalogLoader,
    SecretBindingCatalogSet,
    SecretBootstrapClient,
    SecretBootstrapContext,
    SecretBootstrapProviderFactory,
    SecretBootstrapRequest,
    SecretBootstrapResult,
    SecretBootstrapSnapshot,
    SecretBootstrapState,
    SecretExposure,
    SecretKind,
    SecretPropertyPattern,
    SecretProviderDiscovery,
    SecretProviderTopology,
    SecretProviderType,
    SecretPropertyPolicy,
    SecretRefreshStrategy,
)
from atlas_richie.secret.callback import SecretCallback
from atlas_richie.secret.crypto import (
    ArseEnvelopeCodec,
    CipherEnvelope,
    CryptoContext,
    DefaultEnvelopeCrypto,
    DefaultSecretCipher,
    DefaultSigningService,
    EnvelopeCodec,
    EnvelopeCrypto,
    KeyPurpose,
    KeyReference,
    KeyWrappingBackend,
    SecretCipher,
    SignatureValue,
    SigningBackend,
    SigningService,
    WrappedKey,
    generate_ecdsa_keypair,
    now_utc,
)
from atlas_richie.secret.errors import (
    SecretBootstrapException,
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.global_secret import GlobalSecret
from atlas_richie.secret.global_secret_manager import GlobalSecretManager
from atlas_richie.secret.local import (
    EnvSecretOperations,
    EnvSecretProviderFactory,
    FileSecretDeletable,
    FileSecretOperations,
    FileSecretProviderFactory,
    FileSecretWriter,
    InMemorySecretDeletable,
    InMemorySecretOperations,
    InMemorySecretProviderFactory,
    InMemorySecretWriter,
)
from atlas_richie.secret.metadata import SecretBackend, SecretCapability, SecretMetadata
from atlas_richie.secret.operations import SecretListable, SecretOperations
from atlas_richie.secret.provider import (
    SecretProviderConfiguration,
    SecretProviderDescriptor,
    SecretProviderFactory,
    SecretProviderSession,
    ensure_open,
    list_capability,
)
from atlas_richie.secret.reference import (
    SecretReference,
    SecretVersion,
    SecretVersionSelector,
    SecretVersionSelectorKind,
)
from atlas_richie.secret.registry import SecretRegistry
from atlas_richie.secret.resolver import DefaultSecretResolver, SecretResolver
from atlas_richie.secret.snapshot import (
    SecretRuntimeSnapshot,
    SecretSnapshotChangedEvent,
    SecretSnapshotListener,
    SecretSnapshotManager,
)
from atlas_richie.secret.testkit import (
    ProviderBundle,
    RecordingSnapshotListener,
    StubSecretCallback,
    in_memory_fixture,
)
from atlas_richie.secret.value import DestroyableSecretValue, SecretValue
from atlas_richie.secret.writer import SecretDeletable, SecretWriter

__all__ = [
    # facade
    "GlobalSecret",
    "GlobalSecretManager",
    "SecretRegistry",
    # errors
    "SecretException",
    "SecretConfigurationException",
    "SecretCryptoException",
    "SecretBootstrapException",
    "SecretIntegrityException",
    # read / write
    "SecretResolver",
    "DefaultSecretResolver",
    "SecretOperations",
    "SecretListable",
    "SecretWriter",
    "SecretDeletable",
    # value / reference / metadata
    "SecretValue",
    "DestroyableSecretValue",
    "SecretReference",
    "SecretVersion",
    "SecretVersionSelector",
    "SecretVersionSelectorKind",
    "SecretMetadata",
    "SecretBackend",
    "SecretCapability",
    "SecretCallback",
    # snapshot
    "SecretSnapshotManager",
    "SecretSnapshotChangedEvent",
    "SecretSnapshotListener",
    "SecretRuntimeSnapshot",
    # testkit (re-exported)
    "RecordingSnapshotListener",
    "StubSecretCallback",
    # provider SPI
    "SecretProviderConfiguration",
    "SecretProviderDescriptor",
    "SecretProviderFactory",
    "SecretProviderSession",
    "ensure_open",
    "list_capability",
    # local backends
    "InMemorySecretProviderFactory",
    "InMemorySecretOperations",
    "InMemorySecretWriter",
    "InMemorySecretDeletable",
    "EnvSecretProviderFactory",
    "EnvSecretOperations",
    "FileSecretProviderFactory",
    "FileSecretOperations",
    "FileSecretWriter",
    "FileSecretDeletable",
    # crypto
    "KeyPurpose",
    "KeyReference",
    "WrappedKey",
    "CryptoContext",
    "CipherEnvelope",
    "SignatureValue",
    "now_utc",
    "KeyWrappingBackend",
    "SigningBackend",
    "SecretCipher",
    "DefaultSecretCipher",
    "SigningService",
    "DefaultSigningService",
    "generate_ecdsa_keypair",
    "EnvelopeCrypto",
    "EnvelopeCodec",
    "ArseEnvelopeCodec",
    "DefaultEnvelopeCrypto",
    # bootstrap
    "SecretKind",
    "SecretExposure",
    "RequiredWhen",
    "SecretRefreshStrategy",
    "SecretPropertyPattern",
    "SecretBinding",
    "SecretBindingCatalog",
    "SecretBindingCatalogSet",
    "SecretBindingCatalogLoader",
    "SecretProviderType",
    "SecretBootstrapRequest",
    "SecretBootstrapResult",
    "SecretBootstrapContext",
    "DefaultBootstrapContext",
    "SecretBootstrapClient",
    "SecretBootstrapProviderFactory",
    "SecretPropertyPolicy",
    "BootstrapSecretProperties",
    "SecretBootstrapState",
    "SecretProviderTopology",
    "SecretBootstrapSnapshot",
    "SecretProviderDiscovery",
    "DiscoveryResult",
    "AtlasSecretEnvironmentPostProcessor",
    "ResolverBackedBootstrapClient",
    # testkit
    "ProviderBundle",
    "in_memory_fixture",
]
