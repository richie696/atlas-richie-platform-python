"""Domain facts exposed by the Console bootstrap read use case."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InitializedBootstrap:
    """The Console was initialized; setup must not be reopened."""


@dataclass(frozen=True, slots=True)
class OpenSetupBootstrap:
    """The setup gate facts visible to this request."""

    setup_available: bool
    operator_authorized: bool

    def __post_init__(self) -> None:
        if type(self.setup_available) is not bool or type(self.operator_authorized) is not bool:
            raise ValueError("bootstrap response fields must be booleans")
        if self.operator_authorized and not self.setup_available:
            raise ValueError("bootstrap authorization requires an open setup window")


BootstrapSnapshot = InitializedBootstrap | OpenSetupBootstrap
