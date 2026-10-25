# B0.2 — Runtime database URL configuration

Status: **out-of-band PostgreSQL/MySQL URL parsing and lazy async engine construction implemented; production startup and first-run locator remain open**.

## Contract

`ConsoleDatabaseConfiguration.from_environment()` reads
`SENTINEL_CONSOLE_DATABASE_URL` without opening a connection. It accepts only
the optional async production drivers declared by the Console package:
`postgresql+psycopg` and `mysql+asyncmy`. A non-empty username, password, host,
and database are required. SQLite and synchronous SQLAlchemy drivers are not
accepted as a production fallback. Parse errors are sanitized; URL credentials
are excluded from the configuration object's representation.

`create_engine()` constructs an async SQLAlchemy engine with parameter hiding
and pool pre-ping enabled. It does not test connectivity, migrate, or own
engine lifespan. Callers remain responsible for disposing the engine.

## Risk-to-evidence matrix

| Risk | Evidence |
| --- | --- |
| Unsupported dialect or accidental SQLite fallback | Focused tests reject SQLite and synchronous PostgreSQL URLs |
| Runtime password disclosure | Tests assert password is absent from config repr |
| Wrong async driver setup | PostgreSQL/MySQL URL parsing and lazy engine-construction argument tests |
| Accidental external connection during composition | Engine factory is replaced with a test spy; no DB connection occurs |

## Focused verification

- Database runtime configuration tests: **3 passed**.
- No database server was contacted; engine construction was verified with a
  mocked SQLAlchemy engine factory.
- No browser E2E was run; it remains for the final milestone as requested.

## Remaining boundary

This is deployment-provided configuration for an already provisioned database.
It does not implement the first-run setup page's durable database-locator
write, bootstrap marker/setup-window authority, migration lifecycle, complete
Console composition, real PostgreSQL/MySQL integration, or React-to-Python
acceptance. Those remain open under B0.1/B0.2/B0.5.
