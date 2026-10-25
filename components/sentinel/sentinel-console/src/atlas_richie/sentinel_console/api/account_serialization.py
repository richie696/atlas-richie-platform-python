"""Allow-listed JSON projections for accounts and durable command receipts."""

from __future__ import annotations

from datetime import UTC, datetime

from ..application.account_commands import AccountOperation, AccountOperationStatus
from ..application.account_directory_ports import AccountDirectoryItem


def account_item_body(item: AccountDirectoryItem) -> dict[str, object]:
    """Project safe account facts; credential fields are not representable here."""
    last_login_at = _utc_timestamp(item.last_login_at)
    return {
        "id": item.account_id,
        "username": item.username,
        "roleId": item.role_id,
        "status": item.status,
        "builtIn": item.built_in,
        "lastLoginAt": last_login_at,
        "revision": str(item.revision),
        "lastActiveAdmin": item.last_active_admin,
    }


def operation_body(operation: AccountOperation) -> dict[str, object]:
    """Project one operation's immutable safe result."""
    if operation.status is AccountOperationStatus.COMPLETED:
        assert operation.account is not None
        return {
            "status": operation.status.value,
            "requestKey": operation.request_key,
            "account": account_item_body(operation.account),
        }
    assert operation.reason is not None
    return {
        "status": operation.status.value,
        "requestKey": operation.request_key,
        "reason": operation.reason.value,
    }


def _utc_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
