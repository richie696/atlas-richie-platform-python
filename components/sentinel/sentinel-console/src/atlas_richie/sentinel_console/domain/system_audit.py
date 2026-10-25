"""Bounded, credential-free system audit query and result facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .wire_numbers import MAX_SAFE_JSON_INTEGER
from .wire_strings import is_bounded_wire_identifier

_MAX_IDENTIFIER_UNITS = 200
_MAX_PAGE = 1_000_000
_MAX_PAGE_SIZE = 100
_MAX_QUERY_WINDOW = timedelta(days=31)
_MIN_SUPPORTED_UTC_YEAR = 1970


class AuditAction(StrEnum):
    """Finite user-visible audit operations."""

    ACCOUNT_CREATE = "account-create"
    ACCOUNT_ROLE = "account-role"
    ACCOUNT_STATUS = "account-status"
    ACCOUNT_PASSWORD_RESET = "account-password-reset"
    LOCAL_ADMIN_PASSWORD_RECOVERY = "local-admin-password-recovery"
    ACCOUNT_DELETE = "account-delete"
    PASSWORD_CHANGE = "password-change"
    SYSTEM_INITIALIZE = "system-initialize"
    RULE_VALIDATE = "rule-validate"
    RULE_BINDING_CREATE = "rule-binding-create"
    SOURCE_REGISTER = "source-register"
    SOURCE_UPDATE = "source-update"
    SOURCE_DELETE = "source-delete"
    DEPLOYMENT_DEPENDENCIES_MIGRATED = "deployment-dependencies-migrated"
    REPORTER_CERTIFICATE_ROTATED = "reporter-certificate-rotated"
    MONITORING_SOURCE_CREATE = "monitoring-source-create"
    MONITORING_SOURCE_UPDATE = "monitoring-source-update"
    MONITORING_SOURCE_DELETE = "monitoring-source-delete"
    MONITORING_SOURCE_ENABLE = "monitoring-source-enable"
    MONITORING_SOURCE_DISABLE = "monitoring-source-disable"
    HOST_ASSOCIATION_CREATE = "host-association-create"
    HOST_ASSOCIATION_DELETE = "host-association-delete"
    DRAFT_SAVE = "draft-save"
    DRAFT_DELETE = "draft-delete"
    VERSION_FREEZE = "version-freeze"
    RULE_PUBLISH = "rule-publish"
    PLAN_CREATE = "plan-create"
    PLAN_CANCEL = "plan-cancel"
    PLAN_ACTIVATE = "plan-activate"
    PLAN_RESTORE = "plan-restore"
    TARGET_CONFIGURE = "target-configure"


class AuditResult(StrEnum):
    """Finite operation result categories; accepted is not completed success."""

    SUCCESS = "success"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


def _valid_identifier(value: str) -> bool:
    return is_bounded_wire_identifier(value, _MAX_IDENTIFIER_UNITS)


def _valid_instant(value: datetime) -> bool:
    return (
        value.tzinfo is not None
        and value.utcoffset() is not None
        and _MIN_SUPPORTED_UTC_YEAR <= value.year <= 9999
    )


@dataclass(frozen=True, slots=True)
class AuditQuery:
    """Admin-only half-open UTC range and stable page filters."""

    start: datetime
    end: datetime
    actor_id: str
    action: AuditAction | None
    result: AuditResult | None
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.start, datetime)
            or not _valid_instant(self.start)
            or not isinstance(self.end, datetime)
            or not _valid_instant(self.end)
            or self.end <= self.start
            or self.end - self.start > _MAX_QUERY_WINDOW
        ):
            raise ValueError(
                "audit range must be increasing and no longer than 31 days"
            )
        if not isinstance(self.actor_id, str) or (
            self.actor_id != "" and not _valid_identifier(self.actor_id)
        ):
            raise ValueError("audit actor filter is invalid")
        if self.action is not None and not isinstance(self.action, AuditAction):
            raise ValueError("audit action filter is not supported")
        if self.result is not None and not isinstance(self.result, AuditResult):
            raise ValueError("audit result filter is not supported")
        if (
            isinstance(self.page, bool)
            or not isinstance(self.page, int)
            or not 1 <= self.page <= _MAX_PAGE
        ):
            raise ValueError("audit page is out of range")
        if (
            isinstance(self.page_size, bool)
            or not isinstance(self.page_size, int)
            or not 1 <= self.page_size <= _MAX_PAGE_SIZE
        ):
            raise ValueError("audit page size is out of range")


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Safe audit projection; never contains request bodies or free-form logs."""

    id: str
    occurred_at: datetime
    actor_id: str | None
    action: AuditAction
    target_id: str
    result: AuditResult
    request_id: str
    environment_id: str | None = None
    app_id: str | None = None
    binding_id: str | None = None
    publication_id: str | None = None

    def __post_init__(self) -> None:
        for value in (self.id, self.target_id, self.request_id):
            if not isinstance(value, str) or not _valid_identifier(value):
                raise ValueError("audit record identity is invalid")
        if self.actor_id is not None and (
            not isinstance(self.actor_id, str) or not _valid_identifier(self.actor_id)
        ):
            raise ValueError("audit actor identity is invalid")
        if self.actor_id is None and self.action not in {
            AuditAction.SYSTEM_INITIALIZE,
            AuditAction.LOCAL_ADMIN_PASSWORD_RECOVERY,
            AuditAction.PLAN_ACTIVATE,
            AuditAction.PLAN_RESTORE,
        }:
            raise ValueError("this audit action requires an account actor")
        if not isinstance(self.occurred_at, datetime) or not _valid_instant(
            self.occurred_at
        ):
            raise ValueError("audit event time must be a valid aware instant")
        if not isinstance(self.action, AuditAction) or not isinstance(
            self.result, AuditResult
        ):
            raise ValueError("audit action or result is unsupported")
        optional_ids = (
            self.environment_id,
            self.app_id,
            self.binding_id,
            self.publication_id,
        )
        if any(
            value is not None
            and (not isinstance(value, str) or not _valid_identifier(value))
            for value in optional_ids
        ):
            raise ValueError("audit navigation identity is invalid")
        if self.publication_id is not None and any(
            value is None
            for value in (self.environment_id, self.app_id, self.binding_id)
        ):
            raise ValueError("publication audit links require full rule context")


@dataclass(frozen=True, slots=True)
class SystemAuditPage:
    """One validated page and its authoritative read time/count."""

    query: AuditQuery
    as_of: datetime
    total: int
    items: tuple[AuditRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime) or not _valid_instant(self.as_of):
            raise ValueError("audit read time must be a valid aware instant")
        if (
            isinstance(self.total, bool)
            or not isinstance(self.total, int)
            or not 0 <= self.total <= MAX_SAFE_JSON_INTEGER
        ):
            raise ValueError("audit result count exceeds the supported range")
        if not isinstance(self.items, tuple) or len(self.items) > self.query.page_size:
            raise ValueError("audit page items must be a bounded tuple")
        offset = (self.query.page - 1) * self.query.page_size
        if len(self.items) > max(0, self.total - offset):
            raise ValueError("audit page item count contradicts its total")
        if any(not isinstance(item, AuditRecord) for item in self.items):
            raise ValueError("audit page contains an invalid record")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("audit page record identities must be unique")
        for index, item in enumerate(self.items):
            if (
                item.occurred_at < self.query.start
                or item.occurred_at >= self.query.end
                or item.occurred_at > self.as_of
                or (self.query.actor_id and item.actor_id != self.query.actor_id)
                or (
                    self.query.action is not None
                    and item.action is not self.query.action
                )
                or (
                    self.query.result is not None
                    and item.result is not self.query.result
                )
            ):
                raise ValueError("audit record contradicts query or read time")
            if index and not _comes_before(self.items[index - 1], item):
                raise ValueError("audit records must be newest-first and deterministic")


def _comes_before(left: AuditRecord, right: AuditRecord) -> bool:
    return left.occurred_at > right.occurred_at or (
        left.occurred_at == right.occurred_at and left.id > right.id
    )
