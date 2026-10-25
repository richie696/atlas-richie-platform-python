"""Explicit SQL composition of the Console's account identity capabilities."""

from __future__ import annotations

import ssl
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette

from ...api.client_address import ClientAddressResolver
from ...application.account_commands import MutateAccount
from ...application.account_directory_ports import AccountDirectoryReader
from ...application.authorize_bootstrap import BootstrapAuthorizationAuthority
from ...application.bootstrap_database_check import BootstrapDatabaseChecker
from ...application.bootstrap_initialization import (
    BootstrapInitializationOperationReader,
    BootstrapInitializer,
)
from ...application.bootstrap_ports import (
    BootstrapInitializationReader,
    BootstrapOperatorSessionVerifier,
    SetupWindowReader,
)
from ...application.bootstrap_source_check import BootstrapSourceChecker
from ...application.change_own_password import ChangeOwnPassword
from ...application.check_monitoring_source import CheckMonitoringSource
from ...application.check_registered_source import RegisteredSourceChecker
from ...application.deployment_guides import DeploymentGuidesReader
from ...application.fleet_overview_ports import FleetOverviewReader
from ...application.incident_evidence_ports import IncidentEvidenceReader
from ...application.incident_timeline_ports import IncidentTimelineReader
from ...application.instance_catalog_ports import (
    InstanceCatalogReader,
    InstanceObservationReader,
)
from ...application.login import Login
from ...application.metrics_ports import MetricsReader
from ...application.monitoring_probe import MonitoringCredentialReferenceResolver
from ...application.monitoring_source_registry import MonitoringSourceRegistryPort
from ...application.mutate_rule_set import (
    RuleMutationAuthority,
    RuleMutationBindingReader,
)
from ...application.observation_catalog_ports import ObservationCatalogReader
from ...application.protocol_negotiation_ports import (
    AgentReportingNegotiationReader,
    IncidentEventNegotiationReader,
)
from ...application.read_host_metrics import HostMetricsQueryPort
from ...application.read_rule_binding_states import ReadRuleBindingStates
from ...application.read_rule_catalog import ReadRuleCatalog
from ...application.read_rule_load_observation_history import (
    ReadRuleLoadObservationHistory,
)
from ...application.read_rule_load_observations import ReadRuleLoadObservations
from ...application.refresh_rule_catalog import RefreshRuleCatalog
from ...application.rule_binding_ports import (
    RuleBindingDirectoryReader,
    RuleBindingScopeReader,
)
from ...application.rule_snapshot_ports import RuleSetSnapshotReader
from ...application.run_rule_activation_plan_worker import RunRuleActivationPlanWorker
from ...application.run_rule_load_observation_projection_worker import (
    RunRuleLoadObservationProjectionWorker,
)
from ...application.run_rule_publication_receipt_projection_worker import (
    RunRulePublicationReceiptProjectionWorker,
)
from ...application.run_rule_publication_worker import RunRulePublicationWorker
from ...application.session_ports import CurrentSessionReader
from ...application.session_revocation_ports import CurrentSessionRevoker
from ...application.source_credential_references import (
    SourceCredentialReferenceResolver,
)
from ...application.system_audit_ports import SystemAuditReader
from ...application.system_connections_ports import SystemConnectionsReader
from ...application.system_protocols_ports import SystemProtocolsReader
from ..monitoring_probe_composition import (
    compose_prometheus_host_metrics_adapter,
    compose_prometheus_http_adapter,
)
from ..monitoring_target_policy import MonitoringTargetRule
from ..registered_source_checker import RegisteredSourceTargetRule
from ..registered_source_checker_composition import (
    compose_provider_registered_source_checker,
)
from ..registered_source_connections_reader import (
    RegisteredSourceSystemConnectionsReader,
)
from ..security.account_command_keys import AccountCommandKeyConfiguration
from ..security.client_identity_key import ClientIdentityKeyConfiguration
from ..security.password_hash import PasswordHashService
from .system_settings_store import SqlAlchemySystemSettingsStore
from ..security.registered_source_keys import RegisteredSourceKeyConfiguration
from ..security.rule_command_keys import RuleCommandKeyConfiguration
from ..sentinel_java_go_v1_validator import (
    SentinelGoV1RuleCandidateValidator,
    SentinelJavaV1RuleCandidateValidator,
    SentinelRustV1RuleCandidateValidator,
    SentinelRuleCandidateValidatorRegistry,
)
from ..sentinel_python_v1_validator import SentinelPythonV1RuleCandidateValidator
from ..unobserved_system_protocols_reader import UnobservedSystemProtocolsReader
from .account_command_composition import compose_sql_account_commands
from .account_directory_reader import SqlAlchemyAccountDirectoryReader
from .bootstrap_authorization_file_authority import (
    BootstrapAuthorizationConfiguration,
)
from .bootstrap_initialization_reader import SqlAlchemyBootstrapInitializationReader
from .current_session_reader import SqlAlchemyCurrentSessionReader
from .current_session_revoker import SqlAlchemyCurrentSessionRevoker
from .host_association_store import SQLAlchemyHostAssociationStore
from .incident_event_adapter import SQLAlchemyIncidentEventAdapter
from .login_attempt_configuration import LoginAttemptLimitConfiguration
from .login_attempt_dialect_adapters import LoginAttemptDialectAdapter
from .login_attempt_limiter import SqlAlchemyLoginAttemptLimiter
from .login_composition import compose_sql_login
from .metrics_fleet_overview_reader import SQLAlchemyMetricsFleetOverviewReader
from .metrics_history_reader import SQLAlchemyMetricsHistoryReader
from .metrics_instance_catalog_reader import SQLAlchemyMetricsInstanceCatalogReader
from .metrics_instance_observation_reader import (
    SQLAlchemyMetricsInstanceObservationReader,
)
from .metrics_observation_catalog_reader import (
    SQLAlchemyMetricsObservationCatalogReader,
)
from .monitoring_probe_receipt_store import SQLAlchemyMonitoringProbeReceiptStore
from .monitoring_source_store import SQLAlchemyMonitoringSourceStore
from .own_password_credential_reader import SqlAlchemyOwnPasswordCredentialReader
from .own_password_writer import SqlAlchemyOwnPasswordWriter
from .protocol_negotiation_store import SQLAlchemyProtocolNegotiationStore
from .registered_source_composition import compose_registered_source_store
from .rule_activation_plan_reader import SqlAlchemyRuleActivationPlanReader
from .rule_binding_directory_reader import SqlAlchemyRuleBindingDirectoryReader
from .rule_binding_registration_store import SqlAlchemyRuleBindingRegistrationStore
from .rule_draft_reader import SqlAlchemyRuleDraftReader
from .rule_load_observation_projection_queue import (
    SqlAlchemyRuleLoadObservationProjectionQueue,
)
from .rule_mutation_composition import compose_sql_rule_mutation_authority
from .rule_publication_reader import SqlAlchemyRulePublicationReader
from .rule_publication_receipt_projection_queue import (
    SqlAlchemyRulePublicationReceiptProjectionQueue,
)
from .rule_publication_receipt_store import SqlAlchemyRulePublicationReceiptStore
from .rule_publication_target_reader import SqlAlchemyRulePublicationTargetReader
from .rule_validation_receipt_store import SqlAlchemyRuleValidationReceiptStore
from .rule_version_reader import SqlAlchemyRuleVersionReader
from .runtime_database_engine_provider import RuntimeDatabaseEngineProvider
from .runtime_database_lifecycle import install_runtime_database_lifecycle
from .system_audit_reader import SqlAlchemySystemAuditReader


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
    additional_login_attempt_dialect_adapters: tuple[
        LoginAttemptDialectAdapter, ...
    ] = (),
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
            additional_login_attempt_dialect_adapters=(
                additional_login_attempt_dialect_adapters
            ),
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
                additional_dialect_adapters=(additional_login_attempt_dialect_adapters),
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
    additional_login_attempt_dialect_adapters: tuple[
        LoginAttemptDialectAdapter, ...
    ] = (),
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
    source_credential_reference_resolver: SourceCredentialReferenceResolver
    | None = None,
    registered_source_checker: RegisteredSourceChecker | None = None,
    registered_source_target_rules: Sequence[RegisteredSourceTargetRule] | None = None,
    registered_source_ssl_context: ssl.SSLContext | None = None,
    monitoring_target_rules: Sequence[MonitoringTargetRule] | None = None,
    monitoring_fingerprint_key: bytes | None = None,
    monitoring_ssl_context: ssl.SSLContext | None = None,
    monitoring_credential_reference_resolver: (
        MonitoringCredentialReferenceResolver | None
    ) = None,
    monitoring_source_registry: MonitoringSourceRegistryPort | None = None,
    system_connections_reader: SystemConnectionsReader | None = None,
    deployment_guides_reader: DeploymentGuidesReader | None = None,
    system_audit_reader: SystemAuditReader | None = None,
    system_protocols_reader: SystemProtocolsReader | None = None,
    agent_reporting_negotiation_reader: AgentReportingNegotiationReader | None = None,
    incident_event_negotiation_reader: IncidentEventNegotiationReader | None = None,
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
    rule_binding_scope_reader: RuleBindingScopeReader | None = None,
    rule_publication_worker: RunRulePublicationWorker | None = None,
    rule_set_snapshot_reader: RuleSetSnapshotReader | None = None,
    rule_catalog_reader: ReadRuleCatalog | None = None,
    rule_catalog_refresher: RefreshRuleCatalog | None = None,
    rule_binding_state_reader: ReadRuleBindingStates | None = None,
    rule_load_observation_reader: ReadRuleLoadObservations | None = None,
    rule_load_observation_history_reader: ReadRuleLoadObservationHistory | None = None,
    publication_worker_poll_interval_seconds: float = 1.0,
    publication_worker_batch_size: int = 10,
    rule_publication_receipt_projection_worker: (
        RunRulePublicationReceiptProjectionWorker | None
    ) = None,
    receipt_projection_worker_poll_interval_seconds: float = 1.0,
    receipt_projection_worker_batch_size: int = 10,
    rule_load_observation_projection_worker: (
        RunRuleLoadObservationProjectionWorker | None
    ) = None,
    rule_load_observation_projection_worker_poll_interval_seconds: float = 1.0,
    rule_load_observation_projection_worker_batch_size: int = 10,
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
        additional_login_attempt_dialect_adapters=(
            additional_login_attempt_dialect_adapters
        ),
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
    if system_protocols_reader is None:
        system_protocols_reader = UnobservedSystemProtocolsReader()

    async def resolve_reporting_engine() -> AsyncEngine:
        if runtime_database_provider is not None:
            return await runtime_database_provider.require_engine()
        return engine

    if metrics_reader is None:
        metrics_reader = SQLAlchemyMetricsHistoryReader(resolve_reporting_engine)
    if observation_catalog_reader is None:
        observation_catalog_reader = SQLAlchemyMetricsObservationCatalogReader(
            resolve_reporting_engine
        )
    if (
        agent_reporting_negotiation_reader is None
        or incident_event_negotiation_reader is None
    ):
        protocol_negotiation_store = SQLAlchemyProtocolNegotiationStore(
            resolve_reporting_engine
        )
        if agent_reporting_negotiation_reader is None:
            agent_reporting_negotiation_reader = protocol_negotiation_store
        if incident_event_negotiation_reader is None:
            incident_event_negotiation_reader = protocol_negotiation_store
    if instance_catalog_reader is None:
        instance_catalog_reader = SQLAlchemyMetricsInstanceCatalogReader(
            resolve_reporting_engine
        )
    if instance_observation_reader is None:
        instance_observation_reader = SQLAlchemyMetricsInstanceObservationReader(
            catalog_reader=instance_catalog_reader,
            metrics_reader=metrics_reader,
        )
    if fleet_overview_reader is None:
        fleet_overview_reader = SQLAlchemyMetricsFleetOverviewReader(
            resolve_reporting_engine, metrics_reader
        )
    if incident_timeline_reader is None or incident_evidence_reader is None:
        incident_event_adapter = SQLAlchemyIncidentEventAdapter(
            resolve_reporting_engine
        )
        if incident_timeline_reader is None:
            incident_timeline_reader = incident_event_adapter
        if incident_evidence_reader is None:
            incident_evidence_reader = incident_event_adapter

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
    if (monitoring_target_rules is None) != (monitoring_fingerprint_key is None):
        raise ValueError(
            "monitoring target rules and fingerprint key must be provided together"
        )
    monitoring_source_checker = None
    monitoring_host_metrics_query_port: HostMetricsQueryPort | None = None
    monitoring_probe_receipt_store = None
    if monitoring_source_registry is None and registered_source_keys is not None:
        monitoring_source_registry = SQLAlchemyMonitoringSourceStore(
            resolve_reporting_engine,
            registered_source_keys.create_secret_cipher(),
            fingerprint_key=monitoring_fingerprint_key,
        )
    if monitoring_target_rules is not None and monitoring_fingerprint_key is not None:
        monitoring_probe_receipt_store = SQLAlchemyMonitoringProbeReceiptStore(
            resolve_reporting_engine
        )
        monitoring_source_checker = CheckMonitoringSource(
            compose_prometheus_http_adapter(
                monitoring_target_rules,
                ssl_context=monitoring_ssl_context,
            ),
            monitoring_probe_receipt_store,
            fingerprint_key=monitoring_fingerprint_key,
        )
        monitoring_host_metrics_query_port = compose_prometheus_host_metrics_adapter(
            monitoring_target_rules,
            ssl_context=monitoring_ssl_context,
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
    rule_binding_registration_store = SqlAlchemyRuleBindingRegistrationStore(engine)
    if rule_binding_reader is None:
        sql_rule_binding_reader = SqlAlchemyRuleBindingDirectoryReader(engine)
        rule_binding_reader = sql_rule_binding_reader
        if rule_binding_scope_reader is None:
            rule_binding_scope_reader = sql_rule_binding_reader
    rule_version_reader = SqlAlchemyRuleVersionReader(engine)
    rule_publication_reader = SqlAlchemyRulePublicationReader(engine)
    rule_validation_receipt_store = SqlAlchemyRuleValidationReceiptStore(engine)
    if rule_publication_receipt_projection_worker is None:
        rule_publication_receipt_projection_worker = (
            RunRulePublicationReceiptProjectionWorker(
                SqlAlchemyRulePublicationReceiptProjectionQueue(engine)
            )
        )
    if rule_load_observation_projection_worker is None:
        rule_load_observation_projection_worker = (
            RunRuleLoadObservationProjectionWorker(
                SqlAlchemyRuleLoadObservationProjectionQueue(engine)
            )
        )
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
        monitoring_source_checker=monitoring_source_checker,
        monitoring_probe_receipt_reader=monitoring_probe_receipt_store,
        monitoring_source_registry=monitoring_source_registry,
        monitoring_host_metrics_query_port=monitoring_host_metrics_query_port,
        host_association_store=SQLAlchemyHostAssociationStore(resolve_reporting_engine),
        monitoring_fingerprint_key=monitoring_fingerprint_key,
        monitoring_credential_reference_resolver=(
            monitoring_credential_reference_resolver
        ),
        registered_sources_reader=registered_source_store,
        system_connections_reader=system_connections_reader,
        system_settings_store=SqlAlchemySystemSettingsStore(engine),
        deployment_guides_reader=deployment_guides_reader,
        system_audit_reader=system_audit_reader,
        system_protocols_reader=system_protocols_reader,
        agent_reporting_negotiation_reader=agent_reporting_negotiation_reader,
        incident_event_negotiation_reader=incident_event_negotiation_reader,
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
        rule_binding_scope_reader=rule_binding_scope_reader,
        rule_binding_registration_authority=rule_binding_registration_store,
        rule_binding_registration_receipt_reader=rule_binding_registration_store,
        rule_set_version_reader=rule_version_reader,
        rule_set_version_detail_reader=rule_version_reader,
        rule_publication_reader=rule_publication_reader,
        rule_publication_detail_reader=rule_publication_reader,
        rule_publication_receipt_reader=SqlAlchemyRulePublicationReceiptStore(engine),
        rule_publication_target_reader=SqlAlchemyRulePublicationTargetReader(engine),
        rule_activation_plan_reader=SqlAlchemyRuleActivationPlanReader(engine),
        rule_mutation_authority=rule_mutation_authority,
        rule_set_snapshot_reader=rule_set_snapshot_reader,
        rule_catalog_reader=rule_catalog_reader,
        rule_catalog_refresher=rule_catalog_refresher,
        rule_binding_state_reader=rule_binding_state_reader,
        rule_load_observation_reader=rule_load_observation_reader,
        rule_load_observation_history_reader=rule_load_observation_history_reader,
        rule_candidate_profile_validator=SentinelRuleCandidateValidatorRegistry(
            (
                SentinelPythonV1RuleCandidateValidator(),
                SentinelJavaV1RuleCandidateValidator(),
                SentinelGoV1RuleCandidateValidator(),
                SentinelRustV1RuleCandidateValidator(),
            )
        ),
        rule_validation_receipt_writer=rule_validation_receipt_store,
        rule_publication_worker=rule_publication_worker,
        publication_worker_poll_interval_seconds=(
            publication_worker_poll_interval_seconds
        ),
        publication_worker_batch_size=publication_worker_batch_size,
        rule_publication_receipt_projection_worker=(
            rule_publication_receipt_projection_worker
        ),
        receipt_projection_worker_poll_interval_seconds=(
            receipt_projection_worker_poll_interval_seconds
        ),
        receipt_projection_worker_batch_size=receipt_projection_worker_batch_size,
        rule_load_observation_projection_worker=(
            rule_load_observation_projection_worker
        ),
        rule_load_observation_projection_worker_poll_interval_seconds=(
            rule_load_observation_projection_worker_poll_interval_seconds
        ),
        rule_load_observation_projection_worker_batch_size=(
            rule_load_observation_projection_worker_batch_size
        ),
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
