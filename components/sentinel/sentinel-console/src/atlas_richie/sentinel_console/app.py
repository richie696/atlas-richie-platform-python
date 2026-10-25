"""ASGI application composition for the independent Console service."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette

from .api.account_commands import account_command_routes
from .api.accounts import account_directory_routes
from .api.bootstrap import bootstrap_route
from .api.bootstrap_authorize import (
    bootstrap_authorize_route,
    bootstrap_local_authorize_route,
)
from .api.bootstrap_database_check import bootstrap_database_check_route
from .api.bootstrap_initialization import bootstrap_initialization_routes
from .api.bootstrap_source_check import bootstrap_source_check_route
from .api.client_address import ClientAddressResolver
from .api.fleet_overview import fleet_overview_route
from .api.health import process_health_route
from .api.host_associations import host_association_routes
from .api.host_metrics import host_metrics_route
from .api.incident_evidence import incident_evidence_route
from .api.incidents import incidents_route
from .api.instance_catalog import instance_catalog_route
from .api.instance_observation import instance_observation_route
from .api.login import login_route
from .api.logout import logout_route
from .api.metrics import metrics_route
from .api.monitoring_source_checks import monitoring_source_check_routes
from .api.monitoring_sources import (
    monitoring_source_management_routes,
    monitoring_source_read_routes,
)
from .api.observation_catalog import observation_catalog_route
from .api.own_password import own_password_route
from .api.protocol_negotiation_observations import (
    agent_reporting_observations_route,
    incident_event_observations_route,
)
from .api.registered_source_check import registered_source_check_route
from .api.registered_source_commands import registered_source_command_routes
from .api.registered_sources import registered_sources_route
from .api.rule_activation_plans import rule_activation_plans_route
from .api.rule_binding_scopes import rule_binding_scopes_route
from .api.rule_binding_states import rule_binding_states_route
from .api.rule_bindings import rule_bindings_routes
from .api.rule_candidate_diff import rule_candidate_diff_route
from .api.rule_candidate_validation import rule_candidate_validation_route
from .api.rule_catalog import rule_catalog_routes
from .api.rule_commands import rule_mutation_routes
from .api.rule_draft import rule_draft_route
from .api.rule_drafts import rule_drafts_route
from .api.rule_load_observation_history import rule_load_observation_history_route
from .api.rule_load_observations import rule_load_observations_route
from .api.rule_publication_receipts import rule_publication_receipts_route
from .api.rule_publications import rule_publication_routes
from .api.rule_set_snapshot import rule_set_snapshot_route
from .api.rule_versions import rule_versions_routes
from .api.session import session_route
from .api.static_web import dashboard_web_routes
from .api.system_audit import system_audit_route
from .api.system_connections import system_connections_route
from .api.system_deployment_guides import system_deployment_guides_route
from .api.system_protocols import system_protocols_route
from .api.system_settings import SystemSettingsStore, system_settings_routes
from .application.account_commands import MutateAccount
from .application.account_directory_ports import AccountDirectoryReader
from .application.authorize_bootstrap import BootstrapAuthorizationAuthority
from .application.bootstrap_database_check import BootstrapDatabaseChecker
from .application.bootstrap_initialization import (
    BootstrapInitializationOperationReader,
    BootstrapInitializer,
    InitializeConsole,
    ReadBootstrapInitialization,
)
from .application.bootstrap_ports import (
    BootstrapInitializationReader,
    BootstrapOperatorSessionVerifier,
    SetupWindowReader,
)
from .application.bootstrap_source_check import (
    BootstrapSourceChecker,
    CheckBootstrapSource,
)
from .application.change_own_password import ChangeOwnPassword
from .application.check_monitoring_source import (
    CheckMonitoringSource,
    MonitoringProbeReceiptReader,
)
from .application.check_registered_source import (
    CheckRegisteredSource,
    RegisteredSourceChecker,
    RegisteredSourceCredentialResolver,
)
from .application.compare_rule_candidate import CompareRuleCandidate
from .application.deployment_guides import DeploymentGuidesReader
from .application.fleet_overview_ports import FleetOverviewReader
from .application.host_associations import HostAssociationStore
from .application.incident_evidence_ports import IncidentEvidenceReader
from .application.incident_timeline_ports import IncidentTimelineReader
from .application.instance_catalog_ports import (
    InstanceCatalogReader,
    InstanceObservationReader,
)
from .application.login import Login
from .application.metrics_ports import MetricsReader
from .application.monitoring_probe import MonitoringCredentialReferenceResolver
from .application.monitoring_source_registry import MonitoringSourceRegistryPort
from .application.mutate_registered_source import RegisteredSourceMutationAuthority
from .application.mutate_rule_set import RuleMutationAuthority
from .application.observation_catalog_ports import ObservationCatalogReader
from .application.protocol_negotiation_ports import (
    AgentReportingNegotiationReader,
    IncidentEventNegotiationReader,
)
from .application.read_account_directory import ReadAccountDirectory
from .application.read_agent_reporting_negotiations import (
    ReadAgentReportingNegotiations,
    ReadIncidentEventNegotiations,
)
from .application.read_bootstrap import ReadBootstrap
from .application.read_fleet_overview import ReadFleetOverview
from .application.read_host_metrics import HostMetricsQueryPort
from .application.read_incident_evidence import ReadIncidentEvidence
from .application.read_incident_timeline import ReadIncidentTimeline
from .application.read_instance_catalog import ReadInstanceCatalog
from .application.read_instance_observation import ReadInstanceObservation
from .application.read_metrics import ReadMetrics
from .application.read_observation_catalog import ReadObservationCatalog
from .application.read_registered_sources import ReadRegisteredSources
from .application.read_rule_activation_plans import ReadRuleActivationPlans
from .application.read_rule_binding_scopes import ReadRuleBindingScopes
from .application.read_rule_binding_states import ReadRuleBindingStates
from .application.read_rule_bindings import ReadRuleBindings
from .application.read_rule_catalog import ReadRuleCatalog
from .application.read_rule_draft import ReadRuleDraft
from .application.read_rule_drafts import ReadRuleDrafts
from .application.read_rule_load_observation_history import (
    ReadRuleLoadObservationHistory,
)
from .application.read_rule_load_observations import ReadRuleLoadObservations
from .application.read_rule_publication import ReadRulePublication
from .application.read_rule_publication_receipts import ReadRulePublicationReceipts
from .application.read_rule_publication_target import ReadRulePublicationTarget
from .application.read_rule_publications import ReadRulePublications
from .application.read_rule_set_snapshot import ReadRuleSetSnapshot
from .application.read_rule_version import ReadRuleVersion
from .application.read_rule_versions import ReadRuleVersions
from .application.read_session import ReadSession
from .application.read_system_audit import ReadSystemAudit
from .application.read_system_connections import ReadSystemConnections
from .application.read_system_protocols import ReadSystemProtocols
from .application.refresh_rule_catalog import RefreshRuleCatalog
from .application.registered_source_ports import (
    RegisteredSourceProbeRecorder,
    RegisteredSourcesReader,
)
from .application.revoke_current_session import RevokeCurrentSession
from .application.rule_activation_plan_ports import RuleActivationPlanReader
from .application.rule_binding_ports import (
    RuleBindingDirectoryReader,
    RuleBindingRegistrationAuthority,
    RuleBindingRegistrationReceiptReader,
    RuleBindingScopeReader,
)
from .application.rule_draft_detail_ports import RuleDraftDetailReader
from .application.rule_draft_ports import RuleDraftReader
from .application.rule_publication_ports import (
    RulePublicationDetailReader,
    RulePublicationReader,
    RulePublicationReceiptReader,
    RulePublicationTargetReader,
)
from .application.rule_snapshot_ports import RuleSetSnapshotReader
from .application.rule_validation_ports import (
    RuleCandidateProfileValidator,
    RuleValidationReceiptWriter,
)
from .application.rule_version_ports import (
    RuleSetVersionDetailReader,
    RuleSetVersionReader,
)
from .application.run_rule_activation_plan_worker import RunRuleActivationPlanWorker
from .application.run_rule_load_observation_projection_worker import (
    RunRuleLoadObservationProjectionWorker,
)
from .application.run_rule_publication_receipt_projection_worker import (
    RunRulePublicationReceiptProjectionWorker,
)
from .application.run_rule_publication_worker import RunRulePublicationWorker
from .application.session_ports import CurrentSessionReader
from .application.session_revocation_ports import CurrentSessionRevoker
from .application.source_credential_references import (
    SourceCredentialReferenceResolver,
)
from .application.system_audit_ports import SystemAuditReader
from .application.system_connections_ports import SystemConnectionsReader
from .application.system_protocols_ports import SystemProtocolsReader
from .application.validate_rule_candidate import ValidateRuleCandidate
from .infrastructure.rule_activation_plan_worker_lifecycle import (
    install_rule_activation_plan_worker_lifecycle,
)
from .infrastructure.rule_load_observation_projection_worker_lifecycle import (
    install_rule_load_observation_projection_worker_lifecycle,
)
from .infrastructure.rule_publication_receipt_projection_worker_lifecycle import (
    install_rule_publication_receipt_projection_worker_lifecycle,
)
from .infrastructure.rule_publication_worker_lifecycle import (
    install_rule_publication_worker_lifecycle,
)


def build_app(
    *,
    bootstrap_initialization_reader: BootstrapInitializationReader,
    setup_window_reader: SetupWindowReader,
    bootstrap_operator_verifier: BootstrapOperatorSessionVerifier,
    current_session_reader: CurrentSessionReader,
    current_session_revoker: CurrentSessionRevoker,
    account_directory_reader: AccountDirectoryReader,
    allowed_browser_origins: frozenset[str],
    login_service: Login | None = None,
    client_identity_hmac_key: bytes | None = None,
    account_command_service: MutateAccount | None = None,
    own_password_service: ChangeOwnPassword | None = None,
    dashboard_web_directory: Path | None = None,
    dashboard_base_path: str = "/",
    bootstrap_database_checker: BootstrapDatabaseChecker | None = None,
    bootstrap_initializer: BootstrapInitializer | None = None,
    bootstrap_initialization_operation_reader: (
        BootstrapInitializationOperationReader | None
    ) = None,
    bootstrap_source_checker: BootstrapSourceChecker | None = None,
    bootstrap_authorization_authority: BootstrapAuthorizationAuthority | None = None,
    client_address_resolver: ClientAddressResolver | None = None,
    system_audit_reader: SystemAuditReader | None = None,
    system_connections_reader: SystemConnectionsReader | None = None,
    system_settings_store: SystemSettingsStore | None = None,
    deployment_guides_reader: DeploymentGuidesReader | None = None,
    system_protocols_reader: SystemProtocolsReader | None = None,
    monitoring_source_checker: CheckMonitoringSource | None = None,
    monitoring_probe_receipt_reader: MonitoringProbeReceiptReader | None = None,
    monitoring_source_registry: MonitoringSourceRegistryPort | None = None,
    monitoring_fingerprint_key: bytes | None = None,
    monitoring_credential_reference_resolver: (
        MonitoringCredentialReferenceResolver | None
    ) = None,
    monitoring_host_metrics_query_port: HostMetricsQueryPort | None = None,
    host_association_store: HostAssociationStore | None = None,
    agent_reporting_negotiation_reader: AgentReportingNegotiationReader | None = None,
    incident_event_negotiation_reader: IncidentEventNegotiationReader | None = None,
    registered_sources_reader: RegisteredSourcesReader | None = None,
    registered_source_checker: RegisteredSourceChecker | None = None,
    registered_source_credential_resolver: RegisteredSourceCredentialResolver
    | None = None,
    registered_source_probe_recorder: RegisteredSourceProbeRecorder | None = None,
    source_credential_reference_resolver: SourceCredentialReferenceResolver
    | None = None,
    registered_source_mutation_authority: RegisteredSourceMutationAuthority
    | None = None,
    observation_catalog_reader: ObservationCatalogReader | None = None,
    instance_catalog_reader: InstanceCatalogReader | None = None,
    instance_observation_reader: InstanceObservationReader | None = None,
    metrics_reader: MetricsReader | None = None,
    fleet_overview_reader: FleetOverviewReader | None = None,
    incident_timeline_reader: IncidentTimelineReader | None = None,
    incident_evidence_reader: IncidentEvidenceReader | None = None,
    rule_binding_reader: RuleBindingDirectoryReader | None = None,
    rule_binding_scope_reader: RuleBindingScopeReader | None = None,
    rule_binding_registration_authority: (
        RuleBindingRegistrationAuthority | None
    ) = None,
    rule_binding_registration_receipt_reader: (
        RuleBindingRegistrationReceiptReader | None
    ) = None,
    rule_catalog_reader: ReadRuleCatalog | None = None,
    rule_catalog_refresher: RefreshRuleCatalog | None = None,
    rule_binding_state_reader: ReadRuleBindingStates | None = None,
    rule_load_observation_reader: ReadRuleLoadObservations | None = None,
    rule_load_observation_history_reader: ReadRuleLoadObservationHistory | None = None,
    rule_draft_reader: RuleDraftReader | None = None,
    rule_draft_detail_reader: RuleDraftDetailReader | None = None,
    rule_set_snapshot_reader: RuleSetSnapshotReader | None = None,
    rule_candidate_profile_validator: RuleCandidateProfileValidator | None = None,
    rule_validation_receipt_writer: RuleValidationReceiptWriter | None = None,
    rule_set_version_reader: RuleSetVersionReader | None = None,
    rule_set_version_detail_reader: RuleSetVersionDetailReader | None = None,
    rule_publication_reader: RulePublicationReader | None = None,
    rule_publication_detail_reader: RulePublicationDetailReader | None = None,
    rule_publication_receipt_reader: RulePublicationReceiptReader | None = None,
    rule_publication_target_reader: RulePublicationTargetReader | None = None,
    rule_activation_plan_reader: RuleActivationPlanReader | None = None,
    rule_mutation_authority: RuleMutationAuthority | None = None,
    rule_publication_worker: RunRulePublicationWorker | None = None,
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
) -> Starlette:
    """Build a Console ASGI app from explicit identity authorities.

    No test/demo in-memory provider is selected implicitly. Production wiring
    must provide durable initialization state, a deployment-owned setup-window
    reader, an operator-session verifier, current-session reader, and account
    directory reader before the app is exposed.
    """
    read_bootstrap = ReadBootstrap(
        initialization_reader=bootstrap_initialization_reader,
        setup_window_reader=setup_window_reader,
        operator_verifier=bootstrap_operator_verifier,
    )
    read_session = ReadSession(current_session_reader)
    routes = [
        process_health_route(),
        bootstrap_route(read_bootstrap),
        bootstrap_authorize_route(
            bootstrap_authorization_authority,
            allowed_browser_origins,
            client_address_resolver,
        ),
        bootstrap_local_authorize_route(
            bootstrap_authorization_authority,
            allowed_browser_origins,
            client_address_resolver,
        ),
        bootstrap_database_check_route(
            read_bootstrap, bootstrap_database_checker, allowed_browser_origins
        ),
        bootstrap_source_check_route(
            read_bootstrap,
            CheckBootstrapSource(
                bootstrap_source_checker,
                source_credential_reference_resolver,
            )
            if bootstrap_source_checker is not None
            else None,
            allowed_browser_origins,
        ),
        *bootstrap_initialization_routes(
            InitializeConsole(read_bootstrap, bootstrap_initializer),
            ReadBootstrapInitialization(
                bootstrap_operator_verifier,
                bootstrap_initialization_operation_reader,
            ),
            allowed_browser_origins,
        ),
        session_route(read_session),
        system_audit_route(
            read_session,
            ReadSystemAudit(system_audit_reader)
            if system_audit_reader is not None
            else None,
        ),
        system_connections_route(
            read_session,
            ReadSystemConnections(system_connections_reader)
            if system_connections_reader is not None
            else None,
        ),
        *(
            system_settings_routes(read_session, system_settings_store, allowed_browser_origins)
            if system_settings_store is not None
            else []
        ),
        system_deployment_guides_route(read_session, deployment_guides_reader),
        system_protocols_route(
            read_session,
            ReadSystemProtocols(system_protocols_reader)
            if system_protocols_reader is not None
            else None,
        ),
        *monitoring_source_check_routes(
            read_session,
            monitoring_source_checker,
            monitoring_probe_receipt_reader,
            allowed_browser_origins,
            monitoring_credential_reference_resolver,
        ),
        *monitoring_source_read_routes(read_session, monitoring_source_registry),
        *monitoring_source_management_routes(
            read_session,
            monitoring_source_registry,
            allowed_browser_origins,
            monitoring_fingerprint_key,
        ),
        host_metrics_route(
            read_session,
            monitoring_source_registry,
            monitoring_host_metrics_query_port,
            monitoring_credential_reference_resolver,
        ),
        *host_association_routes(
            read_session,
            host_association_store,
            allowed_browser_origins,
            monitoring_source_registry,
            monitoring_host_metrics_query_port,
            monitoring_credential_reference_resolver,
        ),
        agent_reporting_observations_route(
            read_session,
            ReadAgentReportingNegotiations(agent_reporting_negotiation_reader)
            if agent_reporting_negotiation_reader is not None
            else None,
        ),
        incident_event_observations_route(
            read_session,
            ReadIncidentEventNegotiations(incident_event_negotiation_reader)
            if incident_event_negotiation_reader is not None
            else None,
        ),
        registered_sources_route(
            read_session,
            ReadRegisteredSources(registered_sources_reader)
            if registered_sources_reader is not None
            else None,
        ),
        registered_source_check_route(
            read_session,
            CheckRegisteredSource(
                registered_source_checker,
                registered_source_credential_resolver,
                source_credential_reference_resolver,
                registered_source_probe_recorder,
            )
            if registered_source_checker is not None
            else None,
            allowed_browser_origins,
        ),
        *registered_source_command_routes(
            read_session,
            registered_source_mutation_authority,
            allowed_browser_origins,
        ),
        observation_catalog_route(
            read_session,
            ReadObservationCatalog(observation_catalog_reader)
            if observation_catalog_reader is not None
            else None,
        ),
        instance_catalog_route(
            read_session,
            ReadInstanceCatalog(instance_catalog_reader)
            if instance_catalog_reader is not None
            else None,
        ),
        instance_observation_route(
            read_session,
            ReadInstanceObservation(instance_observation_reader)
            if instance_observation_reader is not None
            else None,
        ),
        metrics_route(
            read_session,
            ReadMetrics(metrics_reader) if metrics_reader is not None else None,
        ),
        fleet_overview_route(
            read_session,
            ReadFleetOverview(fleet_overview_reader)
            if fleet_overview_reader is not None
            else None,
        ),
        incidents_route(
            read_session,
            ReadIncidentTimeline(incident_timeline_reader)
            if incident_timeline_reader is not None
            else None,
        ),
        incident_evidence_route(
            read_session,
            ReadIncidentEvidence(incident_evidence_reader)
            if incident_evidence_reader is not None
            else None,
        ),
        *rule_bindings_routes(
            read_session,
            ReadRuleBindings(rule_binding_reader)
            if rule_binding_reader is not None
            else None,
            rule_binding_registration_authority,
            rule_binding_registration_receipt_reader,
            allowed_browser_origins,
        ),
        rule_binding_scopes_route(
            read_session,
            ReadRuleBindingScopes(rule_binding_scope_reader)
            if rule_binding_scope_reader is not None
            else None,
        ),
        *rule_catalog_routes(
            read_session,
            rule_catalog_reader,
            rule_catalog_refresher,
            allowed_browser_origins,
        ),
        rule_binding_states_route(read_session, rule_binding_state_reader),
        rule_load_observations_route(read_session, rule_load_observation_reader),
        rule_load_observation_history_route(
            read_session, rule_load_observation_history_reader
        ),
        rule_set_snapshot_route(
            read_session,
            ReadRuleSetSnapshot(rule_set_snapshot_reader)
            if rule_set_snapshot_reader is not None
            else None,
        ),
        rule_candidate_diff_route(
            read_session,
            CompareRuleCandidate(rule_set_snapshot_reader)
            if rule_set_snapshot_reader is not None
            else None,
            allowed_browser_origins,
        ),
        rule_candidate_validation_route(
            read_session,
            ValidateRuleCandidate(
                rule_set_snapshot_reader,
                rule_candidate_profile_validator,
                rule_validation_receipt_writer,
            )
            if rule_set_snapshot_reader is not None
            and rule_candidate_profile_validator is not None
            and rule_validation_receipt_writer is not None
            else None,
            allowed_browser_origins,
        ),
        rule_drafts_route(
            read_session,
            ReadRuleDrafts(rule_draft_reader)
            if rule_draft_reader is not None
            else None,
        ),
        rule_draft_route(
            read_session,
            ReadRuleDraft(rule_draft_detail_reader)
            if rule_draft_detail_reader is not None
            else None,
        ),
        *rule_versions_routes(
            read_session,
            ReadRuleVersions(rule_set_version_reader)
            if rule_set_version_reader is not None
            else None,
            ReadRuleVersion(rule_set_version_detail_reader)
            if rule_set_version_detail_reader is not None
            else None,
        ),
        *rule_publication_routes(
            read_session,
            ReadRulePublications(rule_publication_reader)
            if rule_publication_reader is not None
            else None,
            ReadRulePublication(rule_publication_detail_reader)
            if rule_publication_detail_reader is not None
            else None,
            ReadRulePublicationTarget(rule_publication_target_reader)
            if rule_publication_target_reader is not None
            else None,
        ),
        rule_publication_receipts_route(
            read_session,
            ReadRulePublicationReceipts(
                rule_publication_detail_reader,
                rule_publication_receipt_reader,
            )
            if rule_publication_detail_reader is not None
            and rule_publication_receipt_reader is not None
            else None,
        ),
        rule_activation_plans_route(
            read_session,
            ReadRuleActivationPlans(rule_activation_plan_reader)
            if rule_activation_plan_reader is not None
            else None,
        ),
        *rule_mutation_routes(
            read_session,
            rule_mutation_authority,
            allowed_browser_origins,
        ),
        logout_route(
            RevokeCurrentSession(current_session_revoker), allowed_browser_origins
        ),
        *account_directory_routes(
            read_session, ReadAccountDirectory(account_directory_reader)
        ),
    ]
    if account_command_service is not None:
        routes.extend(
            account_command_routes(
                account_command_service,
                read_session,
                allowed_browser_origins,
            )
        )
    if own_password_service is not None:
        routes.append(
            own_password_route(
                own_password_service,
                read_session,
                allowed_browser_origins,
            )
        )
    if login_service is not None:
        if client_identity_hmac_key is None:
            raise ValueError("login requires a deployment-owned client identity key")
        routes.append(
            login_route(
                login_service,
                allowed_browser_origins,
                client_identity_hmac_key,
                client_address_resolver,
            )
        )
    web_directory = dashboard_web_directory or Path(__file__).with_name("web")
    if web_directory.is_dir():
        routes.extend(dashboard_web_routes(web_directory, dashboard_base_path))
    app = Starlette(routes=routes)
    if rule_publication_worker is not None:
        install_rule_publication_worker_lifecycle(
            app,
            rule_publication_worker,
            poll_interval_seconds=publication_worker_poll_interval_seconds,
            batch_size=publication_worker_batch_size,
        )
    if rule_publication_receipt_projection_worker is not None:
        install_rule_publication_receipt_projection_worker_lifecycle(
            app,
            rule_publication_receipt_projection_worker,
            poll_interval_seconds=receipt_projection_worker_poll_interval_seconds,
            batch_size=receipt_projection_worker_batch_size,
        )
    if rule_load_observation_projection_worker is not None:
        install_rule_load_observation_projection_worker_lifecycle(
            app,
            rule_load_observation_projection_worker,
            poll_interval_seconds=(
                rule_load_observation_projection_worker_poll_interval_seconds
            ),
            batch_size=rule_load_observation_projection_worker_batch_size,
        )
    if rule_activation_plan_worker is not None:
        install_rule_activation_plan_worker_lifecycle(
            app,
            rule_activation_plan_worker,
            poll_interval_seconds=activation_plan_worker_poll_interval_seconds,
            batch_size=activation_plan_worker_batch_size,
        )
    return app
