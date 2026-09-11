"""组件能力的可移植描述。
----
提供稳定、可序列化的 dataclass 用于描述组件能力（name + version +
属性集合）。跨 component 通信、capability 协商、版本检查都用此
schema；不绑定任何 transport / framework。

English
--------
Portable component capability descriptions.

A stable, serializable dataclass for declaring a component
capability: name + version + an attribute map. Used for
cross-component capability negotiation, version checks, and
introspection. Transport / framework agnostic.
"""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """组件能力的稳定可序列化描述。

    Args:
        name: 能力名称（如 `"redis-cache-core"`）
        version: semver 字符串（如 `"0.1.0"`）
        attributes: capability → 值的字符串映射
            （如 `{"max_connections": "50"}`）

    English
    --------
    A stable, serializable description of a component capability.
    """

    name: str
    version: str
    attributes: Mapping[str, str]
