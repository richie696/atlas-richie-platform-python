"""`Pkcs11SecretClient` — 4-SPI composite over a PKCS#11 HSM.

中文
----
对位 Java `cn.richie696.component.secret.provider.pkcs11.Pkcs11SecretClient`,
后者用 `java.security.KeyStore` 加载 PKCS#11 provider,Python 端用
`python-pkcs11` 的 C-style API。

PKCS#11 是 HSM 抽象层,所以本 client **不**实现 `SecretOperations`
(HSM 不存 secret)、`SecretListable`(HSM 无 list 概念)、`SecretWriter`
/ `SecretDeletable`。session 的 `operations` / `writer` / `deletable`
都返回 `None`。

`KeyWrappingBackend`:
- `wrap_key(dek, kek)` → 用 kek 的 public key + `CKM_RSA_PKCS_OAEP` /
  `CKM_WRAPKEY_AES` 把 dek 封起来,返回 ciphertext bytes
- `unwrap_key(wrapped, context)` → 用 kek 的 private key 解封

`SigningBackend`:
- `sign(payload, key)` → 用 `CKM_SHA256_RSA_PKCS` /
  `CKM_ECDSA_SHA256` 签 payload
- `verify(payload, signature)` → 用 `CKM_*_VERIFY` 验签

`SecretBootstrapClient.bootstrap(request, context)`:
- 对位 Java:批量从 HSM 加载 DEKs(`session.find_objects(...)`)并合并

错误映射:
- `pkcs11.exceptions.NoSuchKey` / `pkcs11.exceptions.NoSuchObject` →
  `SecretIntegrityException` / `SecretCryptoException`
- `pkcs11.exceptions.PKCS11Error`(PIN 错 / 设备未连接) →
  `SecretConfigurationException`
- 其它 → `SecretException("SEC-CRYPTO-001")`

English
--------
Composite client over a PKCS#11 HSM. Mirrors Java's narrower
4-SPI scope (no storage / no listing). python-pkcs11's C-style
API is the only safe way to talk to an HSM from Python; the
public facade does not leak it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pkcs11
from pkcs11 import Session
from pkcs11.exceptions import (
    NoSuchKey,
    ObjectHandleInvalid,
    PKCS11Error,
)

from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyReference,
    SignatureValue,
    WrappedKey,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretMetadata
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret.value import SecretValue
from atlas_richie.secret.bootstrap.spi import (
    SecretBootstrapClient,
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
)
from atlas_richie.secret.bootstrap.catalog import RequiredWhen
from atlas_richie.secret_pkcs11.configuration import ResolvedPkcs11Configuration

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_pkcs11.client")

_WRAPPING_ALGORITHM = "pkcs11-rsa-oaep"

_SESSION_OPEN_KEY = object()  # sentinel; not used externally


class Pkcs11SecretClient(
    SecretBootstrapClient,
    SecretProviderSession,
):
    """Composite client for PKCS#11 HSM.

    Implements 4 SPI roles: `KeyWrappingBackend` (duck-typed),
    `SigningBackend` (duck-typed), `SecretBootstrapClient`,
    `SecretProviderSession`. The session's `operations` /
    `writer` / `deletable` properties all return `None` — HSM
    has no secret storage.
    """

    __slots__ = (
        "_closed",
        "_close_action",
        "_descriptor_backend",
        "_lib",
        "_resolved",
        "_snapshot_manager",
        "_token",
    )

    def __init__(
        self,
        resolved: ResolvedPkcs11Configuration,
        lib: Any,  # pkcs11.lib (type-annotated as Any to keep facade SDK-agnostic)
        token: Any,
        *,
        snapshot_manager: SecretSnapshotManager | None = None,
        close_action: Callable[[], None] | None = None,
        descriptor_backend: SecretBackend = SecretBackend.PKCS11,
    ) -> None:
        self._resolved = resolved
        self._lib = lib
        self._token = token
        self._snapshot_manager = snapshot_manager or SecretSnapshotManager()
        self._close_action = close_action
        self._closed = False
        self._descriptor_backend = descriptor_backend

    # --- SecretProviderSession Protocol ---------------------------------

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._resolved.provider_id,
            backend=self._descriptor_backend,
            capability=self._resolved.capability,
            version="0.2.0",
        )

    @property
    def configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self._resolved.provider_id,
            parameters={},
            timeout_seconds=self._resolved.properties.timeout_seconds,
            retries=0,  # HSM ops are not retried (would require biometric re-auth)
            namespace=self._resolved.properties.token_label,
        )

    @property
    def operations(self):  # type: ignore[override]
        # HSM has no secret storage; the framework's
        # `list_capability(session)` probe must observe
        # `None` so it doesn't try to call `get` /
        # `get_metadata` / `exists`.
        return None

    @property
    def writer(self):  # type: ignore[override]
        return None

    @property
    def deletable(self):  # type: ignore[override]
        return None

    @property
    def snapshot_manager(self) -> SecretSnapshotManager:
        return self._snapshot_manager

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._close_action is None:
            return
        try:
            self._close_action()
        except Exception:  # noqa: BLE001
            _logger.exception(
                "pkcs11: error during close_action for provider %r",
                self._resolved.provider_id,
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException(
                f"pkcs11: provider session {self._resolved.provider_id!r} is closed",
            )

    # --- KeyWrappingBackend (duck-typed) --------------------------------

    def wrap_key(
        self,
        dek: bytes,
        kek: KeyReference,
        *,
        algorithm: str | None = None,  # noqa: ARG002 - reserved
    ) -> WrappedKey:
        self._ensure_open()
        if not dek:
            raise SecretCryptoException(
                "pkcs11: wrap_key requires a non-empty DEK",
            )
        key_label = self._resolve_key_label(kek)
        try:
            session = self._open_session()
            with session:
                public_key = self._find_public_key(session, key_label)
                # The framework's `wrap_key` is "import the
                # caller's DEK bytes as a wrapped blob"; on PKCS#11
                # this maps to `public_key.encrypt(...)` (RSA-OAEP
                # for a caller-supplied plaintext < key size). The
                # python-pkcs11 `wrap_key(...)` API is for wrapping
                # an HSM-resident key object — a different use
                # case the framework does not currently exercise.
                mechanism = pkcs11.Mechanism.RSA_PKCS_OAEP
                wrapped = public_key.encrypt(dek, mechanism=mechanism)
        except NoSuchKey as error:
            raise SecretCryptoException(
                f"pkcs11 [SEC-KEY-001]: wrap_key for key "
                f"{key_label!r} not found: {error}",
            ) from error
        except PKCS11Error as error:
            raise self._map_crypto_error("wrap_key", kek, error) from error
        return WrappedKey(
            kek_reference=kek,
            ciphertext=wrapped,
            algorithm=_WRAPPING_ALGORITHM,
            nonce=None,
            aad={},
        )

    def unwrap_key(
        self,
        wrapped: WrappedKey,
        context: CryptoContext,
    ) -> bytes:
        self._ensure_open()
        if wrapped.algorithm != _WRAPPING_ALGORITHM:
            raise SecretCryptoException(
                f"pkcs11: cannot unwrap a key with algorithm "
                f"{wrapped.algorithm!r}; expected {_WRAPPING_ALGORITHM!r}",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "pkcs11: wrapped ciphertext is empty",
            )
        key_label = self._resolve_key_label(context.primary_key)
        try:
            session = self._open_session()
            with session:
                private_key = self._find_private_key(session, key_label)
                plaintext = private_key.decrypt(
                    wrapped.ciphertext,
                    mechanism=pkcs11.Mechanism.RSA_PKCS_OAEP,
                )
        except NoSuchKey as error:
            raise SecretCryptoException(
                f"pkcs11 [SEC-KEY-001]: unwrap_key for key "
                f"{key_label!r} not found: {error}",
            ) from error
        except PKCS11Error as error:
            raise self._map_crypto_error(
                "unwrap_key", context.primary_key, error,
            ) from error
        return plaintext

    # --- SigningBackend (duck-typed) ------------------------------------

    def sign(
        self,
        payload: bytes,
        key: KeyReference,
        *,
        algorithm: str | None = None,
    ) -> SignatureValue:
        self._ensure_open()
        if not payload:
            raise SecretCryptoException(
                "pkcs11: sign requires non-empty payload",
            )
        key_label = self._resolve_key_label(key)
        mechanism_str = (
            algorithm
            or self._resolved.properties.default_sign_mechanism.value
        )
        try:
            session = self._open_session()
            with session:
                private_key = self._find_private_key(session, key_label)
                signature = private_key.sign(
                    data=payload,
                    mechanism=_mechanism_from_string(mechanism_str),
                )
        except NoSuchKey as error:
            raise SecretCryptoException(
                f"pkcs11 [SEC-KEY-001]: sign for key "
                f"{key_label!r} not found: {error}",
            ) from error
        except PKCS11Error as error:
            raise self._map_crypto_error("sign", key, error) from error
        return SignatureValue(
            algorithm=mechanism_str,
            signature=signature,
            signed_at=datetime.now(tz=timezone.utc),
            key=key,
        )

    def verify(
        self,
        payload: bytes,
        signature: SignatureValue,
    ) -> bool:
        self._ensure_open()
        if not payload:
            raise SecretCryptoException(
                "pkcs11: verify requires non-empty payload",
            )
        if signature is None:
            raise SecretCryptoException(
                "pkcs11: verify requires a SignatureValue",
            )
        key_label = self._resolve_key_label(signature.key)
        try:
            session = self._open_session()
            with session:
                public_key = self._find_public_key(session, key_label)
                # The HSM's `verify(...)` returns `False` directly
                # for tampered signatures; it raises
                # `PKCS11Error` only for true crypto / key
                # errors. We map the bool False to the framework's
                # "False" path and surface `PKCS11Error` as
                # `SecretCryptoException` (mapped below).
                return bool(
                    public_key.verify(
                        data=payload,
                        signature=signature.signature,
                        mechanism=_mechanism_from_string(signature.algorithm),
                    )
                )
        except NoSuchKey as error:
            raise SecretCryptoException(
                f"pkcs11 [SEC-KEY-001]: verify for key "
                f"{key_label!r} not found: {error}",
            ) from error
        except PKCS11Error as error:
            raise self._map_crypto_error("verify", signature.key, error) from error
        except ObjectHandleInvalid as error:
            raise self._map_crypto_error("verify", signature.key, error) from error

    # --- SecretBootstrapClient Protocol --------------------------------

    def bootstrap(
        self,
        request: SecretBootstrapRequest,
        context: SecretBootstrapContext,
    ) -> SecretBootstrapResult:
        # HSM bootstrap is unusual: there is no secret to
        # *read*; bootstrap here means "verify a list of named
        # keys are present in the HSM" so a deployment knows
        # the HSM has the expected key inventory. We
        # acknowledge each binding by trying to look up the
        # key on the token; missing keys are reported as
        # `missing` (or raise for STARTUP-required bindings).
        self._ensure_open()
        started_at = context.now
        resolved: dict[str, str] = {}  # binding name -> key label
        missing: list[str] = []
        for binding in request.catalog.bindings:
            label = self._resolve_key_label_from_string(
                binding.reference.path,
            )
            try:
                session = self._open_session()
                with session:
                    self._find_public_key(session, label)
                    self._find_private_key(session, label)
            except NoSuchKey as error:
                if binding.required_when is RequiredWhen.STARTUP:
                    raise SecretException(
                        f"pkcs11: bootstrap key binding "
                        f"{binding.name!r} is missing: {error}",
                    ) from error
                missing.append(binding.name)
                continue
            resolved[binding.name] = label
        finished_at = context.now
        # Wrap as `SecretValue` with empty plaintext + a stub
        # `SecretMetadata` so the framework's downstream
        # pipeline is happy (the framework expects SecretValue,
        # but a HSM bootstrap result is really a "key inventory
        # ack"). `backend` is marked so callers can detect
        # HSM-only bootstrap and not treat the empty plaintext
        # as a real secret.
        result_resolved: dict[str, SecretValue] = {
            name: SecretValue(
                plaintext=b"",
                metadata=SecretMetadata(
                    reference=SecretReference(
                        provider=self.descriptor.name, path=name,
                    ),
                    version=SecretVersion(number="0", created_at=started_at),
                    backend=self._descriptor_backend,
                    created_at=started_at,
                    expires_at=None,
                    tags={"provider": "pkcs11", "kind": "key-inventory"},
                ),
            )
            for name in resolved
        }
        return SecretBootstrapResult(
            resolved=result_resolved,  # type: ignore[arg-type]
            missing=tuple(missing),
            started_at=started_at,
            finished_at=finished_at,
        )

    # --- Internal helpers -----------------------------------------------

    def _open_session(self) -> Session:
        """Open a fresh PKCS#11 session. Sessions are short-lived
        and closed on `with` exit; the framework opens a new
        one for each call so an HSM op failure cannot leave a
        half-broken session on the token.
        """
        return self._token.open(user_pin=self._resolved.properties.user_pin)

    def _find_public_key(self, session: Session, label: str):
        keys = list(
            session.get_objects(
                {
                    pkcs11.constants.Attribute.CLASS: pkcs11.constants.ObjectClass.PUBLIC_KEY,
                    pkcs11.constants.Attribute.LABEL: label,
                },
            ),
        )
        if not keys:
            raise NoSuchKey(f"no public key with label {label!r}")
        return keys[0]

    def _find_private_key(self, session: Session, label: str):
        keys = list(
            session.get_objects(
                {
                    pkcs11.constants.Attribute.CLASS: pkcs11.constants.ObjectClass.PRIVATE_KEY,
                    pkcs11.constants.Attribute.LABEL: label,
                },
            ),
        )
        if not keys:
            raise NoSuchKey(f"no private key with label {label!r}")
        return keys[0]

    def _resolve_key_label(self, reference: KeyReference) -> str:
        if not reference.key_id:
            raise SecretConfigurationException(
                f"pkcs11 [SEC-KEY-001]: KeyReference {reference!r} "
                "has an empty key_id",
            )
        bindings = self._resolved.properties.key_bindings
        if bindings and reference.key_id in bindings:
            physical = bindings[reference.key_id]
            if not physical:
                raise SecretConfigurationException(
                    f"pkcs11 [SEC-KEY-001]: key binding for "
                    f"{reference.key_id!r} is empty",
                )
            return physical
        return reference.key_id

    def _resolve_key_label_from_string(self, label: str) -> str:
        return self._resolve_key_label(_key_ref_from_string(label))

    def _map_crypto_error(
        self,
        operation: str,
        key: KeyReference,
        error: PKCS11Error,
    ) -> SecretCryptoException:
        code = _classify_pkcs11_error(error)
        if code == "SEC-AUTH-001":
            return SecretCryptoException(
                f"pkcs11 [SEC-AUTH-001]: {operation} for key "
                f"{key.key_id!r} was rejected: {error}",
            )
        if code == "SEC-KEY-001":
            return SecretCryptoException(
                f"pkcs11 [SEC-KEY-001]: {operation} for key "
                f"{key.key_id!r} not found: {error}",
            )
        return SecretCryptoException(
            f"pkcs11 [SEC-CRYPTO-001]: {operation} for key "
            f"{key.key_id!r} failed: {error}",
        )


# --- Helpers --------------------------------------------------------------


def _classify_pkcs11_error(error: PKCS11Error) -> str:
    """Map a python-pkcs11 error to a framework error code prefix.

    python-pkcs11 surfaces PKCS#11 CKR_* error codes through
    `error.message` (e.g. "CKR_PIN_INCORRECT"). We map the
    well-known ones; anything else falls through to
    `SEC-CRYPTO-001`.
    """
    message = str(error).upper()
    if "CKR_PIN" in message or "CKR_USER_NOT_LOGGED_IN" in message:
        return "SEC-AUTH-001"
    if "CKR_OBJECT_HANDLE_INVALID" in message or "CKR_KEY_HANDLE_INVALID" in message:
        return "SEC-KEY-001"
    return "SEC-CRYPTO-001"


def _mechanism_from_string(mechanism_str: str):
    """Map a `CKM_*` string to the corresponding python-pkcs11
    Mechanism enum value.
    """
    name = mechanism_str.upper()
    mechanism = getattr(pkcs11.Mechanism, name, None)
    if mechanism is None:
        raise SecretConfigurationException(
            f"pkcs11: unsupported sign mechanism {mechanism_str!r}",
        )
    return mechanism


def _key_ref_from_string(label: str) -> KeyReference:
    return KeyReference(provider="pkcs11", key_id=label)


__all__ = ["Pkcs11SecretClient"]
