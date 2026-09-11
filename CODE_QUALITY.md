# Code quality constitution

This repository builds Python-native platform components.  It is not a
translation of Java or Spring conventions.  These rules are hard gates for new
public APIs, implementation changes, and reviews.

## 1. Python-native public APIs

- Follow PEP 8 naming and module conventions: `snake_case` functions and
  modules, `PascalCase` types, explicit keyword-only options where they make a
  call safer.
- Do not introduce Java-shaped APIs such as `get_*`/`set_*` accessors,
  `*Impl`, `*Manager`, `*DTO`, `*Util`, overload emulation, mutable builders,
  service locators, or global registrations.
- Use immutable dataclasses for portable protocol values.  Use `Protocol` only
  for a genuine variation boundary; a protocol is not a substitute for an
  abstraction planned “just in case”.
- Fluent composition is permitted only for progressive construction of one
  domain value, such as an immutable HTTP request.  Each link returns a new
  value, has a clear domain meaning, and does no I/O.  The final `send` or
  `execute` operation is explicit.
- Do not use `**kwargs` as an unbounded replacement for a builder.  Prefer
  named parameters or a typed options value with documented defaults.

## 2. Named semantic values

An externally observable or domain-significant value may not be an unexplained
literal at its use site.  Its single owner must give it a meaningful name.

| Value kind | Required representation |
| --- | --- |
| Closed protocol, security, lifecycle, or error states | `enum.Enum` / `enum.StrEnum` or a typed value object |
| HTTP headers, media types, OAuth/MCP parameter names, error codes | named module constants owned by the protocol module |
| Timeouts, response limits, pagination limits, retry budgets | a named policy/options value; defaults documented at the owner |
| Protocol shapes and schemas | a versioned specification resource or named schema object |

Language-structural values such as `None`, empty containers, booleans, and
`0`/`1` in local indexing or arithmetic are not automatically magic values.
The test is semantic: if changing the literal would change a business,
security, protocol, lifecycle, or compatibility decision, it must be named.

## 3. One behavior, one implementation

The same production behavior must have one authoritative implementation.

- Never copy request mapping, validation, error translation, authentication,
  pagination, serialization, or lifecycle behavior into another component or
  adapter.
- Put shared behavior in the smallest cohesive owner of that behavior; callers
  compose it instead of duplicating it.
- Do not hide duplication behind `Base*`, `Common*`, or generic utility
  classes.  Extract only a concept with a stable name, responsibility, and
  owning module.
- A defect fix belongs in the authoritative owner and must add or adjust its
  focused regression test there.

## 4. Object-oriented boundaries

- Apply SRP, OCP, LSP, ISP, DIP, and the Law of Demeter.  Domain code depends
  on its owned contracts, not concrete frameworks, SDK clients, global state,
  or application configuration.
- Every port represents a real variation (for example an OAuth token endpoint
  exchange or schema compiler).  Framework and provider details stay in an
  adapter.
- Use strategy, adapter, decorator, and pipeline forms only when their
  responsibility and ordering contract are explicit and tested.  No
  inheritance hierarchy or “future-proof” SPI is added without a current
  variation need.
- Components own behavior; applications own dependency assembly, configuration,
  process lifecycle, and business authorization decisions.

## 5. Review and verification gate

Every change must be reviewed for Pythonic API shape, named semantic values,
duplication, dependency direction, lifecycle safety, and public error
contracts.  A focused test protects the changed behavior; component and wheel
checks protect packaging boundaries.  A clean build, formatter, type check, or
mock-only test is never by itself evidence of live interoperability.

The repository remains framework-neutral and single-provider for HTTPX by
design.  Quality rules do not authorize a Python framework runtime, a
multi-provider SPI, or hidden SDK types in public APIs.
