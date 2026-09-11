"""稳定的错误类别，零 transport / framework 耦合。
----
所有 component 抛的"预期可恢复"错误都继承 `PlatformError`，业务方
catch 一个根类型即可处理所有 framework-level 失败。
`ValidationError` 用于输入校验失败；`CapabilityUnavailable` 用于
optional adapter / capability 缺失。意外 / 系统级异常（OSError、
MemoryError 等）不归 PlatformError — 业务方应单独处理。

English
--------
Stable error categories without transport or framework coupling.

`PlatformError` is the root for all "expected, recoverable"
component failures. Component-specific errors inherit from it so
business code can catch the root and handle all framework failures
uniformly. `ValidationError` covers input contract violations;
`CapabilityUnavailable` covers missing optional adapters / config.
Unexpected / system-level errors (OSError, MemoryError, …) do NOT
inherit from PlatformError — those need separate handling.
"""


class PlatformError(Exception):
    """Framework 预期失败基类。"""


class ValidationError(PlatformError):
    """公开入参不满足 component 契约时抛。"""


class CapabilityUnavailable(PlatformError):
    """Optional adapter 或配置的 capability 缺失时抛。"""
