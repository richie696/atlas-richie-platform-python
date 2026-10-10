"""Explicit SQL composition of the Console's account identity capabilities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
import ssl

from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette

from ...api.client_address import ClientAddressResolver
from ...application.account_commands import MutateAccount
from ...application.account_directory_ports import AccountDirectoryReader
from ...application.authorize_bootstrap import BootstrapAuthorizationAuthority
from ...application.bootstrap_ports import (
    BootstrapInitializationReader,
    BootstrapOperatorSessionVerifier,
    SetupWindowReader,
)
from ...application.bootstrap_initialization import (
    BootstrapInitializationOperationReader,
    BootstrapInitializer,
)
from ...application.bootstrap_database_check import BootstrapDatabaseChecker
from ...application.bootstrap_source_check import BootstrapSourceChecker
from ...application.check_registered_source import RegisteredSourceChecker
from ...application.source_credential_references import (
    SourceCredentialReferenceResolver,
)
from ...application.login import Login
from ...application.change_own_password import ChangeOwnPassword
from ...application.mutate_rule_set import (
    RuleMutationAuthority,
    RuleMutationBindingReader,
)
from ...application.rule_binding_ports import RuleBindingDirectoryReader
from ...application.session_ports import CurrentSessionReader
from ...application.session_revocation_ports import CurrentSessionRevoker
from ...application.system_connections_ports import SystemConnectionsReader
from ...application.system_protocols_ports import SystemProtocolsReader
from ...application.system_audit_ports import SystemAuditReader
from ...application.observation_catalog_ports import ObservationCatalogReader
from ...application.instance_catalog_ports import (
    InstanceCatalogReader,
    InstanceObservationReader,
)
from ...application.metrics_ports import MetricsReader
from ...application.fleet_overview_ports import FleetOverviewReader
from ...application.incident_timeline_ports import IncidentTimelineReader
from ...application.incident_evidence_ports import IncidentEvidenceReader
from ...application.run_rule_publication_worker import RunRulePublicationWorker
from ...application.run_rule_activation_plan_worker import RunRuleActivationPlanWorker
from ..registered_source_checker import RegisteredSourceTargetRule
from ..registered_source_checker_composition import (
    compose_provider_registered_source_checker,
)
from ..security.account_command_keys import AccountCommandKeyConfiguration
from ..security.client_identity_key import ClientIdentityKeyConfiguration
from ..security.password_hash import PasswordHashService
from ..security.registered_source_keys import RegisteredSourceKeyConfiguration
from ..security.rule_command_keys import RuleCommandKeyConfiguration
from .account_command_composition import compose_sql_account_commands
from .account_directory_reader import SqlAlchemyAccountDirectoryReader
from .bootstrap_initialization_reader import SqlAlchemyBootstrapInitializationReader
from .current_session_reader import SqlAlchemyCurrentSessionReader
from .current_session_revoker import SqlAlchemyCurrentSessionRevoker
from .login_composition import compose_sql_login
from .login_attempt_configuration import LoginAttemptLimitConfiguration
from .login_attempt_limiter import SqlAlchemyLoginAttemptLimiter
from .own_password_credential_reader import SqlAlchemyOwnPasswordCredentialReader
from .own_password_writer import SqlAlchemyOwnPasswordWriter
from .rule_draft_reader import SqlAlchemyRuleDraftReader
from .rule_binding_directory_reader import SqlAlchemyRuleBindingDirectoryReader
from .rule_binding_registration_store import SqlAlchemyRuleBindingRegistrationStore
from .rule_mutation_composition import compose_sql_rule_mutation_authority
from .rule_version_reader import SqlAlchemyRuleVersionReader
from .rule_activation_plan_reader import SqlAlchemyRuleActivationPlanReader
from .rule_publication_reader import SqlAlchemyRulePublicationReader
from .rule_publication_receipt_store import SqlAlchemyRulePublicationReceiptStore
from .rule_publication_target_reader import SqlAlchemyRulePublicationTargetReader
from .system_audit_reader import SqlAlchemySystemAuditReader
from .registered_source_composition import compose_registered_source_store
from ..registered_source_connections_reader import (
    RegisteredSourceSystemConnectionsReader,
)
from .runtime_database_engine_provider import RuntimeDatabaseEngineProvider
from .runtime_database_lifecycle import install_runtime_database_lifecycle
from .bootstrap_authorization_file_authority import (
    BootstrapAuthorizationConfiguration,
)


@dataclass(frozen=True, slots=True)
class SqlIdentityRuntime:
    """Already-provisioned SQL identity services ready for ASGI assembly."""

    account_directory_reader: AccountDirectoryReader
    current_session_reader: CurrentSessionReader
    current_session_revoker: CurrentSessionRevoker
    login_service: Login
    account_command_service: MutateAccount
    own_password_service: ChangeOwnPassword
    client_identity_hmac_key: bytes = field(repr=False)


def compose_sql_identity_runtime(
    engine: AsyncEngine,
    *,
    attempt_limit: LoginAttemptLimitConfiguration,
    account_command_keys: AccountCommandKeyConfiguration,
    client_identity_key: ClientIdentityKeyConfiguration,
    session_ttl: timedelta,
) -> SqlIdentityRuntime:
    """Compose SQL account use cases while sharing one Argon2 policy object.

    The supplied engine remains caller-owned. This function neither connects,
    migrates nor starts the ASGI application.
    """
    password_hasher = PasswordHashService()
    return SqlIdentityRuntime(
        account_directory_reader=SqlAlchemyAccountDirectoryReader(engine),
        current_session_reader=SqlAlchemyCurrentSessionReader(engine),
        current_session_revoker=SqlAlchemyCurrentSessionRevoker(engine),
        login_service=compose_sql_login(
            engine,
            attempt_limit=attempt_limit,
            session_ttl=session_ttl,
            password_hasher=password_hasher,
        ),
        account_command_service=compose_sql_account_commands(
            engine,
            account_command_keys,
            password_hasher=password_hasher,
        ),
        own_password_service=ChangeOwnPassword(
            reader=SqlAlchemyOwnPasswordCredentialReader(engine),
            writer=SqlAlchemyOwnPasswordWriter(engine),
            password_hasher=password_hasher,
            attempt_limiter=SqlAlchemyLoginAttemptLimiter(
                engine,
                policy=attempt_limit.to_policy(),
            ),
            attempt_hmac_key=client_identity_key.hmac_key,
        ),
        client_identity_hmac_key=client_identity_key.hmac_key,
    )


def build_sql_identity_app(
    engine: AsyncEngine,
    *,
    attempt_limit: LoginAttemptLimitConfiguration,
    account_command_keys: AccountCommandKeyConfiguration,
    client_identity_key: ClientIdentityKeyConfiguration,
    session_ttl: timedelta,
    setup_window_reader: SetupWindowReader,
    bootstrap_operator_verifier: BootstrapOperatorSessionVerifier | None = None,
    bootstrap_authorization_authority: BootstrapAuthorizationAuthority | None = None,
    allowed_browser_origins: frozenset[str],
    client_address_resolver: ClientAddressResolver | None = None,
    bootstrap_initialization_reader: BootstrapInitializationReader | None = None,
    bootstrap_initializer: BootstrapInitializer | None = None,
    bootstrap_initialization_operation_reader: (
        BootstrapInitializationOperationReader | None
    ) = None,
    bootstrap_database_checker: BootstrapDatabaseChecker | None = None,
    runtime_database_provider: RuntimeDatabaseEngineProvider | None = None,
    bootstrap_authorization_configuration: (
        BootstrapAuthorizationConfiguration | None
    ) = None,
    registered_source_keys: RegisteredSourceKeyConfiguration | None = None,
    bootstrap_source_checker: BootstrapSourceChecker | None = None,
    source_credential_reference_resolver: SourceCredentialReferenceResolver | None = None,
    registered_source_checker: RegisteredSourceChecker | None = None,
    registered_source_target_rules: Sequence[RegisteredSourceTargetRule] | None = None,
    registered_source_ssl_context: ssl.SSLContext | None = None,
    system_connections_reader: SystemConnectionsReader | None = None,
    system_audit_reader: SystemAuditReader | None = None,
    system_protocols_reader: SystemProtocolsReader | None = None,
    observation_catalog_reader: ObservationCatalogReader | None = None,
    instance_catalog_reader: InstanceCatalogReader | None = None,
    instance_observation_reader: InstanceObservationReader | None = None,
    metrics_reader: MetricsReader | None = None,
    fleet_overview_reader: FleetOverviewReader | None = None,
    incident_timeline_reader: IncidentTimelineReader | None = None,
    incident_evidence_reader: IncidentEvidenceReader | None = None,
    rule_mutation_authority: RuleMutationAuthority | None = None,
    rule_command_keys: RuleCommandKeyConfiguration | None = None,
    rule_mutation_binding_reader: RuleMutationBindingReader | None = None,
    rule_binding_reader: RuleBindingDirectoryReader | None = None,
    rule_publication_worker: RunRulePublicationWorker | None = None,
    publication_worker_poll_interval_seconds: float = 1.0,
    publication_worker_batch_size: int = 10,
    rule_activation_plan_worker: RunRuleActivationPlanWorker | None = None,
    activation_plan_worker_poll_interval_seconds: float = 1.0,
    activation_plan_worker_batch_size: int = 10,
    dashboard_web_directory: Path | None = None,
    dashboard_base_path: str = "/",
) -> Starlette:
    """Build the identity-enabled ASGI app for SQL-backed capabilities.

    Bootstrap setup-window, operator verification, and initialization-write
    authorities remain deployment-owned inputs. When ``runtime_database_provider``
    is supplied, its ASGI lifecycle owns runtime engine activation, migrations,
    and disposal; otherwise the caller owns the supplied engine lifecycle.
    """
    from ...app import build_app

    if bootstrap_authorization_configuration is not None:
        if (
            bootstrap_operator_verifier is not None
            or bootstrap_authorization_authority is not None
        ):
            raise ValueError(
                "inject either bootstrap authority configuration or explicit ports"
            )
        authority = bootstrap_authorization_configuration.create_authority(
            setup_window_reader
        )
        bootstrap_operator_verifier = authority
        bootstrap_authorization_authority = authority

    if runtime_database_provider is not None and any(
        dependency is None
        for dependency in (
            bootstrap_initialization_reader,
            bootstrap_initializer,
            bootstrap_initialization_operation_reader,
            bootstrap_database_checker,
        )
    ):
        raise ValueError(
            "lazy runtime database requires the complete bootstrap coordinator"
        )

    runtime = compose_sql_identity_runtime(
        engine,
        attempt_limit=attempt_limit,
        account_command_keys=account_command_keys,
        client_identity_key=client_identity_key,
        session_ttl=session_ttl,
    )
    registered_source_store = (
        compose_registered_source_store(engine, registered_source_keys)
        if registered_source_keys is not None
        else None
    )
    if system_connections_reader is None and registered_source_store is not None:
        system_connections_reader = RegisteredSourceSystemConnectionsReader(
            registered_source_store,
            registered_source_store,
        )
    if system_audit_reader is None:
        system_audit_reader = SqlAlchemySystemAuditReader(engine)
    if (
        registered_source_checker is not None
        and registered_source_target_rules is not None
    ):
        raise ValueError("inject either a source checker or target rules, not both")
    if registered_source_target_rules is not None:
        registered_source_checker = compose_provider_registered_source_checker(
            registered_source_target_rules,
            ssl_context=registered_source_ssl_context,
        )
    if (rule_command_keys is None) != (rule_mutation_binding_reader is None):
        raise ValueError(
            "rule-command keys and authoritative binding reader must be provided together"
        )
    if rule_mutation_authority is not None and rule_command_keys is not None:
        raise ValueError(
            "inject either a rule mutation authority or its SQL composition inputs"
        )
    if rule_command_keys is not None and rule_mutation_binding_reader is not None:
        rule_mutation_authority = compose_sql_rule_mutation_authority(
            engine,
            rule_command_keys,
            binding_reader=rule_mutation_binding_reader,
        )
    rule_draft_reader = SqlAlchemyRuleDraftReader(engine)
    if rule_binding_reader is None:
        rule_binding_reader = SqlAlchemyRuleBindingDirectoryReader(engine)
    rule_version_reader = SqlAlchemyRuleVersionReader(engine)
    rule_publication_reader = SqlAlchemyRulePublicationReader(engine)
    app = build_app(
        bootstrap_initialization_reader=(
            bootstrap_initialization_reader
            if bootstrap_initialization_reader is not None
            else SqlAlchemyBootstrapInitializationReader(engine)
        ),
        setup_window_reader=setup_window_reader,
        bootstrap_operator_verifier=bootstrap_operator_verifier,
        current_session_reader=runtime.current_session_reader,
        current_session_revoker=runtime.current_session_revoker,
        account_directory_reader=runtime.account_directory_reader,
        allowed_browser_origins=allowed_browser_origins,
        client_address_resolver=client_address_resolver,
        login_service=runtime.login_service,
        client_identity_hmac_key=runtime.client_identity_hmac_key,
        account_command_service=runtime.account_command_service,
        own_password_service=runtime.own_password_service,
        bootstrap_authorization_authority=bootstrap_authorization_authority,
        bootstrap_initializer=bootstrap_initializer,
        bootstrap_initialization_operation_reader=(
            bootstrap_initialization_operation_reader
        ),
        bootstrap_database_checker=bootstrap_database_checker,
        bootstrap_source_checker=bootstrap_source_checker,
        source_credential_reference_resolver=source_credential_reference_resolver,
        registered_sources_reader=registered_source_store,
        system_connections_reader=system_connections_reader,
        system_audit_reader=system_audit_reader,
        system_protocols_reader=system_protocols_reader,
        observation_catalog_reader=observation_catalog_reader,
        instance_catalog_reader=instance_catalog_reader,
        instance_observation_reader=instance_observation_reader,
        metrics_reader=metrics_reader,
        fleet_overview_reader=fleet_overview_reader,
        incident_timeline_reader=incident_timeline_reader,
        incident_evidence_reader=incident_evidence_reader,
        registered_source_checker=registered_source_checker,
        registered_source_credential_resolver=registered_source_store,
        registered_source_probe_recorder=registered_source_store,
        registered_source_mutation_authority=registered_source_store,
        rule_draft_reader=rule_draft_reader,
        rule_draft_detail_reader=rule_draft_reader,
        rule_binding_reader=rule_binding_reader,
        rule_binding_registration_authority=(
            SqlAlchemyRuleBindingRegistrationStore(engine)
        ),
        rule_set_version_reader=rule_version_reader,
        rule_set_version_detail_reader=rule_version_reader,
        rule_publication_reader=rule_publication_reader,
        rule_publication_detail_reader=rule_publication_reader,
        rule_publication_receipt_reader=SqlAlchemyRulePublicationReceiptStore(
            engine
        ),
        rule_publication_target_reader=SqlAlchemyRulePublicationTargetReader(engine),
        rule_activation_plan_reader=SqlAlchemyRuleActivationPlanReader(engine),
        rule_mutation_authority=rule_mutation_authority,
        rule_publication_worker=rule_publication_worker,
        publication_worker_poll_interval_seconds=(
            publication_worker_poll_interval_seconds
        ),
        publication_worker_batch_size=publication_worker_batch_size,
        rule_activation_plan_worker=rule_activation_plan_worker,
        activation_plan_worker_poll_interval_seconds=(
            activation_plan_worker_poll_interval_seconds
        ),
        activation_plan_worker_batch_size=activation_plan_worker_batch_size,
        dashboard_web_directory=dashboard_web_directory,
        dashboard_base_path=dashboard_base_path,
    )
    if runtime_database_provider is not None:
        install_runtime_database_lifecycle(app, runtime_database_provider)
    return app
