# R-242: atlas-richie-secret-barbican — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-barbican` (5 main files, 258
LOC) collapsed into a single Python wheel with 4 source
files.

## Public symbol list

### `properties.py` (4)
- `AuthType` — StrEnum (`TOKEN` / `TOKEN_FILE`)
- `BarbicanAuth` — frozen dataclass (type + token + token_file)
- `BarbicanSecretMapping` — frozen dataclass (logical → physical id)
- `BarbicanSecretProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_BARBICAN_`

### `configuration.py` (2)
- `ResolvedBarbicanConfiguration` — frozen dataclass
- `BarbicanConfigurationResolver` — endpoint / auth / secrets
  validation, SHA-256 hash

### `client.py` (2)
- `BarbicanSecretMetadata` — frozen response dataclass
- `BarbicanSecretClient` — 3-SPI composite (SecretOperations +
  SecretBootstrapClient + SecretProviderSession)

### `factory.py` (2)
- `BarbicanClientFactory` — `httpx.Client` builder
- `BarbicanSecretProviderFactory` — framework entry

**Total: 10 public symbols** (matches the Java 5-file module).

## Test count

**32 tests, 32 passed** in 0.23s.

- `test_barbican_configuration.py` — 16 tests (endpoint
  scheme, auth modes, project_id, secrets mappings, hash)
- `test_barbican_client.py` — 16 tests (read / metadata /
  401/403/500 error mapping / bootstrap missing policy /
  descriptor / close / token file)

## Test approach — `httpx.MockTransport`

OpenStack Barbican has no local emulator. Tests use
`httpx.MockTransport` (in-process; the entire data path
goes through real `httpx` internals — not MagicMock). Each
test wires a `BarbicanSecretClient` over a `httpx.Client`
that wraps a `MockTransport`; the transport's handler
returns canned responses for each expected URL. This
exercises the full 4-step read flow:

1. Resolve logical → physical id
2. `GET /v1/secrets/{id}` → JSON metadata
3. `GET /v1/secrets/{id}/payload` → raw bytes
4. Build `SecretValue` with metadata

## Java → Python translation table

| Java | Python |
|---|---|
| `BarbicanSecretProperties.java` (47 lines, Spring `@ConfigurationProperties`) | `BarbicanSecretProperties` (pydantic-settings, env injection) |
| `BarbicanConfiguration.java` (24 lines, validate + hash) | `BarbicanConfigurationResolver` (validation + SHA-256 hash) |
| `BarbicanSecretClient.java` (171 lines, 3-SPI composite + HTTP) | `BarbicanSecretClient` (3-SPI composite, `httpx.Client` transport) |
| `BarbicanSecretBootstrapProviderFactory.java` (9 lines) | `BarbicanSecretProviderFactory` (framework entry) |
| `BarbicanSecretAutoConfiguration.java` (7 lines, Spring) | (N/A — Spring-specific) |

## Notable adaptations (Pythonic 1:1)

1. **HTTP client** — Java uses JDK `HttpClient` + a custom
   `RemoteHttpClientFactory` + `HttpResponseRetryExecutor`;
   Python uses `httpx.Client` (which already handles
   transient retries internally) + a `httpx_factory` test
   seam for `httpx.MockTransport`. The retry semantics
   differ but the framework-level error mapping (401/403/
   404 → named `SEC-AUTH-*` / `SEC-STORE-001`) is preserved
   1:1.

2. **JSON parsing** — Java uses Jackson's `ObjectMapper`;
   Python uses the stdlib `json` module. SDK types never
   cross the public boundary (the response is unpacked
   into `BarbicanSecretMetadata` immediately).

3. **Auth abstraction** — Java's `Authentication` /
   `AuthenticationType` Lombok-style nested class becomes
   two flat pydantic fields (`auth_type` + `auth_token` /
   `auth_token_file`) with a `BarbicanAuth` aggregate
   built by `BarbicanSecretProperties.auth()`. This
   matches pydantic-settings' flat-env-injection
   constraint (nested models don't work with env vars).

4. **SecretBackend enum** — `SecretBackend.BARBICAN` is
   already in the framework's enum (used since R-240 added
   it for the broader "remote secret backend" surface).

5. **`bootstrap(RequiredWhen)` semantics** — Java's
   `MissingPolicy.LOCAL` doesn't exist in the Python
   framework; R-242 uses the framework's `RequiredWhen`
   enum (R-240 introduced this adaptation). Missing
   bindings with `OPTIONAL` / `LAZY` `required_when` are
   silently dropped into the `missing` tuple;
   `STARTUP` / `PRODUCTION_ONLY` raise `SEC-STORE-001`.

## Blocked

- **Real Barbican integration tests** — would require an
  OpenStack cluster with Barbican + Keystone. Marked as
  `integration` in `pyproject.toml` markers; documented in
  the README; skipped locally without env override.
