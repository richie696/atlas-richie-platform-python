# atlas-richie-secret-kmip

KMIP 2.1 backend (Key Management Interoperability Protocol) for
the Atlas Richie secret platform. Implements a **2-SPI
composite** (`KeyWrappingBackend` via AES-KWP Encrypt/Decrypt
operations + `SecretProviderSession`); 1:1 functional parity
with Java `atlas-richie-secret-provider-kmip`.

## Scope

KMIP is a **key management** protocol, not a secret store:

- ✅ `KeyWrappingBackend` — wrap / unwrap DEKs via KMIP
  `Encrypt` (op=31) and `Decrypt` (op=32) operations, using
  AES-KWP (`CryptoAlgorithm.AES = 3` +
  `BlockCipherMode.KEK_WRAPPING = 12`).
- ❌ `SecretOperations` — KMIP servers do not store application
  secrets; only managed symmetric keys.
- ❌ `SecretListable` — KMIP 2.1 has no list API in our
  minimal scope.
- ❌ `SecretWriter` / `SecretDeletable` — read-only wrap backend.

The session's `operations` / `writer` / `deletable` properties
all return `None`, matching the PKCS#11 HSM pattern (R-238).

## TTLV codec

`KmipTtlv` is a minimal Type-Length-Value codec covering only
the subset of KMIP 2.1 the wrap/unwrap operations need:

- `STRUCTURE (0x01)` — nested children, 8-byte aligned
- `INTEGER (0x02)` / `ENUMERATION (0x05)` — 32-bit big-endian
- `TEXT (0x07)` — UTF-8
- `BYTE_STRING (0x08)` — raw bytes
- `children(bytes)` — recursive decoder
- `first(elements, tag, type)` — first match (recursive)

Mirrors Java `KmipTtlv.java` 1:1.

## Transport

`KmipSecretClient` connects to a `kmips://host:port` endpoint
over TLS (SSLContext built from the configured trust store /
key store). Each request:

1. Open new TLS connection
2. Send 4-byte length-prefixed request (big-endian)
3. Read 8-byte header (length + TTLV)
4. Read body (padded to 8-byte boundary)
5. Close connection (KMIP 2.1 supports simple one-shot)

Retry policy: only transient `OSError` retries; `SSLError`
on handshake is permanent (trust chain mismatch).

## Install

```bash
# Pure stdlib; no SDK required
pip install atlas-richie-secret-kmip
```

## Quick start

```python
from atlas_richie.secret_kmip import (
    KmipSecretProperties,
    KmipSecretProviderFactory,
)

properties = KmipSecretProperties(
    endpoint="kmips://kmip.example:5696",
    trust_store="/etc/ssl/certs/kmip-ca.pem",
    protocol_major=2,
    protocol_minor=1,
    key_bindings={"default-envelope": "key-abc-123"},
)
factory = KmipSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_KMIP_`; fields cover
endpoint / trust_store / trust_store_password / key_store /
key_store_password / protocol_major (1-2) / protocol_minor (0-9)
/ key_bindings.

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-pkcs11` — sibling HSM backend wheel
  (similar 2-SPI scope)
- `docs/acceptance/R-241-secret-kmip-handoff.md` — design + verification
