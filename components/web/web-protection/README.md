# atlas-richie-web-protection

Request protection algorithms and the container-agnostic decision SPI behind
them: HMAC request signing, nonce replay detection, login brute-force lockout,
bot User-Agent matching, IP/CIDR blacklists and request size limits — plus the
**interceptor chain** that folds per-guard verdicts into one observable
decision event.

**Zero runtime dependencies.** Sentinel already covers rate limiting and circuit
breaking; these are the request-level protections Python was missing.

## 📖 Table of Contents

- [🎯 Component Overview](#-component-overview)
  - [Key Features](#key-features)
- [🏗️ Architecture Design](#-architecture-design)
  - [Layering](#layering)
  - [The SPI Contract](#the-spi-contract)
  - [Guard → Interceptor Adapters](#guard--interceptor-adapters)
  - [Decision Event Flow](#decision-event-flow)
- [🚀 Quick Start](#-quick-start)
  - [1. Build a request context](#1-build-a-request-context)
  - [2. Drive an interceptor chain](#2-drive-an-interceptor-chain)
  - [3. Use a guard directly](#3-use-a-guard-directly)
- [📚 Interface Reference](#-interface-reference)
  - [`WebRequestContext`](#webrequestcontext)
  - [`WebFilterDecision`](#webfilterdecision)
  - [`WebInterceptor` and the Chain](#webinterceptor-and-the-chain)
  - [Attribute Names](#attribute-names)
  - [Trace ID Normalisation](#trace-id-normalisation)
  - [Degradation Strategies](#degradation-strategies)
  - [Watchdog](#watchdog)
  - [Event Bus](#event-bus)
  - [Hot Reload Registry](#hot-reload-registry)
- [🔧 Core Capabilities](#-core-capabilities)
  - [Scenario 1: One decision event for every rejection](#scenario-1-one-decision-event-for-every-rejection)
  - [Scenario 2: Adding your own interceptor](#scenario-2-adding-your-own-interceptor)
  - [Scenario 3: Degrade a failing endpoint](#scenario-3-degrade-a-failing-endpoint)
- [⚙️ Differences from the Java Baseline](#-differences-from-the-java-baseline)
- [🔧 Troubleshooting](#-troubleshooting)
- [📎 ⏱️ Sequence Diagrams](#-sequence-diagrams)
  - [Rejecting a Request](#rejecting-a-request)
  - [Passing a Request Through](#passing-a-request-through)

## 🎯 Component Overview

Ported from the Java atlas-richie-web-core protection package and its spi
package. The algorithms are unchanged; what this release adds is the
**decision contract** the Java side already had: one request context, one
interceptor chain, one decision event.

### Key Features

- ✅ **One decision event**: every rejection carries a `WebFilterDecision`
  (interceptor / key / status / reason), written to the request context and
  optionally published to a sink
- ✅ **Container-agnostic SPI**: interceptors only see a `WebRequestContext`,
  never a framework request object
- ✅ **Short-circuit, not exceptions**: an interceptor marks the context short
  and does **not** call `chain.proceed(ctx)`; exceptions stay reserved for
  genuine faults and are turned into 5xx by the adapter
- ✅ **Guard reuse**: the existing guards (signature, size, idempotency, rate
  limit, …) are wrapped as interceptors instead of being reimplemented
- ✅ **Attribute self-check**: cross-cutting flags (gateway bypass, long-lived
  path) live on the context and are checked by the interceptors that care —
  the same pattern the Java interceptors use
- ✅ **Zero runtime dependencies**: no Redis, no framework, no Spring
- ✅ **Idempotent lifecycle**: `ctx.close()` may be called any number of times

## 🏗️ Architecture Design

### Layering

| Layer | Module | Depends on | Responsibility |
| --- | --- | --- | --- |
| SPI contract | atlas_richie.web_protection.spi | stdlib only | Context, decision event, interceptor and chain protocols |
| SPI defaults | atlas_richie.web_protection.spi.support | stdlib only | `MutableWebRequestContext`, `DefaultWebInterceptorChain` |
| Guard adapters | atlas_richie.web_protection.interceptors | guards | Wraps each guard as an interceptor |
| Tracing | atlas_richie.web_protection.tracing | stdlib only | `TraceIdParser` + `TraceIdInterceptor` — trace id normalisation |
| Degradation | atlas_richie.web_protection.degrade | stdlib only | Trigger / strategy / registry / evaluator — fallback responses |
| Watchdog | atlas_richie.web_protection.hang | stdlib only | Hang event, scheduler, detection interceptor |
| Events | atlas_richie.web_protection.hook | stdlib only | Publish / subscribe bus for request and hang events |
| Hot reload | atlas_richie.web_protection.reload | stdlib only | Registry of reloadable components |
| Guards | guards / rate_limit / idempotency / matchers / trackers | stdlib only | Pure allow/deny decisions |
| Adapter | atlas-richie-web-protection-adapter-asgi | this package | Wires the chain into a framework |

The SPI layers know nothing about HTTP servers; the adapter layers know nothing
about the algorithms. That split is what makes the same chain usable from
ASGI, from a servlet bridge, or from a test.

### The SPI Contract

```mermaid
graph TB
    subgraph "Adapter (framework-aware)"
        A["ASGI middleware / servlet filter"]
    end

    subgraph "SPI (framework-agnostic)"
        B["WebRequestContext<br/>request + response + attributes"]
        C["WebInterceptorChain<br/>proceed(ctx)"]
        D["WebFilterDecision<br/>interceptor / key / status / reason"]
    end

    subgraph "Guards (pure algorithms)"
        E["SignatureVerifier"]
        F["RequestSizeGuard"]
        G["RateLimitGuard"]
        H["IdempotencyGuard"]
    end

    A -->|"builds"| B
    A -->|"drives"| C
    C -->|"runs"| E
    C -->|"runs"| F
    C -->|"runs"| G
    C -->|"runs"| H
    E -->|"deny"| D
    F -->|"deny"| D
    G -->|"deny"| D
    H -->|"deny"| D
    D -->|"written to"| B
```

### Guard → Interceptor Adapters

Every guard becomes an interceptor that owns its rejection semantics — status
code, reason, response headers and body template — exactly like the Java
interceptors do.

| Python interceptor | Java counterpart | Rejection |
| --- | --- | --- |
| `IpBlacklistInterceptor` | `AnomalyDetectionInterceptor` (IP branch) | 403 `ip_blacklisted` |
| `BotUserAgentInterceptor` | `AnomalyDetectionInterceptor` (bot branch) | 403 `bot_detected` |
| `GatewayBypassInterceptor` | `PlatformProtectionInterceptor` (gateway branch) | never rejects |
| `RequestSizeInterceptor` | `PlatformProtectionInterceptor` (size branch) | 413 / 431 |
| `LongLivedBypassInterceptor` | `LongLivedPathBypass` | never rejects |
| `LoginLockInterceptor` | `BruteForceInterceptor` | 429 `account_locked` |
| `SignatureInterceptor` | `ApiSignatureInterceptor` | 401 + verifier reason |
| `IdempotencyInterceptor` | business.`IdempotencyInterceptor` | 409 `idempotent_replay` |
| `RateLimitInterceptor` | `DistributedRateLimitInterceptor` | 429 / 401 + guard reason |

### Decision Event Flow

```mermaid
sequenceDiagram
    participant A as Adapter
    participant C as Chain
    participant I as Interceptor
    participant X as WebRequestContext
    participant S as WebDecisionSink

    A->>C: proceed(ctx)
    C->>I: intercept(ctx, chain)
    I->>X: set_attribute(DECISION_ATTRIBUTE, decision)
    I->>X: add_response_header(name, value)
    I->>X: mark_short_circuit(status, body)
    I->>S: publish(decision)
    Note over I,C: proceed is NOT called - the chain stops here
    C-->>A: returns
    A->>X: read status / headers / body
    A-->>A: write the rejection response
```

## 🚀 Quick Start

### 1. Build a request context

```python
from atlas_richie.web_protection.spi import MutableWebRequestContext

ctx = MutableWebRequestContext(
    method="POST",
    path="/api/orders",
    headers={"x-client-key": ["partner-1"], "content-length": ["128"]},
    query_params={"dry_run": ["true"]},
)
ctx.path_variables()          # {}
ctx.header("x-client-key")    # "partner-1" (first value, case-insensitive)
ctx.header_names()            # ["x-client-key", "content-length"]
```

Header values may be a list of strings or a plain string — a plain string is
treated as **one** value, never split into characters.

### 2. Drive an interceptor chain

```python
from atlas_richie.web_protection import RequestSizeGuard
from atlas_richie.web_protection.interceptors import RequestSizeInterceptor
from atlas_richie.web_protection.spi import DefaultWebInterceptorChain

chain = DefaultWebInterceptorChain([RequestSizeInterceptor(RequestSizeGuard(1_048_576, 16_384))])
chain.proceed(ctx)

if ctx.is_short_circuited:
    print(ctx.response_status, ctx.short_circuit_body)
```

### 3. Use a guard directly

Guards stay usable on their own — they return **decisions** and leave rendering
to the caller.

```python
from atlas_richie.web_protection import (
    ApiSignatureVerifier, NonceCache, LoginAttemptTracker,
    BotUserAgentMatcher, IpBlacklistEntry, RequestSizeGuard,
)

class Keys:
    def secret_for(self, client_key: str) -> bytes | None:
        return load_from_vault(client_key)

verifier = ApiSignatureVerifier(Keys(), NonceCache(ttl_seconds=300), timestamp_skew_seconds=60)
decision = verifier.verify(
    method="POST", path="/api/orders", client_key="partner-1",
    timestamp="1700000000000", nonce="abc123", signature="<hex>",
)
if decision is not None:
    deny(decision.reason)   # missing_header | bad_timestamp | timestamp_skew
                            # nonce_replay | no_secret | signature_mismatch
```

Signing canonical string: method + newline + path + newline + timestamp +
newline + nonce, HMAC-SHA256, **lower-case hex**, compared in constant time.

## 📚 Interface Reference

### `WebRequestContext`

Read-only inbound, writable outbound, plus a lifecycle. Python naming rule:
**scalars are properties, collections and lookups are methods, writes are
explicit setters.**

| Member | Kind | Meaning |
| --- | --- | --- |
| method | property | HTTP method, upper-cased |
| path | property | request path, no query string |
| header(name) | method | first value of a header, case-insensitive, None if absent |
| headers(name) | method | all values of a header, [] if absent |
| `header_names`() | method | all header names, lower-cased |
| query_param(name) | method | first value of a query parameter |
| `query_params`() | method | all query parameters |
| `path_variables`() | method | path variables resolved by the router |
| attribute(name) | method | read a cross-interceptor attribute |
| `set_attribute`(name, value) | method | write an attribute, returns the previous value |
| remove_attribute(name) | method | delete an attribute, returns the previous value |
| `response_status` | property | response status, starts at 200 |
| set_response_status(status) | method | set the response status |
| `response_headers`() | method | live view of the response headers |
| `add_response_header`(name, value) | method | add a response header (same name overwrites) |
| client_key | property | client key resolved by a key resolver |
| set_client_key(key) | method | set the client key |
| trace_id | property | trace id |
| set_trace_id(trace_id) | method | set the trace id |
| `is_short_circuited` | property | whether an interceptor short-circuited |
| `mark_short_circuit`(status, body) | method | mark the short circuit |
| `short_circuit_body` | property | short-circuit body template, None if not short-circuited |
| error | property | exception raised on this request, if any |
| set_error(error) | method | set the exception (overwrites) |
| start_nanos | property | request start time on a monotonic clock |
| close() | method | release resources — **idempotent** |

### `WebFilterDecision`

Frozen, four fields, same order as the Java record.

| Field | Type | Meaning |
| --- | --- | --- |
| interceptor | str | which interceptor decided (class name) |
| key | str or None | the decision key (rate-limit key, login key, …) |
| status | int | HTTP status of the rejection |
| reason | str | machine-readable reason (`ip_blacklisted`, `nonce_replay`, …) |

`is_deny` is true when status is 400 or more. Two factory methods mirror the Java
record: `WebFilterDecision`.rate_limit_deny(...) produces the reason
`rate_limit.exceeded` and `WebFilterDecision`.circuit_breaker_deny(...) produces
`circuit_breaker.open`.

A `WebDecisionSink` is any object with `publish(decision)` returning None.

### `WebInterceptor` and the Chain

```python
class MyInterceptor:
    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if ctx.header("x-tenant") is None:
            ctx.set_attribute(DECISION_ATTRIBUTE, WebFilterDecision(
                "MyInterceptor", None, 400, "tenant.missing"))
            ctx.mark_short_circuit(400, '{"error": "tenant.missing"}')
            return          # <- do NOT call chain.proceed(ctx)
        chain.proceed(ctx)
```

`DefaultWebInterceptorChain` drives interceptors in registration order. proceed
is a no-op when the context is already short-circuited or when the chain has
reached its end. The chain is **not thread-safe** — one instance per request.

### Attribute Names

| Constant | Value | Written by | Read by |
| --- | --- | --- | --- |
| `DECISION_ATTRIBUTE` | `platform.web.filter-decision` | every denying interceptor | your sink / hook |
| `GATEWAY_BYPASS_ATTRIBUTE` | `platform.web.gateway-bypass` | `GatewayBypassInterceptor` | `SignatureInterceptor` |
| `GATEWAY_ID_ATTRIBUTE` | `platform.web.gateway-id` | `GatewayBypassInterceptor` | your code |
| `LONG_LIVED_ATTRIBUTE` | `platform.web.long-lived` | `LongLivedBypassInterceptor` | request-level interceptors |
| `CLIENT_IP_ATTRIBUTE` | `platform.web.client-ip` | the adapter | `RateLimitInterceptor` |
| `LOGIN_KEY_ATTRIBUTE` | `platform.web.login-key` | the adapter | `LoginLockInterceptor` |

The first four names are byte-identical to the Java constants.

### Trace ID Normalisation

`TraceIdParser` normalises whatever the upstream sent into one 32-hex trace
id. `TraceIdInterceptor` applies it to a request context.

| Input | Result |
| --- | --- |
| `traceparent: 00-<32-hex>-<16-hex>-<flags>` | the 32-hex trace id, lower-cased |
| `traceparent` with a version other than `00` | ignored, falls through to the next source |
| `X-Request-Id` that is already 32 hex | returned verbatim (case preserved) |
| `X-Request-Id` shorter than 32 | lower-cased, padded to 32 with **random** hex |
| `X-Request-Id` longer than 32 | truncated to 32, lower-cased |
| neither header | a freshly generated 32-hex UUID v4 |

```python
from atlas_richie.web_protection import TraceIdInterceptor, TraceIdParser

trace_id = TraceIdParser.resolve(traceparent, request_id)   # never None
```

The interceptor writes the result to `ctx.trace_id` and to the `X-Trace-Id`
response header, then continues the chain. It runs **first**
(`ORDER = 50`, same as the Java `OtelTracingInterceptor`) so later
interceptors can read the trace id.

The padding uses **random** hex, not zeros — an upstream id is not a
predictable prefix of the normalised id.

### Degradation Strategies

A degradation strategy answers one question: **when this endpoint is in
trouble, what should the client see instead?**

| Type | Role |
| --- | --- |
| `Trigger` | `EXCEPTION` / `HIGH_LATENCY` / `CUSTOM` — what happened |
| `DegradeStrategy` | the SPI you implement: `name` / `triggers` / `order` / `matches` / `build` |
| `DegradeResult` | status + body + headers + the name of the strategy that produced it |
| `DegradeStrategyRegistry` | holds the strategies and picks the first match by `order` |
| `DegradeEvaluator` | the framework-free decision: detect trigger → select → build |

```mermaid
flowchart LR
    A["request fails or runs slow"] --> B["DegradeEvaluator.evaluate(ctx)"]
    B --> C{"degrade.skip?"}
    C -->|"yes"| D["no degradation"]
    C -->|"no"| E{"path has a route?"}
    E -->|"no"| D
    E -->|"yes"| F{"trigger detected?"}
    F -->|"none"| D
    F -->|"EXCEPTION / HIGH_LATENCY / CUSTOM"| G{"strategy matches?"}
    G -->|"yes"| H["strategy.build(trigger, ctx)"]
    G -->|"no"| I["route config or global fallback"]
    H --> J["DegradeResult → mark_short_circuit"]
    I --> J
```

Register a strategy and let it answer for the endpoints it knows about:

```python
from atlas_richie.web_protection import (
    DegradeResult,
    DefaultDegradeStrategyRegistry,
    Trigger,
)


class CachedOrders:
    def name(self) -> str:
        return "cached-orders"

    def triggers(self) -> frozenset[Trigger]:
        return frozenset({Trigger.EXCEPTION})

    def order(self) -> int:
        return 0

    def matches(self, trigger) -> bool:
        return trigger is Trigger.EXCEPTION

    def build(self, trigger, ctx) -> DegradeResult:
        return DegradeResult.of(200, '{"cached":true}', "cached-orders")


registry = DefaultDegradeStrategyRegistry()
registry.register("cached-orders", CachedOrders())
```

**Scope matters**: degradation only applies to paths that have a **route
configured** — the Java baseline treats degradation as a per-interface business
decision, not a blanket safety net. Configure `routes` (or `route_rules`) for
the endpoints you want protected; `require_route_match=False` makes every path
eligible for the global fallback instead.

The evaluator reads its inputs from the request context, so the adapter (or your
own code) can drive it:

| Attribute | Written by | Meaning |
| --- | --- | --- |
| `degrade.skip` | business code | `true` disables degradation for this request |
| `degrade.exception` | the adapter | the exception that was raised |
| `degrade.manual` | business code | `true` forces `Trigger.CUSTOM` |
| `degrade.latencyMs` | the adapter | measured latency in milliseconds |
| `degrade.hit_strategy` | the evaluator | the strategy (or route/fallback) that won |

The response body has the same shape as the Java `ApiResult.error(code, msg)`
serialisation — `{"success":false,"code":...,"msg":...}` — and the `{reason}`
placeholder is replaced by the trigger name (`exception` / `high-latency` /
`custom`).

**Not the Sentinel breaker.** Sentinel's circuit breaker
(`sentinel/slots/degrade.py`) is **flow control**: it raises
`CircuitBlocked` and refuses the call. Web degradation is **fallback**: it
answers the client with a usable response. The two do not overlap — one blocks,
the other degrades.

### Watchdog

The watchdog answers: **is this request stuck, and for how long?**

| Type | Role |
| --- | --- |
| `WatchdogScheduler` | shared scheduler: 3 daemon workers + 1 daemon timer thread |
| `WatchHandle` | the cancel token returned by `schedule()` |
| `HangEvent` | method / path / elapsed / threshold / client key / trace id / stack |
| `HangDetectionInterceptor` | registers the three watchdogs around the chain |

Three levels fire in order — `warn`, `dump`, `kill_switch` — and each level
fires **at most once** per request, so the expensive thread snapshot runs at
most once:

| Level | Threshold | Effect |
| --- | --- | --- |
| `warn` | `warn_ms` | log a warning, publish `HangEvent` |
| `dump` | `dump_ms` | log a warning plus a thread snapshot, publish `HangEvent` |
| `kill_switch` | `kill_switch_ms` | same as `dump`, then call `kill_interrupter` |

```python
from atlas_richie.web_protection import HangDetectionInterceptor

interceptor = HangDetectionInterceptor(
    warn_ms=1_000,
    dump_ms=3_000,
    kill_switch_ms=10_000,
    dump_enabled=True,
    hook_bus=bus,
)
```

Thresholds must satisfy `warn_ms <= dump_ms <= kill_switch_ms` and all be
positive — the constructor rejects anything else, because an inverted ladder
would fire the cheap level after the expensive one.

Long-lived paths (SSE, WebSocket, streaming) are skipped: if the context
carries `platform.web.long-lived`, no watchdog is registered at all.

### Event Bus

A small publish/subscribe bus for the events the platform produces.

| Type | Role |
| --- | --- |
| `HookEvent` | the marker base class every event derives from |
| `HookSubscriber` | the subscriber protocol: `on_event(event)` |
| `HookBus` | the bus protocol: `subscribe` / `publish` / `diagnostic_view` |
| `DefaultHookBus` | the default implementation |
| `RequestCompletedEvent` | published when a request ends — normal, short-circuited or failed |

```python
from atlas_richie.web_protection import DefaultHookBus, RequestCompletedEvent

bus = DefaultHookBus()
subscription = bus.subscribe(RequestCompletedEvent, my_subscriber)
bus.publish(RequestCompletedEvent.of(ctx, end_nanos))
subscription.close()
```

Three guarantees:

- **exact-type dispatch** — a subscriber of `HookEvent` does **not** receive a
  `RequestCompletedEvent`; subscribe to the concrete type
- **exception isolation** — a subscriber that raises does not stop the others
- **no subscribers, no cost** — publishing an event nobody listens for is a
  single dictionary lookup

### Hot Reload Registry

Swap a component's configuration without restarting the process.

| Type | Role |
| --- | --- |
| `Reloadable` | the SPI: `current_state()` + `accept(new_state)` |
| `ReloadEvent` | published after a successful reload |
| `HotReloadRegistry` | the registry protocol |
| `DefaultHotReloadRegistry` | the default implementation |

```python
from atlas_richie.web_protection import DefaultHotReloadRegistry

registry = DefaultHotReloadRegistry(bus)
registry.register("rate-limit", my_reloadable)
registry.reload("rate-limit")     # current_state() → accept(state)
registry.reload_all()
```

`reload` re-reads the component's own state and hands it back to it — the
component decides what to do with it. `reload_all` sweeps every registered
component and returns how many succeeded. The registry publishes a
`ReloadEvent` when a bus was supplied, so audit trails need no extra wiring.

## 🔧 Core Capabilities

### Scenario 1: One decision event for every rejection

Wire a sink once and every rejection becomes observable, whatever guard
produced it.

```python
class LoggingSink:
    def publish(self, decision: WebFilterDecision) -> None:
        log.warning("rejected by %s: %s (status=%s)",
                    decision.interceptor, decision.reason, decision.status)

middleware = ProtectionASGIMiddleware(app, decision_sink=LoggingSink())
```

The event is **not** skipped for rejected requests — the Java side has the same
red line: a rejected request must still report *why* it was rejected.

### Scenario 2: Adding your own interceptor

Interceptors are plain objects. Compose your own chain without touching the
framework:

```python
chain = DefaultWebInterceptorChain([
    TenantInterceptor(),
    *middleware.interceptors,
])
```

### Scenario 3: Degrade a failing endpoint

Register a strategy, hand the evaluator to the adapter, and the client gets a
fallback instead of a 500.

```python
from atlas_richie.web_protection import (
    DegradeConfig,
    DegradeEvaluator,
    DefaultDegradeStrategyRegistry,
    RouteFallback,
)
from atlas_richie.web_protection_adapter_asgi import ProtectionASGIMiddleware

registry = DefaultDegradeStrategyRegistry()
registry.register("cached-orders", CachedOrders())

evaluator = DegradeEvaluator(
    registry,
    DegradeConfig(routes={"/api/v1/orders": RouteFallback(pattern="/api/v1/orders")}),
)

middleware = ProtectionASGIMiddleware(app, degrade_evaluator=evaluator)
```

When the endpoint raises, the client receives the strategy's response and the
exception never reaches it. With no strategy registered, the route
configuration produces the fallback body instead — the same shape as the Java
`ApiResult.error(code, msg)` serialisation.

**What it costs**: the adapter buffers the downstream response while the
decision is made, so the response is no longer streamed. Keep SSE and
long-polling endpoints out of the degraded scope.

## ⚙️ Differences from the Java Baseline

| Topic | Java | Python | Why |
| --- | --- | --- | --- |
| Decision attribute | one name per interceptor (platform.web.signature-decision, …) | one unified name `platform.web.filter-decision` | the BACKLOG asks for a **unified** decision event, and Python has no hook bus yet — the attribute is the only hand-off channel |
| Event publication | `HookBus` (publish is never skipped by a short circuit) | optional `WebDecisionSink` + the context attribute | the hook bus is a separate BACKLOG item |
| Rate-limit reason | fixed `rate_limit.exceeded` | `rate_limited` / `gateway_identity_missing` / `client_unidentified` | keeps "quota exhausted" distinguishable from "identity missing" |
| Gateway bypass | hard-coded, cannot be disabled | configurable header name (default `x-forwarded-from-gateway`) | keeps the Java default contract while staying operable |
| Circuit breaker | `CircuitBreakerInterceptor` | not ported | the breaker state machine is not a request-level guard |
| Login outcome learning | `RequestLifecycleHookInterceptor` | still in the adapter | the hook bus is a separate BACKLOG item |
| Duplicate headers | `getHeader()` returns the first value | `ctx.header()` returns the first value; `header_map_from_context()` returns the last | the context follows Java; the single-value map keeps the ASGI adapter's existing `header_map()` contract |
| Trace interceptor name | `OtelTracingInterceptor` | `TraceIdInterceptor` | the Java name promises OTel but the class never touches the OTel SDK; this port has no OTel dependency at all, so the name says what it does |
| prefer-w3c switch | documented in the Java README, **not implemented in the Java source** | not implemented either | the Java code always prefers traceparent; this port follows the code, not the README |
| Whitespace handling | `String.trim()` / `String.isBlank()` | ASCII whitespace only | identical for realistic input; only exotic spaces such as U+00A0 differ |
| Trace interceptor registration | skipped when the observability starter is present | always available | Java's legacy web tracing must not sit beside the OTel trace boundary; the same rule applies once the Python observability component lands |
| Degrade placement | `DegradeInterceptor` sits on the chain; the chain tail is the business call | a framework-free `DegradeEvaluator`; the adapter calls it around the app invocation | the Python chain runs **before** the app, so a chain element cannot observe the business result |
| Degrade body | `ApiResult.error(code, msg).toJson()` | the same JSON shape, without the `ApiResult` contract class | the Python platform has no `ApiResult` yet |
| Bean fallback | `fallbackBean` / `fallbackMethod` reflect into a Spring bean | not ported — register a `DegradeStrategy` instead | Python has no "reflect into a bean by name" idiom |
| Global fallback | unreachable in the Java source — the evaluator returns early when no route matches | reachable via `require_route_match=False` | the Java branch is dead code; the switch makes it usable without changing the default |
| Hang kill switch | `Thread.interrupt()` on the business thread | optional `kill_interrupter` callback, off by default | CPython has no safe way to interrupt a running thread |
| Hang stack capture | `Thread.currentThread()` inside the watchdog callback — the **watchdog's** stack | the monitored business thread's stack | the Java capture is off by one thread |
| Event bus | `InterceptingFilter` always creates a bus | no bus unless one is passed | an empty bus costs a lookup per request |
| Hot-reload name | `default String name()` → class name | optional `name()`, falls back to the class name | same semantics, but the name is not required |

The IP-blacklist hardening deviation from the Java side is unchanged:
Java's `IpBlacklistEntry` resolves hostnames through DNS, which turns a
blacklist check into an outbound name query. This port accepts IP literals
only, so a hostname never matches.

## 🔧 Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| The chain never rejects anything | guards were never wrapped into interceptors | build the chain through the adapter, or add the interceptor yourself |
| `ctx.attribute(DECISION_ATTRIBUTE)` is None after a rejection | the interceptor was not used, or a different attribute name was read | use the exported constant, not a literal |
| A long-lived (SSE) path is still rejected | the IP blacklist runs before the long-lived bypass | that is intentional — the blacklist applies to every path |
| A custom `deny_renderer` output changed | the renderer must return bytes | the adapter re-encodes the body as UTF-8; return bytes to keep them byte-identical |
| Rejections are counted but never reported | no sink was configured | pass `decision_sink`=... to the middleware |
| A degraded endpoint still returns 500 | the evaluator was never handed to the adapter | pass `degrade_evaluator=`... to the middleware |
| Degradation never triggers | the path has no route configured, or no trigger was detected | configure `routes` (or set `require_route_match=False`) and inspect the `degrade.` attributes |
| A slow endpoint is not degraded | the latency threshold applies to the whole downstream call | compare the measured time with `degrade.latencyMs` |
| The SSE response arrives all at once | degradation buffers the downstream response | keep streaming endpoints out of the degraded scope |
| The watchdog never fires | the request finished before the threshold, or the path is long-lived | long-lived paths skip the watchdog entirely |

## 📎 ⏱️ Sequence Diagrams

### Rejecting a Request

```mermaid
sequenceDiagram
    participant Client
    participant MW as ASGI middleware
    participant Chain
    participant I as SignatureInterceptor
    participant X as WebRequestContext

    Client->>MW: POST /api/orders (bad signature)
    MW->>X: build context
    MW->>Chain: proceed(ctx)
    Chain->>I: intercept(ctx, chain)
    I->>X: set_attribute(DECISION_ATTRIBUTE, decision)
    I->>X: mark_short_circuit(401, body)
    Note over I,Chain: chain.proceed is NOT called
    Chain-->>MW: returns
    MW-->>Client: 401 + body + headers
```

### Passing a Request Through

```mermaid
sequenceDiagram
    participant Client
    participant MW as ASGI middleware
    participant Chain
    participant I as Interceptors
    participant App as Downstream app

    Client->>MW: GET /api/orders
    MW->>Chain: proceed(ctx)
    Chain->>I: intercept(ctx, chain)
    I->>Chain: chain.proceed(ctx)
    Chain-->>MW: chain exhausted, not short-circuited
    MW->>App: call the app
    App-->>Client: 200

### Degrading a Failing Request

```mermaid
sequenceDiagram
    participant Client
    participant MW as ASGI middleware
    participant App as Downstream app
    participant E as DegradeEvaluator
    participant S as Strategy

    Client->>MW: GET /api/v1/orders
    MW->>App: call the app (response buffered)
    App-->>MW: RuntimeError
    MW->>E: evaluate(ctx)
    E->>E: detect trigger (EXCEPTION)
    E->>S: matches(EXCEPTION)
    S-->>E: DegradeResult(503, body)
    E->>MW: mark_short_circuit(503, body)
    MW-->>Client: 503 + fallback body
```
```
