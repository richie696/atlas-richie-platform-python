"""Adapt the read-only registered-source checker to the first-run Port."""

from __future__ import annotations

from ..application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceCheckResult,
    BootstrapSourceChecker,
    BootstrapSourceFailureReason,
    ConsulDirectCredentials,
    NacosDirectCredentials,
    NoSourceAuthentication,
)
from ..application.check_registered_source import (
    RegisteredSourceChecker,
    SourceCheckAuthenticationMode,
    SourceCheckFailureReason,
    SourceConnectionInput,
)
from ..domain.configuration_source import ConfigurationSourceProvider


class RegisteredCheckerBootstrapAdapter(BootstrapSourceChecker):
    """Reuse one SSRF-bounded provider checker for first-run probes."""

    def __init__(self, checker: RegisteredSourceChecker) -> None:
        self._checker = checker

    async def check(
        self, candidate: BootstrapSourceCandidate
    ) -> BootstrapSourceCheckResult:
        """Translate ephemeral setup credentials without storing request data."""
        provider = ConfigurationSourceProvider(candidate.provider.value)
        authentication = candidate.authentication
        if isinstance(authentication, NoSourceAuthentication):
            command = SourceConnectionInput(
                None,
                None,
                provider,
                candidate.endpoint,
                candidate.location,
                SourceCheckAuthenticationMode.NONE,
            )
        elif isinstance(authentication, NacosDirectCredentials):
            command = SourceConnectionInput(
                None,
                None,
                provider,
                candidate.endpoint,
                candidate.location,
                SourceCheckAuthenticationMode.DIRECT,
                username=authentication.username,
                password=authentication.password,
            )
        elif isinstance(authentication, ConsulDirectCredentials):
            command = SourceConnectionInput(
                None,
                None,
                provider,
                candidate.endpoint,
                candidate.location,
                SourceCheckAuthenticationMode.DIRECT,
                acl_token=authentication.acl_token,
            )
        else:
            # CheckBootstrapSource resolves references before calling this Port.
            raise ValueError("bootstrap source authentication was not resolved")

        result = await self._checker.check(command, actor_id="bootstrap-setup")
        if result.reachable:
            return BootstrapSourceCheckResult(reachable=True)
        return BootstrapSourceCheckResult(
            reachable=False,
            reason=_failure_reason(result.reason),
        )


def _failure_reason(
    reason: SourceCheckFailureReason | None,
) -> BootstrapSourceFailureReason:
    if reason is SourceCheckFailureReason.AUTHENTICATION:
        return BootstrapSourceFailureReason.AUTHENTICATION
    if reason is SourceCheckFailureReason.UNSUPPORTED:
        return BootstrapSourceFailureReason.UNSUPPORTED
    return BootstrapSourceFailureReason.CONNECTION


__all__ = ["RegisteredCheckerBootstrapAdapter"]
