"""Application contract for deployment-owned runtime database configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
from typing import Protocol
from uuid import UUID


class RuntimeDatabaseLocatorError(RuntimeError):
    """The runtime database configuration is unavailable or invalid."""


class RuntimeDatabaseLocatorConflict(RuntimeDatabaseLocatorError):
    """A concurrent writer changed the locator revision."""


@dataclass(frozen=True, slots=True)
class RuntimeDatabaseTarget:
    """Approved socket addresses and TLS identity selected during bootstrap."""

    hostname: str
    addresses: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.hostname, str) or not self.hostname:
            raise ValueError("runtime database target hostname is invalid")
        normalized: list[str] = []
        for address in self.addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except (TypeError, ValueError):
                raise ValueError("runtime database target address is invalid") from None
            if parsed.is_link_local or parsed.is_unspecified or parsed.is_multicast:
                raise ValueError("runtime database target address is invalid")
            normalized.append(parsed.compressed)
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("runtime database target addresses are invalid")
        object.__setattr__(self, "addresses", tuple(normalized))


@dataclass(frozen=True, slots=True)
class RuntimeDatabaseLocator:
    """Sensitive URL, approved network target, and opaque revision."""

    database_url: str = field(repr=False)
    revision: str
    target: RuntimeDatabaseTarget | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.database_url, str)
            or not self.database_url
            or len(self.database_url) > 4096
            or "\x00" in self.database_url
        ):
            raise ValueError("runtime database URL is invalid")
        try:
            revision = UUID(self.revision)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("runtime database revision is invalid") from None
        if str(revision) != self.revision:
            raise ValueError("runtime database revision is invalid")
        if self.target is not None and not isinstance(
            self.target, RuntimeDatabaseTarget
        ):
            raise ValueError("runtime database target is invalid")


class RuntimeDatabaseLocatorStore(Protocol):
    """Read and compare-and-swap the deployment-owned encrypted locator."""

    async def read(self) -> RuntimeDatabaseLocator | None:
        """Return None only when no locator has ever been written."""

    async def write(
        self,
        database_url: str,
        *,
        expected_revision: str | None,
        target: RuntimeDatabaseTarget | None = None,
    ) -> RuntimeDatabaseLocator:
        """Create when expected_revision is None; otherwise CAS-update."""
