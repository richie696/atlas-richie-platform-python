# Sentinel Console database adapter contract

## Scope

The Console supports SQLite, PostgreSQL, and MySQL through SQLAlchemy. Provider
behavior belongs in infrastructure adapters; application use cases and SQL
stores must not branch on a database vendor. The stable Console Facade owns URL
validation, adapter selection, lifecycle handoff, and stable error mapping.

Database support is extended by an explicitly composed, built-in Python
adapter. This is not a promise of arbitrary third-party runtime plugin
discovery. A new provider necessarily needs provider-specific code and an
optional driver dependency; the isolation contract is that the code stays at
the provider boundary rather than spreading through business persistence.

The application layer owns capability-sized persistence Ports and must not
import SQLAlchemy, database drivers, or Infrastructure implementations. SQL
stores under Infrastructure implement those Ports with SQLAlchemy's portable
expression and transaction APIs. A separate dialect Adapter is needed only
where provider behavior is genuinely different (for example, migration locks,
upsert semantics, or schema types); do not create a vendor Adapter around each
generic CRUD method. Replacing SQLAlchemy with a non-SQL persistence technology
would require new Port implementations and the same capability contracts, but
is a different change from adding a SQLAlchemy dialect.

## Responsibilities

| Concern | Owner | Contract |
| --- | --- | --- |
| Runtime SQLAlchemy engine creation | `DatabaseEngineAdapter` | Map one driver URL and security options to a lazy engine. |
| First-run engine creation | Same engine adapter | Validate the typed setup candidate, require the approved target when remote, and return only durable locator facts. |
| Read-only connection check | `BootstrapDatabaseCheckAdapter` | Probe without migration/write; return only the bounded `reachable` / stable failure result. |
| Provider selection | `DatabaseEngineAdapterRegistry` and `BootstrapDatabaseCheckAdapterRegistry` | Explicit construction; duplicate keys and unknown providers fail closed. |
| Setup flow and persistence orchestration | Console Facades / application use cases | Do not import driver modules or contain vendor branches. |
| Schema lifecycle | Alembic migration layer plus provider-specific migrations only when proven necessary | Startup and first-run behavior must be verified against that dialect; registration alone is not support. |

## Adding a built-in provider

1. Add a stable `BootstrapDatabaseKind` value and update the setup API schema and
   Dashboard's selectable provider metadata. Unknown values remain rejected.
2. Add one `DatabaseEngineAdapter` implementation with explicit URL parsing,
   lazy runtime engine creation, driver error normalization, and first-run target
   policy. Remote providers must preserve DNS/IP pinning and hostname-verified
   TLS; local providers must use deployment-owned paths and never accept a path
   from the browser.
3. Add one `BootstrapDatabaseCheckAdapter` implementation. It must be read-only,
   bounded, redact credentials/driver diagnostics, and map failures to the
   stable Console result vocabulary.
4. Register the adapters in the central explicit composition functions. Keep
   driver selection out of repositories, SQL stores, and application services.
   Duplicate registration is a startup error, not last-one-wins behavior.
5. Add the driver's optional dependency extra and document the minimum supported
   server/driver versions. The default extra set must not import optional drivers.
6. Verify every migration and query construct used by the Console (transaction
   boundaries, uniqueness, locking/CAS, JSON/sequence behavior, indexes,
   timestamps, and result mapping). Add dialect-specific migrations only when
   the shared migration cannot express the required semantics safely.
7. Run the shared adapter contract tests, then a disposable real-provider
   acceptance for connection check, first initialization, migration, identity
   persistence, restart/readback, transaction/concurrency semantics, and
   cleanup. A synthetic adapter test proves the extension seam only; it does
   not qualify a new database for production support.
8. Update the supported-dialect matrix and installed-wheel tests. Do not mark a
   provider supported until its driver extra, migration, security policy, and
   real-provider acceptance all pass.

## Pattern decision

The current design uses **Adapter + Registry + Facade**: Adapter isolates
provider behavior, Registry performs explicit selection, and Facades keep
composition/connection-check call order out of use cases. Template Method is
not used: local SQLite bootstrap and remote PostgreSQL/MySQL have materially
different path ownership, DNS pinning, TLS, and connection lifecycles, so there
is no safe shared superclass algorithm to freeze. If a future provider reveals
a genuinely common lifecycle, reassess with provider evidence instead of
adding inheritance preemptively.

## Current support boundary

The registered production providers are SQLite, PostgreSQL, and MySQL. The
FutureDialect tests in `tests/test_database_runtime.py` and
`tests/test_bootstrap_database_connector.py` use synthetic adapters to verify
registry selection, URL/engine delegation, bootstrap target handoff, stable
check result, and secret-safe representations. They do not add a fourth
supported database and do not replace disposable PostgreSQL/MySQL acceptance.
