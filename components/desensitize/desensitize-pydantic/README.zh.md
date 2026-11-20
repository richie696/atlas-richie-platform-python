# atlas-richie-desensitize-pydantic

Pydantic v2 模型的 API 响应脱敏——补上 `desensitize-core` 此前的执行器缺口
（对位 Java `desensitize-jackson`：Jackson 绑定 `@Sensitive` 注解）。

core 的对象图掩蔽对 pydantic 模型会落到 `__slots__`（内部属性）或无标记的
`__dict__`，字段级标记不可见，API 响应只能明文。本包补上执行器。

依赖 `desensitize-core` + `pydantic`（v2）。不绑任何 Web 框架。

[English](./README.md) | [简体中文](./README.zh.md)

## 字段级标记（对位 `@Sensitive`）

```python
from typing import Annotated
from pydantic import BaseModel
from atlas_richie.desensitize_core import MaskType, MaskScene
from atlas_richie.desensitize_pydantic import sensitive, Transient

class Address(BaseModel):
    city: str
    detail: Annotated[str, sensitive(MaskType.ADDRESS)]        # 掩蔽

class User(BaseModel):
    name: str
    phone: Annotated[str, sensitive(MaskType.PHONE)]           # 掩蔽（标记）
    address: Address                                           # 嵌套模型递归
    cards: list[Address]                                       # 模型列表递归
    secret_note: Annotated[str, Transient()]                   # 完全不输出
```

## 使用

```python
from atlas_richie.desensitize_pydantic import PydanticMaskingSerializer
from atlas_richie.desensitize_core import MaskScene

serializer = PydanticMaskingSerializer()
serializer.to_safe_json(user)                                  # -> str
serializer.to_safe_dict(user, MaskScene.API_RESPONSE)          # -> dict
```

需要按名规则时注入配置好的服务：

```python
from atlas_richie.desensitize_core import DefaultMaskingService, DesensitizeProperties, MaskType

serializer = PydanticMaskingSerializer(DefaultMaskingService(
    DesensitizeProperties(sensitive_keys={"password": MaskType.PASSWORD})
))
```

掩蔽次序与 Java 一致：先按字段名跑规则（`mask_map`），显式标记的结果**覆盖**
之——标记是作者声明，优先于名字猜测。`Transient` 字段不进入输出。

**按名规则默认为空**（`sensitive_keys` 空表，同 Java）：password 这类字段默认
明文，需要显式配置 `DesensitizeProperties(sensitive_keys={"password":
MaskType.PASSWORD})`。标记机制不依赖任何配置，建议敏感字段一律用标记声明。

## 接入 FastAPI（示例，本包不依赖 FastAPI）

```python
@app.get("/users/{uid}", response_class=JSONResponse)
async def get_user(uid: int) -> JSONResponse:
    user = await load_user(uid)
    return JSONResponse(content=serializer.to_safe_dict(user))
```

注入自定义脱敏配置时传入你自己的 `MaskingService`（场景开关、规则、
明文权限等见 `desensitize-core`）。
