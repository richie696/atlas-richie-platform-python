"""看门狗 SPI（对位 Java `web.core.hang` 包）。"""

from .events import MAX_STACK_FRAMES, HangEvent, stack_of
from .interceptor import (
    LEVEL_DUMP,
    LEVEL_KILL_SWITCH,
    LEVEL_WARN,
    HangDetectionInterceptor,
)
from .scheduler import WatchHandle, WatchdogScheduler

__all__ = [
    "LEVEL_DUMP",
    "LEVEL_KILL_SWITCH",
    "LEVEL_WARN",
    "MAX_STACK_FRAMES",
    "HangDetectionInterceptor",
    "HangEvent",
    "WatchHandle",
    "WatchdogScheduler",
    "stack_of",
]
