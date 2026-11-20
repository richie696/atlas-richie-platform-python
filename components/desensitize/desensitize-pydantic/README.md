# atlas-richie-desensitize-pydantic

API response masking for Pydantic v2 models — fills the executor gap that `desensitize-core`
had (the counterpart of Java `desensitize-jackson`: Jackson binds the `@Sensitive` annotation).

For pydantic models, core's object-graph masking lands on `__slots__` (internal attributes) or an unmarked
`__dict__`, so field-level markers stay invisible and API responses stay in plaintext. This package supplies the missing executor.

Depends on `desensitize-core` + `pydantic` (v2). No web framework is bound.

[English](./README.md) | [简体中文](./README.zh.md)

## Field-level markers (counterpart of `@Sensitive`)

```python
from typing import Annotated
from pydantic import BaseModel
from atlas_richie.desensitize_core import MaskType, MaskScene
from atlas_richie.desensitize_pydantic import sensitive, Transient

class Address(BaseModel):
    city: str
    detail: Annotated[str, sensitive(MaskType.ADDRESS)]        # masked

class User(BaseModel):
    name: str
    phone: Annotated[str, sensitive(MaskType.PHONE)]           # masked (marker)
    address: Address                                           # nested model, recursive
    cards: list[Address]                                       # list of models, recursive
    secret_note: Annotated[str, Transient()]                   # never emitted at all
```

## Usage

```python
from atlas_richie.desensitize_pydantic import PydanticMaskingSerializer
from atlas_richie.desensitize_core import MaskScene

serializer = PydanticMaskingSerializer()
serializer.to_safe_json(user)                                  # -> str
serializer.to_safe_dict(user, MaskScene.API_RESPONSE)          # -> dict
```

To apply name-based rules, inject a configured service:

```python
from atlas_richie.desensitize_core import DefaultMaskingService, DesensitizeProperties, MaskType

serializer = PydanticMaskingSerializer(DefaultMaskingService(
    DesensitizeProperties(sensitive_keys={"password": MaskType.PASSWORD})
))
```

The masking order matches Java: name-based rules run first (`mask_map`), and the result of an
explicit marker **overrides** them — a marker is an authorial declaration. `Transient` fields never reach the output.

**Name-based rules are empty by default** (`sensitive_keys` is an empty table, same as Java): fields such
as password are plaintext unless you explicitly configure `DesensitizeProperties(sensitive_keys={"password":
MaskType.PASSWORD})`. The marker mechanism depends on no configuration at all, so declare every sensitive field with a marker.

## FastAPI integration (example; this package does not depend on FastAPI)

```python
@app.get("/users/{uid}", response_class=JSONResponse)
async def get_user(uid: int) -> JSONResponse:
    user = await load_user(uid)
    return JSONResponse(content=serializer.to_safe_dict(user))
```

To plug in a custom masking configuration, pass your own `MaskingService` (scene switches, rules
and plaintext permissions are described in `desensitize-core`).
