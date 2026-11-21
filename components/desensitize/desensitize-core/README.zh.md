# atlas-richie-desensitize-core

框架无关的数据脱敏：九种掩码类型、四个场景、可配置规则，以及明文角色权限。
移植自 Java 的 `atlas-richie-desensitize-core`。

**零运行时依赖。**

[English](./README.md) | [简体中文](./README.zh.md)

## 用法

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

## 各类型的默认值

| 类型 | 保留左侧 | 保留右侧 | 掩码长度 |
| --- | --- | --- | --- |
| `PHONE` | 3 | 4 | 实际被替换的长度 |
| `ID_CARD` | 6 | 4 | 实际被替换的长度 |
| `BANK_CARD` | 4 | 4 | 固定分组格式（见下） |
| `NAME` | 1 | 0 | 实际被替换的长度 |
| `ADDRESS` | 6 | 0 | 实际被替换的长度 |
| `API_KEY` | 4 | 4 | **4**（定长，隐藏真实长度） |
| `EMAIL` / `PASSWORD` / `CUSTOM` | 0 | 0 | 由策略自行决定 |

## 刻意保留的 Java 行为

- `BANK_CARD` 先剥掉 ASCII 空白，再输出 `first4 + " **** **** " + last4`。
  它**忽略** `mask_char` 与保留位数。输入不足 8 位数字时，按**原始长度**
  （含空格）整体掩码。
- `EMAIL` 硬编码 `***`，域名原样保留。local 段只有一个字符时完整保留。没有
  可用的 `@` 时，输出 `mask_char` 重复 `min(len, 3)` 次。
- `PASSWORD` 整体掩码，且长度**永不少于 6 位** —— 短密码也不会泄露长度。
- 保留边缘的类型在 `keep_left + keep_right >= len` 时**整段**掩码。
- `BANK_CARD` 的空白剥离用 Java 只认 ASCII 的 `\s`，不是 Python 感知 Unicode
  的 `\s`。
- `AUDIT` 继承 **LOG** 场景的敏感键覆盖（Java 的一个怪癖）。

## 用 `CUSTOM` 扩展

`MaskType.CUSTOM` **没有内置策略** —— 默认注册表对它抛 `RuntimeError`。它是扩展点，
与 Java 一致：实现 `MaskingStrategy`、注册进去，它就接管所有 `CUSTOM` 规则。

```python
from atlas_richie.desensitize_core import MaskRule, MaskType, MaskingStrategyRegistry


class HashedStrategy:
    def supports(self, mask_type: MaskType) -> bool:
        return mask_type is MaskType.CUSTOM

    def mask(self, raw: str | None, rule: MaskRule) -> str | None:
        return f"hashed:{rule.custom_strategy}" if raw is not None else None


registry = MaskingStrategyRegistry([HashedStrategy()])
rule = MaskRule(MaskType.CUSTOM, 0, 0, "*", "sha256")
registry.require(MaskType.CUSTOM).mask("secret", rule)
```

`MaskRule.custom_strategy` 对位 Java 的 `MaskRule.customStrategy`：它**承载**调用方
自定义策略的名字，并原样传到 `mask()`。两侧都不按这个名字解析 —— Java 同样按类型
路由 `CUSTOM`，从规则里读这个参数（它自己的查找链计划在 V2）。

## 开关与权限

`DesensitizeProperties.enabled` 与逐场景开关会短路成明文。
`DefaultMaskPermissionEvaluator` 在「启用了权限控制、且上下文带有
`permission.plain_text_roles` 里列出的角色」时同样返回明文。
接入真实 RBAC 的办法是注入自己的 `MaskPermissionEvaluator`。

## 对象图与日志安全序列化

`SafeLogSerializer` 把任意载荷渲染成日志安全 JSON，过程中边渲染边脱敏：

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

logger.info("login for %s", SensitiveLogArg.phone("13812348000"))  # 日志里已脱敏
```

支持标量、mapping、list/tuple/set、dataclass，以及带 `__dict__` 或 `__slots__`
的普通对象。字段标记来自 dataclass metadata（Java 用 `@Sensitive` 注解）；
`ClassVar` 与 `transient_field` 会被跳过 —— 对位 Java 跳过 static 与 transient
字段。没有标记时，套用 `properties.fields[class_fqn][field]` 映射。与 Java
一致，只有**字符串**字段会被脱敏。

`DefaultObjectMaskingService` 是序列化器之上的薄门面，与 Java 的服务形状一致。

### 有界递归

深度上限为 8（Java 的 `MAX_DEPTH`），循环引用的 mapping 会被换成 `[circular]`
标记。`mask_map` 本身也是有界的 —— Java 的版本无限递归，自引用的载荷会把调用方
挂死。日志序列化器必须能终止。

### 刻意差异

- **`SensitiveLogArg.__str__` 会脱敏。** Java 的 `toString()` 返回**原始**值，
  依赖 Logback turbo filter 去脱敏。Python 的 logging 没有这种拦截点，返回原值
  就会泄露凭证。因此脱敏发生在 `__str__` 里，用注入的服务或默认服务；
  `raw_value` 是显式选择才暴露原值的入口，`__repr__` 永不显示原值。
- **合法 JSON 转义。** Java 手写的 `quote` 只转义 `" \ \n \r \t`，其余控制
  字符原样输出，会产出非法 JSON。这里用正规的 JSON 转义。
- **调用方的场景会传递到嵌套值。** Java 的 `writeMap` 对嵌套项硬编码 `LOG`，
  于是「只在 API_RESPONSE 生效」的敏感键嵌了一层就漏了。尊重调用方的场景才是
  真正的契约。

## 范围

已移植：模型、配置、八个策略、两个注册表、权限求值器、`DefaultMaskingService`
（字符串 + 递归 map 脱敏）、字段标记、`SafeLogSerializer`、
`DefaultObjectMaskingService` 与 `SensitiveLogArg`。

未移植：log/exception 的正则兜底。

同仓兄弟包已移植：Java 的 `desensitize-jackson` 对应 `desensitize-pydantic`；
Java 的 `desensitize-logging` 对应 `desensitize-logging`（MDC 上下文、日志参数
与 MDC 两个拦截点，以及日志脱敏 SPI）。
