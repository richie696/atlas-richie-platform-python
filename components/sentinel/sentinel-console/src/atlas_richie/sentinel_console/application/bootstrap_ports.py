"""Small consumer-owned ports for reading Console bootstrap facts."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

class BootstrapInitializationReader(Protocol):
    """Read the Console initialization fact from its durable authority."""

    async def is_initialized(self) -> bool:
        """Return the durable initialization fact or fail closed."""


class SetupWindowReader(Protocol):
    """Read whether deployment currently permits first-run setup."""

    async def is_setup_window_open(self) -> bool:
        """Return the deployment-owned setup-window fact or fail closed."""


class SetupWindowController(Protocol):
    """Change deployment setup availability using an exact revision CAS."""

    async def set_setup_window_open(
        self, is_open: bool, *, expected_revision: str | None
    ) -> str:
        """Persist a new state and return its opaque revision."""

    async def close_setup_window_if_open(self) -> None:
        """Idempotently close setup after the target database commits."""


class BootstrapInitializationLock(Protocol):
    """Serialize cross-store first-run side effects for one deployment."""

    def acquire(self) -> AbstractAsyncContextManager[None]:
        """Acquire the deployment setup lock until the returned scope exits."""


class BootstrapOperatorSessionVerifier(Protocol):
    """Verify an opaque request cookie without treating it as admin identity."""

    async def is_current_operator(self, opaque_session: str | None) -> bool:
        """Verify the current request or raise BootstrapAuthorityUnavailable."""
