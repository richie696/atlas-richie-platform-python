"""Application workflow for operator-managed Metrics V2 reporter identities."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime

from .metrics_ingest_ports import MetricsReporterBinding
from .metrics_reporter_admin_ports import (
    MetricsReporterAdminError,
    MetricsReporterAdminErrorCode,
    MetricsReporterAdministration,
)

_CERTIFICATE_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
_MAX_ID_LENGTH = 200
_MAX_PRINCIPAL_LENGTH = 255


class ManageMetricsReporters:
    """Validate operator input and delegate persistence to its owner Port."""

    def __init__(
        self,
        administration: MetricsReporterAdministration,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._administration = administration
        self._clock = clock or (lambda: datetime.now(UTC))

    async def enroll(self, binding: MetricsReporterBinding) -> MetricsReporterBinding:
        """Enroll one exact process identity without accepting key material."""
        _validate_binding(binding)
        return await self._administration.enroll_reporter(binding)

    async def revoke(self, certificate_principal: str) -> bool:
        """Revoke a principal using one UTC instant from the injected clock."""
        if not _valid_identifier(certificate_principal, _MAX_PRINCIPAL_LENGTH):
            raise MetricsReporterAdminError(
                MetricsReporterAdminErrorCode.INVALID_BINDING
            )
        revoked_at = self._clock()
        if not _is_utc(revoked_at):
            raise ValueError("reporter management clock must return UTC")
        return await self._administration.revoke_reporter(
            certificate_principal, revoked_at
        )


def _validate_binding(binding: MetricsReporterBinding) -> None:
    if not isinstance(binding, MetricsReporterBinding):
        raise MetricsReporterAdminError(MetricsReporterAdminErrorCode.INVALID_BINDING)
    if _CERTIFICATE_FINGERPRINT_PATTERN.fullmatch(binding.certificate_sha256) is None:
        raise MetricsReporterAdminError(MetricsReporterAdminErrorCode.INVALID_BINDING)
    if not _valid_identifier(binding.certificate_principal, _MAX_PRINCIPAL_LENGTH):
        raise MetricsReporterAdminError(MetricsReporterAdminErrorCode.INVALID_BINDING)
    if any(
        not _valid_identifier(value, _MAX_ID_LENGTH)
        for value in (
            binding.reporter_id,
            binding.environment_id,
            binding.app_id,
            binding.instance_id,
            binding.process_id,
        )
    ):
        raise MetricsReporterAdminError(MetricsReporterAdminErrorCode.INVALID_BINDING)


def _valid_identifier(value: str, maximum_length: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum_length
        and all(character.isprintable() for character in value)
    )


def _is_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


__all__ = ["ManageMetricsReporters"]
