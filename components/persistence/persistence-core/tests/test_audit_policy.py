"""审计/软删字段策略：insert 补空、update 刷新、禁用即不填。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas_richie.persistence_core import (
    AuditField,
    AuditFieldPolicy,
    AuditFieldValues,
    audit_column_values,
    resolve_insert_values,
    resolve_update_values,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class TestPolicy:
    def test_default_column_names(self) -> None:
        policy = AuditFieldPolicy()
        assert policy.column_name(AuditField.CREATE_ID) == "createId"
        assert policy.column_name(AuditField.UPDATE_ID) == "updateId"
        assert policy.column_name(AuditField.CREATE_TIME) == "createTime"
        assert policy.column_name(AuditField.UPDATE_TIME) == "updateTime"
        assert policy.column_name(AuditField.DELETED) == "deleted"

    def test_custom_column_names(self) -> None:
        policy = AuditFieldPolicy(create_id="creator", deleted="is_deleted")
        assert policy.column_name(AuditField.CREATE_ID) == "creator"
        assert policy.column_name(AuditField.DELETED) == "is_deleted"

    def test_insert_value_fills_only_null(self) -> None:
        policy = AuditFieldPolicy()
        assert policy.insert_value(
            AuditField.CREATE_ID, None, username="alice", now=NOW
        ) == "alice"
        assert policy.insert_value(
            AuditField.CREATE_ID, "bob", username="alice", now=NOW
        ) == "bob"

    def test_insert_value_for_deleted(self) -> None:
        policy = AuditFieldPolicy()
        assert policy.insert_value(
            AuditField.DELETED, None, username="", now=NOW
        ) is False

    def test_insert_value_when_disabled(self) -> None:
        policy = AuditFieldPolicy(enabled=False)
        assert policy.insert_value(
            AuditField.CREATE_ID, None, username="alice", now=NOW
        ) is None

    def test_update_value_only_touches_update_fields(self) -> None:
        policy = AuditFieldPolicy()
        assert policy.update_value(
            AuditField.UPDATE_ID, None, username="carol", now=NOW
        ) == "carol"
        assert policy.update_value(
            AuditField.UPDATE_TIME, None, username="carol", now=NOW
        ) == NOW
        assert policy.update_value(
            AuditField.CREATE_TIME, None, username="carol", now=NOW
        ) is None

    def test_missing_username_becomes_empty_string(self) -> None:
        policy = AuditFieldPolicy()
        assert policy.insert_value(
            AuditField.CREATE_ID, None, username="", now=NOW
        ) == ""


class TestResolve:
    def test_insert_fills_all_five_fields(self) -> None:
        policy = AuditFieldPolicy()
        values = resolve_insert_values(
            policy, AuditFieldValues(), username="alice", now=NOW
        )
        assert values.create_id == "alice"
        assert values.update_id == "alice"
        assert values.create_time == NOW
        assert values.update_time == NOW
        assert values.deleted is False

    def test_insert_preserves_existing_values(self) -> None:
        policy = AuditFieldPolicy()
        current = AuditFieldValues(create_id="bob", create_time=NOW - timedelta(days=1))
        values = resolve_insert_values(
            policy, current, username="alice", now=NOW
        )
        assert values.create_id == "bob"
        assert values.create_time == NOW - timedelta(days=1)
        assert values.update_id == "alice"

    def test_insert_when_disabled_changes_nothing(self) -> None:
        policy = AuditFieldPolicy(enabled=False)
        values = resolve_insert_values(
            policy, AuditFieldValues(), username="alice", now=NOW
        )
        assert values == AuditFieldValues()

    def test_update_refreshes_only_update_fields(self) -> None:
        policy = AuditFieldPolicy()
        current = AuditFieldValues(
            create_id="alice",
            create_time=NOW - timedelta(days=1),
            update_time=NOW - timedelta(days=1),
        )
        values = resolve_update_values(
            policy, current, username="carol", now=NOW
        )
        assert values.update_id == "carol"
        assert values.update_time == NOW
        assert values.create_id == "alice"
        assert values.create_time == NOW - timedelta(days=1)


class TestColumnValues:
    def test_maps_semantic_values_to_column_names(self) -> None:
        policy = AuditFieldPolicy()
        values = AuditFieldValues(
            create_id="alice", update_id="alice", create_time=NOW, update_time=NOW,
            deleted=False,
        )
        mapping = audit_column_values(policy, values)
        assert mapping == {
            "createId": "alice",
            "updateId": "alice",
            "createTime": NOW,
            "updateTime": NOW,
            "deleted": False,
        }

    def test_none_values_are_skipped(self) -> None:
        policy = AuditFieldPolicy()
        mapping = audit_column_values(policy, AuditFieldValues(create_id="alice"))
        assert mapping == {"createId": "alice"}

    def test_custom_column_names_are_used(self) -> None:
        policy = AuditFieldPolicy(create_id="creator")
        mapping = audit_column_values(policy, AuditFieldValues(create_id="alice"))
        assert mapping == {"creator": "alice"}
