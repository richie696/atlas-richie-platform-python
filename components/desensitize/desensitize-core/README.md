# atlas-richie-desensitize-core

Framework-neutral data masking: nine mask types, four scenes, configurable rules,
and plaintext-role permissions. Ported from the Java `atlas-richie-desensitize-core`.

**Zero runtime dependencies.**

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

## Scope

Ported: models, properties, the eight strategies, both registries, the permission
evaluator, and `DefaultMaskingService` (string + recursive map masking).

Not ported: the `@Sensitive` Jackson annotation and annotation-driven field
resolution, `ObjectMaskingService` / `SafeLogSerializer` (reflection and JSON
adapters), the log/exception regex fallbacks, and the static `DesensitizeUtils`
global binding — the platform has no global runtime, so inject the service.
Field types resolve from the explicit `properties.fields[class_fqn][field]` map.
