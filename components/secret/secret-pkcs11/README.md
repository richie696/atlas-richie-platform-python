# atlas-richie-secret-pkcs11

PKCS#11 / HSM backend for the Atlas Richie secret platform.
Implements the **4-SPI subset** that Java
`atlas-richie-secret-provider-pkcs11` exposes:

| SPI | Implemented? | Reason |
|---|---|---|
| `SecretOperations` | **no** | HSM has no secret storage; the framework's `operations` property on the session returns `None` |
| `KeyWrappingBackend` | yes | `CKM_WRAPKEY` (RSA-OAEP) on a public key |
| `SigningBackend` | yes | `CKM_SHA256_RSA_PKCS` or `CKM_ECDSA_SHA256` |
| `SecretBootstrapClient` | yes | Startup-time batch (HSM-side bootstrap of named DEKs) |
| `SecretProviderSession` | yes | Provider lifecycle |
| `SecretListable` | **no** | HSM has no listing capability |

HSM (Hardware Security Module) is fundamentally **crypto only** —
no storage, no listing. The wheel exposes only the operations an
HSM can perform, matching Java's `Pkcs11SecretClient` capability
set.

## Local development: SoftHSM2

```bash
brew install softhsm           # macOS
mkdir -p /tmp/softhsm/tokens
cat > /tmp/softhsm/softhsm2.conf <<'EOF'
directories.tokendir = /tmp/softhsm/tokens
objectstore.backend = file
log.level = ERROR
slots.removable = false
EOF
SOFTHSM2_CONF=/tmp/softhsm/softhsm2.conf \
  softhsm2-util --init-token --slot 0 --label "atlas-test" \
  --pin 1234 --so-pin 1234
```

Set `SOFTHSM2_CONF` to point at the config above; the test
fixtures read this and skip if SoftHSM is unreachable.

## SDK

- `python-pkcs11` — `pkcs11.lib(so_path).get_token(token_label=...)` +
  `token.open(user_pin=...)` for session

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `docs/acceptance/R-238-secret-pkcs11-handoff.md`
