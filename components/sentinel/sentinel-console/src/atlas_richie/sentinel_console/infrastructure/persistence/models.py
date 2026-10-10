"""Relational identity, session, bootstrap receipt, and audit mappings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    JSON,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime

from .base import ConsoleBase

_MILLISECOND_TIMESTAMP_FRACTIONAL_DIGITS = 3
_MILLISECOND_TIMESTAMP = DateTime(timezone=True).with_variant(
    MySQLDateTime(fsp=_MILLISECOND_TIMESTAMP_FRACTIONAL_DIGITS), "mysql"
)
_LEASE_TIMESTAMP = _MILLISECOND_TIMESTAMP


class ConsoleGuardRecord(ConsoleBase):
    """Singleton row used to serialize setup and last-admin transactions."""

    __tablename__ = "console_guard"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_console_guard_singleton"),
    )

    singleton_id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False
    )
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    initialized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AccountRecord(ConsoleBase):
    """Dashboard account; only a one-way password hash is persisted."""

    __tablename__ = "console_account"
    __table_args__ = (
        UniqueConstraint("username_key", name="uq_console_account_username_key"),
        CheckConstraint("role_id IN ('admin', 'view')", name="ck_console_account_role"),
        CheckConstraint(
            "status IN ('active', 'disabled')", name="ck_console_account_status"
        ),
        CheckConstraint("revision >= 1", name="ck_console_account_revision"),
        CheckConstraint(
            "built_in = false OR (role_id = 'admin' AND status = 'active')",
            name="ck_console_account_builtin_admin_active",
        ),
        Index("ix_console_account_status_role", "status", "role_id"),
    )

    account_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    username_key: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role_id: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AuthenticationSessionRecord(ConsoleBase):
    """Server session indexed by a hash, never by the opaque cookie value."""

    __tablename__ = "console_session"
    __table_args__ = (
        Index("ix_console_session_account_expiry", "account_id", "expires_at"),
    )

    session_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="CASCADE"),
        nullable=False,
    )
    session_epoch: Mapped[str] = mapped_column(String(36), nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LoginAttemptRecord(ConsoleBase):
    """Opaque-subject failure windows for deployment-owned auth attempt limits."""

    __tablename__ = "console_login_attempt"
    __table_args__ = (
        CheckConstraint("failure_count >= 0", name="ck_console_login_attempt_count"),
        Index("ix_console_login_attempt_expiry", "expires_at_ms"),
    )

    client_identity_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_until_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class InitializationOperationRecord(ConsoleBase):
    """Safe idempotency receipt for setup; it contains no setup input secrets."""

    __tablename__ = "console_initialization_operation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'rejected')",
            name="ck_console_initialization_status",
        ),
        Index("ix_console_initialization_operator", "operator_session_hash"),
    )

    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    operator_session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountOperationRecord(ConsoleBase):
    """Write-only-safe receipt snapshot and versioned command fingerprint."""

    __tablename__ = "console_account_operation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'rejected')",
            name="ck_console_account_operation_status",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN "
            "('username_taken', 'last_admin', 'built_in', 'conflict', 'not_found')",
            name="ck_console_account_operation_reason",
        ),
        CheckConstraint(
            "(status = 'completed' AND account_id IS NOT NULL "
            "AND account_username IS NOT NULL AND account_role_id IN ('admin', 'view') "
            "AND account_status IN ('active', 'disabled') "
            "AND account_built_in IS NOT NULL AND account_revision IS NOT NULL "
            "AND account_revision >= 1 "
            "AND account_last_active_admin IS NOT NULL AND reason IS NULL) OR "
            "(status = 'rejected' AND account_id IS NULL "
            "AND account_username IS NULL AND account_role_id IS NULL "
            "AND account_status IS NULL AND account_built_in IS NULL "
            "AND account_last_login_at IS NULL AND account_revision IS NULL "
            "AND account_last_active_admin IS NULL AND reason IS NOT NULL)",
            name="ck_console_account_operation_result",
        ),
        Index("ix_console_account_operation_actor", "actor_account_id", "created_at"),
    )

    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    actor_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fingerprint_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    account_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_role_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    account_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    account_built_in: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    account_last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    account_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    account_last_active_admin: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RuleValidationReceiptRecord(ConsoleBase):
    """Immutable validation receipt; only safe identities and field issues."""

    __tablename__ = "console_rule_validation_receipt"
    __table_args__ = (
        CheckConstraint(
            "is_publishable IN (false, true)",
            name="ck_console_rule_validation_publishable",
        ),
        Index(
            "ix_console_rule_validation_binding_created",
            "binding_id",
            "created_at",
        ),
    )

    validation_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(200), nullable=False)
    profile: Mapped[str] = mapped_column(String(200), nullable=False)
    base_checksum: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_checksum: Mapped[str] = mapped_column(String(200), nullable=False)
    is_publishable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    actor_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RegisteredConfigurationSourceRecord(ConsoleBase):
    """Safe source facts plus an authenticated-encryption envelope for credentials."""

    __tablename__ = "console_registered_source"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('nacos', 'consul')",
            name="ck_console_registered_source_provider",
        ),
        CheckConstraint(
            "authentication_mode IN ('none', 'credential-reference', 'direct')",
            name="ck_console_registered_source_auth_mode",
        ),
        CheckConstraint(
            "(authentication_mode = 'none' AND credential_configured = false "
            "AND credential_cipher_format IS NULL AND credential_key_id IS NULL "
            "AND credential_payload IS NULL) OR "
            "(authentication_mode IN ('credential-reference', 'direct') "
            "AND credential_configured = true "
            "AND credential_cipher_format IS NOT NULL "
            "AND credential_key_id IS NOT NULL AND credential_payload IS NOT NULL)",
            name="ck_console_registered_source_credential_envelope",
        ),
        Index("ix_console_registered_source_provider", "provider", "source_id"),
    )

    source_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    authentication_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_configured: Mapped[bool] = mapped_column(Boolean, nullable=False)
    credential_cipher_format: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    credential_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_payload: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="RESTRICT"),
        nullable=False,
    )


class RegisteredSourceProbeRecord(ConsoleBase):
    """Latest non-secret connectivity observation for one source revision."""

    __tablename__ = "console_registered_source_probe"
    __table_args__ = (
        CheckConstraint(
            "reason IS NULL OR reason IN ('connection', 'authentication', 'unsupported')",
            name="ck_console_registered_source_probe_reason",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_console_registered_source_probe_latency",
        ),
        CheckConstraint(
            "expires_at > checked_at",
            name="ck_console_registered_source_probe_expiry",
        ),
        Index("ix_console_registered_source_probe_expiry", "expires_at"),
    )

    source_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("console_registered_source.source_id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision: Mapped[str] = mapped_column(String(200), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class RegisteredSourceOperationRecord(ConsoleBase):
    """Idempotent source-command receipt; no credentials or source request body."""

    __tablename__ = "console_registered_source_operation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'rejected')",
            name="ck_console_registered_source_operation_status",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN "
            "('validation', 'conflict', 'not_found', 'unavailable')",
            name="ck_console_registered_source_operation_reason",
        ),
        CheckConstraint(
            "(status = 'completed' AND reason IS NULL AND source_id IS NOT NULL "
            "AND source_revision IS NOT NULL AND source_name IS NOT NULL "
            "AND source_endpoint IS NOT NULL "
            "AND source_provider IN ('nacos', 'consul') "
            "AND source_location IS NOT NULL "
            "AND source_authentication_mode IS NOT NULL "
            "AND source_credential_configured IS NOT NULL) OR "
            "(status = 'rejected' AND reason IS NOT NULL AND source_id IS NULL "
            "AND source_revision IS NULL AND source_name IS NULL "
            "AND source_endpoint IS NULL AND source_provider IS NULL "
            "AND source_location IS NULL AND source_authentication_mode IS NULL "
            "AND source_credential_configured IS NULL)",
            name="ck_console_registered_source_operation_result",
        ),
        Index(
            "ix_console_registered_source_operation_actor",
            "actor_account_id",
            "created_at",
        ),
    )

    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    actor_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_revision: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_endpoint: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_authentication_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    source_credential_configured: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RuleDraftRecord(ConsoleBase):
    """Mutable complete rule candidate with an opaque CAS revision."""

    __tablename__ = "console_rule_draft"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('flow', 'degrade', 'system', 'authority', 'param')",
            name="ck_console_rule_draft_kind",
        ),
        Index("ix_console_rule_draft_binding_updated", "binding_id", "updated_at"),
    )

    draft_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(200), nullable=False)
    revision: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str] = mapped_column(String(200), nullable=False)
    base_version_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    base_checksum: Mapped[str] = mapped_column(String(200), nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(200), nullable=True)
    records: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="RESTRICT"),
        nullable=False,
    )


class RuleMutationOperationRecord(ConsoleBase):
    """Immutable idempotency receipt bound to actor, session and rule binding."""

    __tablename__ = "console_rule_operation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'rejected')",
            name="ck_console_rule_operation_status",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN "
            "('validation', 'conflict', 'not_found', 'unsupported', 'unavailable')",
            name="ck_console_rule_operation_reason",
        ),
        CheckConstraint(
            "(status = 'pending' AND mutation_kind = 'publish' "
            "AND reason IS NULL AND result IS NULL AND work_payload IS NOT NULL) OR "
            "(status = 'completed' AND mutation_kind IN "
            "('save_draft', 'delete_draft', 'freeze_version', 'publish', 'create_plan', 'cancel_plan', 'configure_target') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
            name="ck_console_rule_operation_result",
        ),
        Index("ix_console_rule_operation_actor", "actor_account_id", "created_at"),
        Index("ix_console_rule_operation_publish_queue", "status", "mutation_kind", "created_at"),
        CheckConstraint(
            "work_attempt_count >= 0", name="ck_console_rule_operation_work_attempts"
        ),
        CheckConstraint(
            "(work_claim_token IS NULL AND work_lease_expires_at IS NULL) OR "
            "(work_claim_token IS NOT NULL AND work_lease_expires_at IS NOT NULL)",
            name="ck_console_rule_operation_work_lease",
        ),
        CheckConstraint(
            "(actor_account_id IS NOT NULL AND session_hash IS NOT NULL "
            "AND origin_plan_id IS NULL AND origin_phase IS NULL) OR "
            "(actor_account_id IS NULL AND session_hash IS NULL "
            "AND origin_plan_id IS NOT NULL "
            "AND origin_phase IN ('activation', 'restoration'))",
            name="ck_console_rule_operation_actor_origin",
        ),
        CheckConstraint(
            "(origin_plan_id IS NULL AND origin_phase IS NULL) OR "
            "(origin_plan_id IS NOT NULL AND origin_phase IS NOT NULL "
            "AND mutation_kind = 'publish')",
            name="ck_console_rule_operation_plan_phase",
        ),
        UniqueConstraint(
            "origin_plan_id", "origin_phase",
            name="uq_console_rule_operation_plan_phase",
        ),
    )

    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    binding_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="RESTRICT"),
        nullable=True,
    )
    session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_plan_id: Mapped[str | None] = mapped_column(
        String(200),
        ForeignKey("console_rule_activation_plan.plan_id", ondelete="RESTRICT"),
        nullable=True,
    )
    origin_phase: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fingerprint_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    mutation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    work_payload: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    work_claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    work_lease_expires_at: Mapped[datetime | None] = mapped_column(
        _LEASE_TIMESTAMP, nullable=True
    )
    work_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RuleSetVersionRecord(ConsoleBase):
    """Immutable frozen candidate with complete rule records and validation link."""

    __tablename__ = "console_rule_version"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('flow', 'degrade', 'system', 'authority', 'param')",
            name="ck_console_rule_version_kind",
        ),
        Index(
            "ix_console_rule_version_binding_created",
            "binding_id",
            "created_at",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str] = mapped_column(String(200), nullable=False)
    base_version_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checksum: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False)
    validation_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("console_rule_validation_receipt.validation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    records: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="RESTRICT"),
        nullable=False,
    )


class RuleActivationPlanRecord(ConsoleBase):
    """Durable binding-scoped activation and explicit restoration schedule."""

    __tablename__ = "console_rule_activation_plan"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'activating', 'active', 'restoring', "
            "'completed', 'blocked', 'cancelled')",
            name="ck_console_rule_activation_plan_state",
        ),
        CheckConstraint(
            "deactivate_at > activate_at",
            name="ck_console_rule_activation_plan_window",
        ),
        CheckConstraint(
            "claim_attempt_count >= 0",
            name="ck_console_rule_activation_plan_claim_attempts",
        ),
        CheckConstraint(
            "(claim_token IS NULL AND claim_lease_expires_at IS NULL) OR "
            "(claim_token IS NOT NULL AND claim_lease_expires_at IS NOT NULL)",
            name="ck_console_rule_activation_plan_claim_lease",
        ),
        Index(
            "ix_console_rule_activation_plan_binding_window",
            "binding_id", "state", "activate_at", "deactivate_at",
        ),
        Index(
            "ix_console_rule_activation_plan_due",
            "state", "activate_at", "deactivate_at", "claim_lease_expires_at",
        ),
    )

    plan_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[str] = mapped_column(String(200), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(200), nullable=False)
    version_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("console_rule_version.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    restore_version_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("console_rule_version.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    activate_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivate_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    activation_publication_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    restore_publication_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_lease_expires_at: Mapped[datetime | None] = mapped_column(
        _LEASE_TIMESTAMP, nullable=True
    )
    claim_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="RESTRICT"),
        nullable=False,
    )


class RulePublicationRecord(ConsoleBase):
    """Durable, phase-separated source publication facts."""

    __tablename__ = "console_rule_publication"
    __table_args__ = (
        CheckConstraint(
            "validation_state IN ('awaiting', 'running', 'succeeded', 'failed', 'unknown')",
            name="ck_console_rule_publication_validation_state",
        ),
        CheckConstraint(
            "write_state IN ('awaiting', 'running', 'succeeded', 'failed', 'unknown')",
            name="ck_console_rule_publication_write_state",
        ),
        CheckConstraint(
            "read_back_state IN ('awaiting', 'running', 'succeeded', 'failed', 'unknown')",
            name="ck_console_rule_publication_readback_state",
        ),
        CheckConstraint(
            "validation_reason IS NULL OR validation_reason IN "
            "('conflict', 'unavailable', 'rejected', 'readback_mismatch', 'unsupported', 'unknown')",
            name="ck_console_rule_publication_validation_reason",
        ),
        CheckConstraint(
            "write_reason IS NULL OR write_reason IN "
            "('conflict', 'unavailable', 'rejected', 'readback_mismatch', 'unsupported', 'unknown')",
            name="ck_console_rule_publication_write_reason",
        ),
        CheckConstraint(
            "read_back_reason IS NULL OR read_back_reason IN "
            "('conflict', 'unavailable', 'rejected', 'readback_mismatch', 'unsupported', 'unknown')",
            name="ck_console_rule_publication_readback_reason",
        ),
        Index(
            "ix_console_rule_publication_binding_created",
            "binding_id", "created_at", "publication_id",
        ),
    )

    publication_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(200), nullable=False)
    target_version_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("console_rule_version.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_checksum: Mapped[str] = mapped_column(String(200), nullable=False)
    base_version_id: Mapped[str | None] = mapped_column(
        String(200), ForeignKey("console_rule_version.version_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_state: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    validation_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    write_state: Mapped[str] = mapped_column(String(16), nullable=False)
    write_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    write_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    read_back_state: Mapped[str] = mapped_column(String(16), nullable=False)
    read_back_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    read_back_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class RulePublicationReceiptRecord(ConsoleBase):
    """Latest trusted runtime outcome for one instance and publication."""

    __tablename__ = "console_rule_publication_receipt"
    __table_args__ = (
        CheckConstraint(
            "state IN ('applied', 'pending', 'failed', 'unknown', 'restart_required')",
            name="ck_console_rule_publication_receipt_state",
        ),
    )

    publication_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("console_rule_publication.publication_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    instance_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(200), nullable=False)
    process_epoch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    loaded_process_epoch: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    target_version_id: Mapped[str] = mapped_column(String(200), nullable=False)
    loaded_version_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    loaded_checksum: Mapped[str | None] = mapped_column(String(200), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(
        _MILLISECOND_TIMESTAMP, nullable=True
    )
    last_report_at: Mapped[datetime | None] = mapped_column(
        _MILLISECOND_TIMESTAMP, nullable=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)


class RulePublicationTargetRecord(ConsoleBase):
    """Exact non-secret provider target owned by one rule binding."""

    __tablename__ = "console_rule_publication_target"
    __table_args__ = (
        Index("ix_console_rule_publication_target_source", "source_id"),
    )

    binding_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    target_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    target_body: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RuleBindingRecord(ConsoleBase):
    """Console-owned binding metadata, separate from configuration-center rules."""

    __tablename__ = "console_rule_binding"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('flow', 'degrade', 'system', 'authority', 'param')",
            name="ck_console_rule_binding_kind",
        ),
        UniqueConstraint(
            "environment_id", "app_id", "kind",
            name="uq_console_rule_binding_scope_kind",
        ),
        Index("ix_console_rule_binding_scope", "environment_id", "app_id", "kind"),
    )

    binding_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    environment_id: Mapped[str] = mapped_column(String(200), nullable=False)
    app_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str] = mapped_column(String(200), nullable=False)
    source_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("console_registered_source.source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    location: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RuleBindingRegistrationOperationRecord(ConsoleBase):
    """Idempotency receipt for binding creation; no rule bodies or credentials."""

    __tablename__ = "console_rule_binding_registration_operation"
    __table_args__ = (
        Index(
            "ix_console_rule_binding_registration_actor",
            "actor_account_id",
            "created_at",
        ),
    )

    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("console_account.account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("console_rule_binding.binding_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRecord(ConsoleBase):
    """Bounded audit fact without request body, secret, rule content, or traceback."""

    __tablename__ = "console_audit_event"
    __table_args__ = (
        Index("ix_console_audit_created_event", "created_at", "event_id"),
        Index("ix_console_audit_actor_created", "actor_account_id", "created_at"),
        CheckConstraint(
            "outcome IN ('accepted', 'completed', 'rejected')",
            name="ck_console_audit_outcome",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("console_account.account_id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    target_kind: Mapped[str | None] = mapped_column(String(48), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
