"""Deployment configuration for the durable local setup-window authority."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .setup_window_file_store import SetupWindowFileStore

_PATH_ENV = "SENTINEL_CONSOLE_SETUP_WINDOW_PATH"


class SetupWindowConfigurationError(ValueError):
    """The deployment-owned setup-window file path is invalid or absent."""


@dataclass(frozen=True, slots=True)
class SetupWindowConfiguration:
    """Absolute path for one setup-window state file on a local POSIX mount."""

    path: Path

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, Path)
            or not self.path.is_absolute()
            or self.path.name in {"", ".", ".."}
        ):
            raise SetupWindowConfigurationError(
                "setup-window path must be an absolute file path"
            )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> SetupWindowConfiguration:
        """Read the required setup-window path without creating it implicitly."""
        values = os.environ if environment is None else environment
        try:
            path_text = values[_PATH_ENV]
        except KeyError:
            raise SetupWindowConfigurationError(
                "setup-window deployment configuration is incomplete"
            ) from None
        if not isinstance(path_text, str) or not path_text:
            raise SetupWindowConfigurationError(
                "setup-window path must be an absolute file path"
            )
        try:
            return cls(Path(path_text))
        except (TypeError, ValueError):
            raise SetupWindowConfigurationError(
                "setup-window path must be an absolute file path"
            ) from None

    def create_store(self) -> SetupWindowFileStore:
        """Create the file Adapter for explicit ASGI composition."""
        return SetupWindowFileStore(self.path)
