"""Masking strategies and their type-indexed registry.

Ported from `cn.richie696.component.desensitize.core.strategy` (Java). The Spring
`@Component` stereotypes are dropped; registration is explicit.

Two quirks are preserved deliberately because callers depend on the exact output:
`BANK_CARD` emits a fixed grouped format and ignores `mask_char` / keep counts,
and `EMAIL` hard-codes `***` rather than using `mask_char`.
"""

from __future__ import annotations

import re
from typing import Protocol

from .model import MaskRule, MaskType

# Java's replaceAll("\\s+") is ASCII-only unless UNICODE_CHARACTER_CLASS is set;
# Python's \s is Unicode-aware, so spell out the ASCII class to stay aligned.
_JAVA_SPACE = re.compile(r"[ \t\n\x0b\f\r]+")


class MaskingStrategy(Protocol):
    def supports(self, mask_type: MaskType) -> bool: ...

    def mask(self, raw: str | None, rule: MaskRule) -> str | None: ...


class _KeepEdgeStrategy:
    """Keep `keep_left` / `keep_right` characters and mask the middle."""

    supported_type: MaskType

    def supports(self, mask_type: MaskType) -> bool:
        return mask_type is self.supported_type

    def mask(self, raw: str | None, rule: MaskRule) -> str | None:
        if raw is None or raw == "":
            return raw
        left, right = rule.keep_left, rule.keep_right
        if left + right >= len(raw):
            return rule.mask_char * len(raw)
        prefix = raw[:left]
        suffix = raw[len(raw) - right :] if right else ""
        mask_length = (
            rule.mask_length
            if rule.mask_length is not None and rule.mask_length > 0
            else len(raw) - left - right
        )
        return prefix + rule.mask_char * mask_length + suffix


class PhoneMaskingStrategy(_KeepEdgeStrategy):
    supported_type = MaskType.PHONE


class IdCardMaskingStrategy(_KeepEdgeStrategy):
    supported_type = MaskType.ID_CARD


class AddressMaskingStrategy(_KeepEdgeStrategy):
    supported_type = MaskType.ADDRESS


class ApiKeyMaskingStrategy(_KeepEdgeStrategy):
    supported_type = MaskType.API_KEY


class BankCardMaskingStrategy:
    """Grouped card format: first 4 + ` **** **** ` + last 4, ignoring mask_char."""

    def supports(self, mask_type: MaskType) -> bool:
        return mask_type is MaskType.BANK_CARD

    def mask(self, raw: str | None, rule: MaskRule) -> str | None:
        if raw is None or raw == "":
            return raw
        digits = _JAVA_SPACE.sub("", raw)
        if len(digits) <= 8:
            return rule.mask_char * len(raw)
        return digits[:4] + " **** **** " + digits[-4:]


class EmailMaskingStrategy:
    """Masks the local part, keeps the domain; `***` is fixed by contract."""

    def supports(self, mask_type: MaskType) -> bool:
        return mask_type is MaskType.EMAIL

    def mask(self, raw: str | None, rule: MaskRule) -> str | None:
        if raw is None or raw == "":
            return raw
        at = raw.find("@")
        if at <= 0:
            return rule.mask_char * min(len(raw), 3)
        local, domain = raw[:at], raw[at:]
        if len(local) == 1:
            return local + "***" + domain
        return local[0] + "***" + domain


class NameMaskingStrategy:
    """Keeps the first character, masks the rest."""

    def supports(self, mask_type: MaskType) -> bool:
        return mask_type is MaskType.NAME

    def mask(self, raw: str | None, rule: MaskRule) -> str | None:
        if raw is None or raw == "":
            return raw
        if len(raw) == 1:
            return rule.mask_char
        return raw[0] + rule.mask_char * (len(raw) - 1)


class PasswordMaskingStrategy:
    """Fully masked, never shorter than 6 characters so length is not leaked."""

    DEFAULT_MASK_LENGTH = 6

    def supports(self, mask_type: MaskType) -> bool:
        return mask_type is MaskType.PASSWORD

    def mask(self, raw: str | None, rule: MaskRule) -> str | None:
        if raw is None or raw == "":
            return raw
        return rule.mask_char * max(len(raw), self.DEFAULT_MASK_LENGTH)


def default_strategies() -> list[MaskingStrategy]:
    return [
        PhoneMaskingStrategy(),
        IdCardMaskingStrategy(),
        BankCardMaskingStrategy(),
        EmailMaskingStrategy(),
        NameMaskingStrategy(),
        AddressMaskingStrategy(),
        PasswordMaskingStrategy(),
        ApiKeyMaskingStrategy(),
    ]


class MaskingStrategyRegistry:
    """Indexes strategies by every type they support; first registration wins."""

    def __init__(self, strategies: list[MaskingStrategy] | None = None) -> None:
        self._strategies: dict[MaskType, MaskingStrategy] = {}
        for strategy in strategies if strategies is not None else default_strategies():
            for mask_type in MaskType:
                if strategy.supports(mask_type) and mask_type not in self._strategies:
                    self._strategies[mask_type] = strategy

    def require(self, mask_type: MaskType) -> MaskingStrategy:
        strategy = self._strategies.get(mask_type)
        if strategy is None:
            raise RuntimeError(f"No MaskingStrategy registered for type: {mask_type}")
        return strategy


__all__ = [
    "AddressMaskingStrategy",
    "ApiKeyMaskingStrategy",
    "BankCardMaskingStrategy",
    "EmailMaskingStrategy",
    "IdCardMaskingStrategy",
    "MaskingStrategy",
    "MaskingStrategyRegistry",
    "NameMaskingStrategy",
    "PasswordMaskingStrategy",
    "PhoneMaskingStrategy",
    "default_strategies",
]
