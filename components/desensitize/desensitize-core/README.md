# atlas-richie-desensitize-core

Framework-neutral data masking: nine mask types, four scenes, configurable rules,
and plaintext-role permissions. Ported from the Java `atlas-richie-desensitize-core`.

**Zero runtime dependencies.**

[English](./README.md) | [简体中文](./README.zh.md)

## Usage

```python
from atlas_richie.desensitize_core import (
    DefaultMaskingService, DesensitizeProperties, MaskScene, MaskType,
)

service = DefaultMaskingService()
service.mask("13812345678", MaskType.PHONE)          # '138****5678'
service.mask("alice@example.com", MaskType.EMAIL)    # 'a***@example.com'

props = DesensitizeProperties(sensitive_keys={"phone": MaskType.PHONE, "email": MaskType.EMAIL})
service = DefaultMaskingService(props)
service.mask_map({"phone": "13812345678", "nested": {"email": "a@b.com"}}, MaskScene.API_RESPONSE)
```

## Defaults per type

| Type | keep left | keep right | mask length |
| --- | --- | --- | --- |
| `PHONE` | 3 | 4 | actual replaced length |
| `ID_CARD` | 6 | 4 | actual replaced length |
| `BANK_CARD` | 4 | 4 | fixed grouped format (see below) |
| `NAME` | 1 | 0 | actual replaced length |
| `ADDRESS` | 6 | 0 | actual replaced length |
| `API_KEY` | 4 | 4 | **4** (fixed, hides real length) |
| `EMAIL` / `PASSWORD` / `CUSTOM` | 0 | 0 | strategy-specific |

## Behaviours preserved from Java on purpose

- `BANK_CARD` strips ASCII whitespace, then emits `first4 + " **** **** " + last4`.
  It **ignores** `mask_char` and the keep counts. Inputs with ≤ 8 digits are fully
  masked to the *original* length (including any spaces).
- `EMAIL` hard-codes `***` and keeps the domain untouched. A single-character
  local part is kept in full. Without a usable `@`, the output is `mask_char`
  repeated `min(len, 3)` times.
- `PASSWORD` is fully masked and never shorter than 6 characters, so a short
  password does not leak its length.
- Keep-edge types mask the **entire** value when `keep_left + keep_right >= len`.
- Whitespace stripping in `BANK_CARD` uses Java's ASCII-only `\s`, not Python's
  Unicode-aware `\s`.
- `AUDIT` inherits the **LOG** scene's sensitive-key overrides (a Java quirk).

## Switches and permissions

`DesensitizeProperties.enabled` and per-scene switches short-circuit to plaintext.
`DefaultMaskPermissionEvaluator` also returns plaintext when permission control is
enabled and the context carries a role listed in `permission.plain_text_roles`.
Inject your own `MaskPermissionEvaluator` to plug in real RBAC.

## Object graphs and log-safe serialization

`SafeLogSerializer` renders any payload as log-safe JSON, masking as it goes:

```python
from dataclasses import dataclass
from atlas_richie.desensitize_core import (
    DefaultMaskingService, MaskRuleRegistry, MaskScene, MaskType,
    SafeLogSerializer, SensitiveLogArg, sensitive_field, transient_field,
)

@dataclass
class User:
    name: str
    phone: str = sensitive_field(MaskType.PHONE)
    email: str = sensitive_field(MaskType.EMAIL, scenes=(MaskScene.LOG,))
    secret: str = transient_field(default="hidden")

props = DesensitizeProperties(sensitive_keys={"phone": MaskType.PHONE})
service = DefaultMaskingService(props)
serializer = SafeLogSerializer(service, MaskRuleRegistry(props))

serializer.to_safe_json(User("张三丰", "13812348000", "a@b.com"))
serializer.to_safe_json(payload, MaskScene.API_RESPONSE)
serializer.to_safe_string({"phone": "13812348000"})

logger.info("login for %s", SensitiveLogArg.phone("13812348000"))  # masked in the log
```

Handles scalars, mappings, lists/tuples/sets, dataclasses, and plain objects with
`__dict__` or `__slots__`. Field markers come from dataclass metadata (Java uses
the `@Sensitive` annotation); `ClassVar` and `transient_field` are skipped, matching
Java's skip of static and transient fields. Without a marker, the
`properties.fields[class_fqn][field]` mapping applies. Only **string** fields are
masked, as in Java.

`DefaultObjectMaskingService` is the thin facade over the serializer, matching the
Java service shape.

### Bounded recursion

Depth is capped at 8 (Java's `MAX_DEPTH`) and cyclic mappings are replaced with a
`[circular]` marker. `mask_map` itself is bounded too — Java's version recurses
without a limit, so a self-referencing payload would hang the caller. A log
serializer must terminate.

### Deliberate deviations

- **`SensitiveLogArg.__str__` masks.** Java's `toString()` returns the **raw** value
  and relies on a Logback turbo filter to mask it. Python's logging has no such
  interception, so returning raw would leak credentials. Masking happens in
  `__str__` using an injected service or a default one; `raw_value` is an explicit
  opt-in accessor and `__repr__` never shows the value.
- **Valid JSON escaping.** Java's hand-rolled `quote` escapes only `" \ \n \r \t`,
  leaving other control characters raw and emitting invalid JSON. This uses proper
  JSON escaping.
- **The caller's scene propagates into nested values.** Java's `writeMap` hardcodes
  `LOG` for nested entries, so an `API_RESPONSE`-only sensitive key nested one level
  down would be left unmasked. Honouring the caller's scene is the actual contract.

## Scope

Ported: models, properties, the eight strategies, both registries, the permission
evaluator, `DefaultMaskingService` (string + recursive map masking), field markers,
`SafeLogSerializer`, `DefaultObjectMaskingService` and `SensitiveLogArg`.

Not ported: the log/exception regex fallbacks.

Ported in sibling packages: `desensitize-jackson` is `desensitize-pydantic`;
`desensitize-logging` is `desensitize-logging` (MDC context, the log-arg and
MDC interception points, and the logging masking SPI).
