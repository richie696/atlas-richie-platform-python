# R-241: atlas-richie-secret-kmip — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-kmip` (6 main files / 2 test
files) collapsed into a single Python wheel with 4 source
files + 5 test files.

## Public symbol list

### `ttlv.py` (13)
- `Element` — NamedTuple (tag, type, value)
- 5 type constants: `STRUCTURE` / `INTEGER` / `ENUMERATION` / `TEXT` / `BYTE_STRING`
- 6 codec functions: `element` / `structure` / `integer` / `enumeration` / `text` / `bytes_`
- 2 decoders: `children` / `first` (recursive lookup)

### `properties.py` (1)
- `KmipSecretProperties` — pydantic-settings, env_prefix `ATLAS_RICHIE_SECRET_KMIP_`

### `configuration.py` (2)
- `ResolvedKmipConfiguration` — frozen dataclass (provider_id, properties, configuration_hash, capability)
- `KmipConfigurationResolver` — endpoint + protocol version + binding validation, SHA-256 hash

### `client.py` (1 public)
- `KmipSecretClient` — 2-SPI composite (KeyWrappingBackend via AES-KWP + SecretProviderSession)
- Plus internals re-exported for tests: `_parse_endpoint`, `_build_encrypt_request`, `_build_decrypt_request`, `_parse_response`, `_send_request`, `_retry_io`, `_WRAPPING_ALGORITHM`

### `factory.py` (2)
- `KmipClientFactory` — `ssl.SSLContext` builder from trust/key stores
- `KmipSecretProviderFactory` — framework `SecretProviderFactory` entry

**Total: ~19 public symbols** (1:1 with the Java 6-file module's surface).

## Test count

**54 tests, 54 passed** in 0.97s.

- `test_kmip_ttlv.py` — 13 tests (5 types round-trip, nested structures, padding, error paths)
- `test_kmip_response.py` — 6 tests (success / non-zero status / mismatched-op / ambiguous batch / missing data)
- `test_kmip_endpoint.py` — 11 tests (default port, IPv4 / IPv6 literal, https scheme, retry policy transient / permanent / SSL)
- `test_kmip_configuration.py` — 16 tests (endpoint / protocol version / key bindings / capability / hash)
- `test_kmip_integration.py` — 8 tests (real KMIP mock server, TLS round-trip wrap/unwrap, UniqueID mismatch, descriptor, close idempotency)

## Test approach — real KMIP mock server

`test_kmip_integration.py` spins up a real TLS KMIP mock
server (matching the local-emulator pattern from R-238
`SoftHSM2`):

1. Generate a self-signed RSA-2048 cert + key via
   `cryptography` (test dep)
2. Write to temp PEM files; `ssl.SSLContext` loads them
3. Spawn a `threading.Thread` running `socket.create_server` + `ssl.SSLContext.wrap_socket`
4. Server parses the TTLV-encoded request, looks up the
   `UNIQUE_IDENTIFIER`, and produces a mock response
   (Encrypt appends `:<uid>`; Decrypt verifies the suffix)
5. Client connects, sends the raw TTLV, parses the
   response, and verifies the round-trip

No real KMIP server required. No MagicMock — every byte
exercises the framework's data path.

## Java → Python translation table

| Java | Python |
|---|---|
| `KmipTtlv.java` (60 lines, TTLV codec) | `ttlv.py` (1:1 line-for-line port) |
| `KmipSecretProperties.java` (Spring `@ConfigurationProperties`) | `KmipSecretProperties` (pydantic-settings, env injection) |
| `KmipSecretConfiguration.java` (validation + hash) | `KmipConfigurationResolver` + `ResolvedKmipConfiguration` |
| `KmipSecretClient.java` (112 lines, 2-SPI composite + TLS transport + retry) | `KmipSecretClient` (2-SPI composite, `ssl.SSLContext` transport, retry policy) |
| `KmipSecretBootstrapProviderFactory.java` (single line) | `KmipSecretProviderFactory` (framework entry) |
| `KmipSecretAutoConfiguration.java` (Spring `@AutoConfiguration`) | (N/A — Spring-specific) |

## Notable adaptations (Pythonic 1:1)

1. **TTL length validation in client** — Java's
   `ByteBuffer.wrap(header, 4, 4).getInt()` returns a
   signed int; the Java code checks `length < 0`. The
   Python `struct.unpack(">I", ...)` returns an unsigned
   int; we add the `< 0` check explicitly (in practice a
   `>I` 32-bit value can't be negative, but the cap at
   16 MB still holds).

2. **Wire format is raw TTLV, no length prefix** — both
   client and mock server send/expect raw TTLV. The Java
   client's `out.write(request)` (no `writeInt(len)`)
   confirms this; the 4 bytes after the 4-byte "header"
   Java reads are the TTLV's own 4-byte length field, not
   a separate length prefix. Initial mock-server
   implementation added a 4-byte length prefix; caught
   by the round-trip test and corrected.

3. **`ssl.SSLSocket.recv` requires `bytes`, not `memoryview`**
   — Python's stdlib `socket` accepts `memoryview` for
   `recv_into`, but `ssl.SSLSocket.recv` does not. The
   `_read_exact` helper accumulates `bytes` chunks
   instead. This is a Python-specific subtlety that has
   no Java analog.

4. **`SecretBackend` placeholder** — Java has no
   `SecretBackend.KMIP` enum value (KMIP is a
   key-management protocol, not a backend enum). Python
   reuses `SecretBackend.PKCS11` as a placeholder for
   observability, matching the Java de facto convention.

5. **Self-signed cert via `cryptography` test dep** —
   R-238 PKCS#11 uses real `SoftHSM2`; R-241 KMIP needs
   a TLS server and has no analog. `cryptography` is
   already an opt-in `[crypto]` extra on `secret-core`,
   so adding it to the test extra of `secret-kmip` has
   no impact on production dependencies.

## Blocked

- **Real KMIP server integration** — would require a
  running KMIP 2.1 server (HashiCorp Vault KMIP secrets
  engine, PyKMIP server, or commercial). Marked as
  `integration` in `pyproject.toml` markers; documented
  in the README; skipped locally without env override.
  The TTLV codec + transport layer are exercised against
  the in-process mock server, which mirrors the
  one-shot Java `sendOnce` semantics exactly.
