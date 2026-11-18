# atlas-richie-testing

Shared test helpers for contract-oriented component tests. Standard library only;
not a production runtime dependency.

## What belongs here

The root `conftest.py` rule: a helper moves here once **2+ packages** need it.
Anything used by a single package stays colocated with that package's tests.

## Helpers

### Service reachability gate

```python
from atlas_richie.testing import tcp_reachable, host_port_of
from atlas_richie.testing.pytest_support import skip_unless_reachable

@pytest.fixture(scope="session")
def requires_redis(redis_url):
    skip_unless_reachable(redis_url, "Redis", env_hint="ATLAS_RICHIE_CACHE_REDIS_URL")
```

`host_port_of(url, default_port)` parses `scheme://[user:pass@]host[:port][/path]`,
bare `host:port`, and bracketed IPv6 (`redis://[::1]:6379/0`). It returns `None`
rather than guessing when the input is ambiguous — notably an unbracketed IPv6
literal, which would otherwise be misread as a `host:port` pair and make a probe
silently wrong.

`tcp_reachable` is a **port-open check, not a protocol health check**. Services
needing protocol-level verification (Vault's `/v1/sys/health`, LocalStack's health
endpoint) keep their own probes.

Consumers: `cache-redis`, `statemachine-redis`, `redis-streammq` — all three
previously carried near-identical copies of this probe.

### Deterministic clock

```python
from atlas_richie.testing import ManualClock

clock = ManualClock()                 # callable, starts at 0.0
monkeypatch.setattr(bucket, "_now_millis", staticmethod(lambda: int(clock())))
clock.advance(80)                     # units are the caller's choice
clock.set(0)                          # reset between phases
```

Replaces the ad-hoc `clock = [0.0]` / `lambda: clock[0]` pattern. Consumers:
`cache-core`'s expiry matrix; the same shape appears in `mfa-validation` and
`redis-streammq`.

### Capability assertion

`assert_capability_descriptor(descriptor)` checks the minimum public contract
(non-blank name and version). Framework-free.

## Importing

`atlas_richie.testing` exports only framework-free helpers, so importing it never
requires pytest. pytest-specific helpers live in `atlas_richie.testing.pytest_support`
and are imported explicitly from test code. A test pins this property by importing
the package with `sys.modules["pytest"] = None`.
