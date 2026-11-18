"""结构化 JSON 日志消息脱敏（对位 Java `DesensitizeJsonMessageConverter`）。

此前只有 `SensitiveLogArg.__str__` 掩蔽单个值；整条 JSON 日志消息里的敏感
字段仍明文。本模块补上：消息若为 JSON 对象（`{...}`）则解析 → maskMap →
重序列化；非 JSON、解析失败、任何异常都**原样透传**——日志脱敏是旁路，
绝不能因为脱敏失败而丢日志或抛异常给业务。

`JsonLogMaskingFilter` 是 stdlib `logging.Filter`，对位 Logback converter：
掩蔽的是**最终格式化后**的消息（msg % args），与 Java 在 converter 层处理
完整消息一致。
"""

from __future__ import annotations

import json
import logging

from .model import MaskScene
from .service import MaskingService


def mask_json_message(
    message: str | None,
    masking: MaskingService,
    scene: MaskScene = MaskScene.LOG,
) -> str | None:
    if message is None or not message.strip():
        return message
    trimmed = message.strip()
    if not (trimmed.startswith("{") and trimmed.endswith("}")):
        return message
    try:
        parsed = json.loads(trimmed)
    except (ValueError, TypeError):
        return message
    if not isinstance(parsed, dict):
        return message
    try:
        masked = masking.mask_map(parsed, scene)
        if masked is None:
            return message
        return json.dumps(masked, ensure_ascii=False)
    except Exception:  # noqa: BLE001 — 脱敏失败原样透传，不得丢日志
        return message


class JsonLogMaskingFilter(logging.Filter):
    """Masks the formatted log message when it is a JSON object.

    Install on a logger or handler:
        logger.addFilter(JsonLogMaskingFilter(masking_service))
    """

    def __init__(
        self,
        masking: MaskingService,
        scene: MaskScene = MaskScene.LOG,
        name: str = "",
    ) -> None:
        super().__init__(name)
        self._masking = masking
        self._scene = scene

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            formatted = record.getMessage()
        except Exception:  # noqa: BLE001 — 格式化失败的消息保持原样
            return True
        masked = mask_json_message(formatted, self._masking, self._scene)
        if masked is not None and masked != formatted:
            record.msg = masked
            record.args = ()
        return True


__all__ = ["mask_json_message", "JsonLogMaskingFilter"]