# Dependency policy

1. `foundation/contracts` and component cores have no runtime dependency outside
   the Python standard library and explicitly declared sibling contracts.
2. Public APIs use component DTOs, `typing.Protocol`, standard-library streams,
   bytes, and JSON values.  They never expose framework or SDK objects.
3. An adapter may depend on one component and the external technology it adapts;
   it must not make that technology mandatory for the component.
4. Importing a package has no network, background thread, credential lookup, or
   registration side effect.
5. A missing security, schema, or transport capability fails explicitly.  It may
   never silently weaken validation or authorization.

`atlas-richie-http` is the explicit, narrow exception to the stdlib-only
component-core rule: it owns platform HTTP semantics and uses **HTTPX as its one
internal transport dependency**.  Its public API never accepts or returns HTTPX
types, and it intentionally has no provider SPI.  A future change of implementation
is an internal compatibility migration, not a runtime-selectable application option.

The dependency direction is checked by package metadata and contract tests.  Any
new runtime dependency requires an adapter boundary or an approved revision to
this policy.  [`CODE_QUALITY.md`](CODE_QUALITY.md) further defines the required
Python-native API, semantic-value, duplication, and OOP review gates.
