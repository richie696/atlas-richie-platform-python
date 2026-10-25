"""Validated password input for account-password write commands."""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_ACCOUNT_PASSWORD_UTF16_UNITS = 8
MAX_ACCOUNT_PASSWORD_UTF16_UNITS = 32


@dataclass(frozen=True, slots=True)
class AccountPassword:
    """Preserve the exact submitted password while enforcing the wire policy.

    Passwords are deliberately not trimmed, normalized, or included in the
    object's representation. Length matches JavaScript string length so the
    Python Console and React contract reject the same inputs.
    """

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("password must be a string")
        try:
            length = len(self.value.encode("utf-16-le")) // 2
        except UnicodeEncodeError as error:
            raise ValueError("password contains an unpaired surrogate") from error
        if not (
            MIN_ACCOUNT_PASSWORD_UTF16_UNITS
            <= length
            <= MAX_ACCOUNT_PASSWORD_UTF16_UNITS
        ):
            raise ValueError("password length is outside the supported range")
