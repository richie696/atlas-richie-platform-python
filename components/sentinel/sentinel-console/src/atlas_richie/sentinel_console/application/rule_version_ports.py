"""Consumer-owned ports for immutable rule-version reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.rule_versions import RuleSetVersion, RuleSetVersionCollection


class RuleSetVersionReader(Protocol):
    """Read the complete bounded immutable-version collection for a binding."""

    async def read_rule_versions(self, binding_id: str) -> RuleSetVersionCollection:
        """Return versions belonging only to the requested binding."""


class RuleSetVersionDetailReader(Protocol):
    """Read one exact immutable version within its rule binding."""

    async def read_rule_version(
        self, binding_id: str, version_id: str
    ) -> RuleSetVersion:
        """Return the exact version or raise not-found for an invisible target."""


class RuleSetVersionAuthorityUnavailable(RuntimeError):
    """The immutable-version authority cannot return trustworthy facts."""


class RuleSetVersionNotFound(LookupError):
    """The binding or version does not exist or is not visible."""


class RuleSetVersionRateLimited(RuntimeError):
    """The authority declined the read within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule version read rate limited")
