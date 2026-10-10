"""Compose the first-run SQL Console from explicit deployment-owned inputs."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import timedelta
import os
from pathlib import Path
import re
import ssl
from collections.abc import Mapping, Sequence

from starlette.applications import Starlette

from ...api.browser_origin import normalize_browser_origin
from ...api.client_address import ClientAddressResolver
from ...application.bootstrap_database_check import BootstrapDatabaseKind
from ...application.bootstrap_source_check import BootstrapSourceChecker
from ...application.check_registered_source import RegisteredSourceChecker
from ...application.source_credential_references import (
    SourceCredentialReferenceResolver,
)
from ...application.mutate_rule_set import (
    RuleMutationAuthority,
    RuleMutationBindingReader,
)
from ...application.system_protocols_ports import SystemProtocolsReader
from ...application.system_connections_ports import SystemConnectionsReader
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
from ..bootstrap_database_engine import BootstrapDatabaseEngineFactory
from ..bootstrap_database_connector import BootstrapDatabaseConnector
from ..bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRule,
)
from ..bootstrap_registered_source_checker import (
    RegisteredCheckerBootstrapAdapter,
)
from ..registered_source_checker_composition import (
    compose_provider_registered_source_checker,
)
from ...domain.configuration_source import ConfigurationSourceProvider
from ..security.account_command_keys import AccountCommandKeyConfiguration
from ..security.client_identity_key import ClientIdentityKeyConfiguration
from ..security.registered_source_keys import RegisteredSourceKeyConfiguration
from ..security.rule_command_keys import RuleCommandKeyConfiguration
from .bootstrap_authorization_file_authority import (
    BootstrapAuthorizationConfiguration,
)
from .bootstrap_initialization_coordinator import (
    SqlAlchemyBootstrapInitializationCoordinator,
)
from .bootstrap_initialization_lock import LocalBootstrapInitializationLock
from .identity_composition import build_sql_identity_app
from .login_attempt_configuration import LoginAttemptLimitConfiguration
from .runtime_database_engine_provider import RuntimeDatabaseEngineProvider
from .runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)
from .setup_window_configuration import SetupWindowConfiguration
from .rule_binding_directory_reader import SqlAlchemyRuleBindingDirectoryReader
from .registered_source_composition import compose_registered_source_store
from .rule_publication_worker_composition import (
    create_consul_rule_publication_worker,
    create_nacos_rule_publication_worker,
)
from ..registered_source_checker import RegisteredSourceTargetPolicy

_INITIALIZATION_LOCK_PATH_ENV = "SENTINEL_CONSOLE_BOOTSTRAP_INITIALIZATION_LOCK_PATH"
_BOOTSTRAP_IDEMPOTENCY_KEY_ENV = "SENTINEL_CONSOLE_BOOTSTRAP_IDEMPOTENCY_KEY"
_DATABASE_TARGETS_ENV = "SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS"
_SOURCE_TARGETS_ENV = "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS"
_BROWSER_ORIGINS_ENV = "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS"
_TRUSTED_PROXY_CIDRS_ENV = "SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS"
_SESSION_TTL_ENV = "SENTINEL_CONSOLE_SESSION_TTL_SECONDS"
_DASHBOARD_BASE_PATH_ENV = "SENTINEL_CONSOLE_DASHBOARD_BASE_PATH"
_RULE_PUBLICATION_PROVIDER_ENV = "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDER"
_RULE_PUBLICATION_PROFILE_ENV = "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID"
_POSTGRES_ROOT_CERTIFICATE_ENV = "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
_MYSQL_ROOT_CERTIFICATE_ENV = "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
_SOURCE_ROOT_CERTIFICATE_ENV = "SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE"
_POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class FirstRunSqlIdentityConfiguration:
    """Validated deployment inputs needed to create a first-run ASGI app.

    Network policy, TLS trust, key material, local state paths and browser
    origins are explicit inputs. The composition never invents permissive
    defaults or reads process environment implicitly.
    """

    setup_window: SetupWindowConfiguration
    runtime_locator: RuntimeDatabaseLocatorConfiguration
    bootstrap_authorization: BootstrapAuthorizationConfiguration
    initialization_lock_path: Path
    database_target_policy: BootstrapDatabaseTargetPolicy = field(repr=False)
    bootstrap_idempotency_key: bytes = field(repr=False)
    login_attempt_limit: LoginAttemptLimitConfiguration
    account_command_keys: AccountCommandKeyConfiguration = field(repr=False)
    client_identity_key: ClientIdentityKeyConfiguration = field(repr=False)
    registered_source_keys: RegisteredSourceKeyConfiguration = field(repr=False)
    allowed_browser_origins: frozenset[str]
    client_address_resolver: ClientAddressResolver = field(
        default_factory=ClientAddressResolver, repr=False
    )
    session_ttl: timedelta = timedelta(hours=8)
    postgresql_root_certificate: str | None = None
    mysql_ssl_context: ssl.SSLContext | None = field(default=None, repr=False)
    registered_source_ssl_context: ssl.SSLContext | None = field(
        default=None, repr=False
    )
    registered_source_checker: RegisteredSourceChecker | None = field(
        default=None, repr=False
    )
    registered_source_target_rules: Sequence[RegisteredSourceTargetRule] | None = (
        field(default=None, repr=False)
    )
    bootstrap_source_checker: BootstrapSourceChecker | None = field(
        default=None, repr=False
    )
    source_credential_reference_resolver: (
        SourceCredentialReferenceResolver | None
    ) = field(default=None, repr=False)
    rule_mutation_authority: RuleMutationAuthority | None = field(
        default=None, repr=False
    )
    rule_command_keys: RuleCommandKeyConfiguration | None = field(
        default=None, repr=False
    )
    rule_mutation_binding_reader: RuleMutationBindingReader | None = field(
        default=None, repr=False
    )
    system_protocols_reader: SystemProtocolsReader | None = field(
        default=None, repr=False
    )
    system_connections_reader: SystemConnectionsReader | None = field(
        default=None, repr=False
    )
    system_audit_reader: SystemAuditReader | None = field(default=None, repr=False)
    observation_catalog_reader: ObservationCatalogReader | None = field(
        default=None, repr=False
    )
    instance_catalog_reader: InstanceCatalogReader | None = field(
        default=None, repr=False
    )
    instance_observation_reader: InstanceObservationReader | None = field(
        default=None, repr=False
    )
    metrics_reader: MetricsReader | None = field(default=None, repr=False)
    fleet_overview_reader: FleetOverviewReader | None = field(default=None, repr=False)
    incident_timeline_reader: IncidentTimelineReader | None = field(
        default=None, repr=False
    )
    incident_evidence_reader: IncidentEvidenceReader | None = field(
        default=None, repr=False
    )
    rule_publication_worker: RunRulePublicationWorker | None = field(
        default=None, repr=False
    )
    rule_publication_provider: ConfigurationSourceProvider | None = None
    rule_publication_profile_id: str | None = None
    rule_activation_plan_worker: RunRuleActivationPlanWorker | None = field(
        default=None, repr=False
    )
    dashboard_web_directory: Path | None = None
    dashboard_base_path: str = "/"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.initialization_lock_path, Path)
            or not self.initialization_lock_path.is_absolute()
            or self.initialization_lock_path.name in {"", ".", ".."}
        ):
            raise ValueError("bootstrap initialization lock path must be absolute")
        if (
            not isinstance(self.bootstrap_idempotency_key, bytes)
            or len(self.bootstrap_idempotency_key) < 32
        ):
            raise ValueError("bootstrap idempotency key must be at least 32 bytes")
        if not isinstance(self.allowed_browser_origins, frozenset) or not all(
            isinstance(origin, str) and origin for origin in self.allowed_browser_origins
        ):
            raise ValueError("allowed browser origins must be explicit")
        if not self.allowed_browser_origins:
            raise ValueError("at least one browser origin must be configured")
        if self.session_ttl <= timedelta(0):
            raise ValueError("session lifetime must be positive")
        if (
            self.rule_command_keys is None
            and self.rule_mutation_binding_reader is not None
        ):
            raise ValueError(
                "an authoritative binding reader requires rule-command keys"
            )
        if self.rule_mutation_authority is not None and (
            self.rule_command_keys is not None
            or self.rule_mutation_binding_reader is not None
        ):
            raise ValueError(
                "inject either a rule mutation authority or its SQL composition inputs"
            )
        if (self.rule_publication_provider is None) != (
            self.rule_publication_profile_id is None
        ):
            raise ValueError("rule publication worker settings are incomplete")
        if self.rule_publication_provider is not None:
            if self.rule_publication_worker is not None:
                raise ValueError(
                    "inject either a publication worker or deployment settings"
                )
            if self.rule_command_keys is None:
                raise ValueError(
                    "rule publication requires rule-command fingerprint keys"
                )
            if not isinstance(self.rule_publication_profile_id, str) or not (
                self.rule_publication_profile_id.strip()
            ):
                raise ValueError("rule publication profile identity is invalid")
            if not any(
                rule.provider is self.rule_publication_provider
                for rule in (self.registered_source_target_rules or ())
            ):
                raise ValueError(
                    "rule publication provider has no registered network grant"
                )
        state_paths = (
            self.setup_window.path,
            self.runtime_locator.path,
            self.bootstrap_authorization.state_path,
            self.initialization_lock_path,
        )
        if len({_normalized_state_path(path) for path in state_paths}) != len(
            state_paths
        ):
            raise ValueError("deployment state paths must be distinct")
        normalized_origins = frozenset(
            normalize_browser_origin(origin)
            for origin in self.allowed_browser_origins
        )
        object.__setattr__(self, "allowed_browser_origins", normalized_origins)
        if self.dashboard_web_directory is not None and (
            not isinstance(self.dashboard_web_directory, Path)
            or not self.dashboard_web_directory.is_absolute()
        ):
            raise ValueError("dashboard web directory must be absolute")
        if not isinstance(self.dashboard_base_path, str):
            raise ValueError("dashboard base path is invalid")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        rule_mutation_binding_reader: RuleMutationBindingReader | None = None,
    ) -> FirstRunSqlIdentityConfiguration:
        """Load deployment env and an optional host-owned rule binding reader.

        Rule commands are enabled only when the independent rule key ring is
        configured and its exact-binding authority is explicitly supplied by
        the host. The Console never derives binding facts from request input.
        """
        values = os.environ if environment is None else environment
        try:
            lock_path = Path(values[_INITIALIZATION_LOCK_PATH_ENV])
            encoded_key = values[_BOOTSTRAP_IDEMPOTENCY_KEY_ENV]
            database_targets = _parse_database_targets(
                values[_DATABASE_TARGETS_ENV]
            )
            source_targets = _parse_source_targets(values[_SOURCE_TARGETS_ENV])
            origins = frozenset(
                origin.strip()
                for origin in values[_BROWSER_ORIGINS_ENV].split(",")
                if origin.strip()
            )
        except (KeyError, AttributeError, TypeError, ValueError):
            raise ValueError(
                "first-run Console deployment configuration is incomplete or invalid"
            ) from None

        try:
            idempotency_key = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, TypeError, ValueError):
            raise ValueError(
                "first-run Console deployment configuration is incomplete or invalid"
            ) from None
        if len(idempotency_key) < 32:
            raise ValueError(
                "first-run Console deployment configuration is invalid"
            )
        try:
            session_ttl = timedelta(
                seconds=_positive_integer(values, _SESSION_TTL_ENV, default=28_800)
            )
            postgres_root_certificate = _absolute_optional_path(
                values, _POSTGRES_ROOT_CERTIFICATE_ENV
            )
            mysql_root_certificate = _absolute_optional_path(
                values, _MYSQL_ROOT_CERTIFICATE_ENV
            )
            source_root_certificate = _absolute_optional_path(
                values, _SOURCE_ROOT_CERTIFICATE_ENV
            )
            mysql_ssl_context = ssl.create_default_context(
                cafile=(
                    str(mysql_root_certificate)
                    if mysql_root_certificate is not None
                    else None
                )
            )
            registered_source_ssl_context = (
                ssl.create_default_context(cafile=str(source_root_certificate))
                if source_root_certificate is not None
                else None
            )
            rule_command_keys = (
                RuleCommandKeyConfiguration.from_optional_environment(values)
            )
            publication_provider_value = values.get(
                _RULE_PUBLICATION_PROVIDER_ENV
            )
            publication_profile_id = values.get(_RULE_PUBLICATION_PROFILE_ENV)
            publication_provider = (
                ConfigurationSourceProvider(publication_provider_value)
                if publication_provider_value is not None
                else None
            )
            if publication_provider is None and publication_profile_id is not None:
                raise ValueError("rule publication profile has no provider")
            if publication_provider is not None and rule_command_keys is None:
                raise ValueError("rule publication requires command fingerprint keys")
            if rule_command_keys is None and rule_mutation_binding_reader is not None:
                raise ValueError(
                    "an exact binding reader requires a rule-command key ring"
                )
            return cls(
                setup_window=SetupWindowConfiguration.from_environment(values),
                runtime_locator=RuntimeDatabaseLocatorConfiguration.from_environment(
                    values
                ),
                bootstrap_authorization=(
                    BootstrapAuthorizationConfiguration.from_environment(values)
                ),
                initialization_lock_path=lock_path,
                database_target_policy=BootstrapDatabaseTargetPolicy(
                    database_targets
                ),
                bootstrap_idempotency_key=idempotency_key,
                login_attempt_limit=LoginAttemptLimitConfiguration.from_environment(
                    values
                ),
                account_command_keys=AccountCommandKeyConfiguration.from_environment(
                    values
                ),
                client_identity_key=ClientIdentityKeyConfiguration.from_environment(
                    values
                ),
                registered_source_keys=(
                    RegisteredSourceKeyConfiguration.from_environment(values)
                ),
                allowed_browser_origins=origins,
                client_address_resolver=ClientAddressResolver.from_cidrs(
                    _optional_csv(values, _TRUSTED_PROXY_CIDRS_ENV)
                ),
                session_ttl=session_ttl,
                postgresql_root_certificate=(
                    str(postgres_root_certificate)
                    if postgres_root_certificate is not None
                    else None
                ),
                mysql_ssl_context=mysql_ssl_context,
                registered_source_ssl_context=registered_source_ssl_context,
                registered_source_target_rules=source_targets,
                rule_command_keys=rule_command_keys,
                rule_mutation_binding_reader=rule_mutation_binding_reader,
                rule_publication_provider=publication_provider,
                rule_publication_profile_id=publication_profile_id,
                dashboard_base_path=values.get(_DASHBOARD_BASE_PATH_ENV, "/"),
            )
        except (OSError, TypeError, ValueError):
            raise ValueError(
                "first-run Console deployment configuration is incomplete or invalid"
            ) from None


def build_first_run_sql_identity_app(
    configuration: FirstRunSqlIdentityConfiguration,
) -> Starlette:
    """Build setup and initialized modes with one shared authority graph.

    This function wires the deployment-owned file authorities, cross-store
    initialization coordinator, lazy runtime engine, SQL identity adapters and
    ASGI lifespan. It does not create/open the setup window, connect until a
    request or startup requires SQL, or claim support for non-local shared-file
    locking.
    """
    if not isinstance(configuration, FirstRunSqlIdentityConfiguration):
        raise TypeError("first-run Console configuration is required")

    setup_window = configuration.setup_window.create_store()
    runtime_locator = configuration.runtime_locator.create_store()
    initialization_lock = LocalBootstrapInitializationLock(
        configuration.initialization_lock_path
    )
    bootstrap_authority = configuration.bootstrap_authorization.create_authority(
        setup_window
    )
    database_engine_factory = BootstrapDatabaseEngineFactory(
        configuration.database_target_policy,
        postgresql_root_certificate=configuration.postgresql_root_certificate,
        mysql_ssl_context=configuration.mysql_ssl_context,
    )
    registered_source_checker = configuration.registered_source_checker
    if registered_source_checker is not None and (
        configuration.registered_source_target_rules is not None
    ):
        raise ValueError("inject either a source checker or deployment target rules")
    if configuration.registered_source_target_rules is not None:
        registered_source_checker = compose_provider_registered_source_checker(
            configuration.registered_source_target_rules,
            ssl_context=configuration.registered_source_ssl_context,
        )
    bootstrap_source_checker = configuration.bootstrap_source_checker
    if bootstrap_source_checker is None and registered_source_checker is not None:
        bootstrap_source_checker = RegisteredCheckerBootstrapAdapter(
            registered_source_checker
        )
    coordinator = SqlAlchemyBootstrapInitializationCoordinator(
        database_engine_factory=database_engine_factory,
        runtime_database_locator_store=runtime_locator,
        setup_window_reader=setup_window,
        setup_window_controller=setup_window,
        operator_verifier=bootstrap_authority,
        initialization_lock=initialization_lock,
        source_secret_cipher=configuration.registered_source_keys.create_secret_cipher(),
        idempotency_key=configuration.bootstrap_idempotency_key,
    )
    runtime_provider = RuntimeDatabaseEngineProvider(runtime_locator)
    from .runtime_database_engine_provider import RuntimeDatabaseEngineBridge

    runtime_engine = RuntimeDatabaseEngineBridge(runtime_provider)
    rule_mutation_binding_reader = configuration.rule_mutation_binding_reader
    if configuration.rule_command_keys is not None and rule_mutation_binding_reader is None:
        # The standard deployment owns binding metadata in this same SQL authority.
        rule_mutation_binding_reader = SqlAlchemyRuleBindingDirectoryReader(
            runtime_engine  # type: ignore[arg-type]
        )

    rule_publication_worker = configuration.rule_publication_worker
    if configuration.rule_publication_provider is not None:
        provider = configuration.rule_publication_provider
        source_store = compose_registered_source_store(
            runtime_engine,  # type: ignore[arg-type]
            configuration.registered_source_keys,
        )
        target_policy = RegisteredSourceTargetPolicy(
            tuple(
                rule
                for rule in (configuration.registered_source_target_rules or ())
                if rule.provider is provider
            )
        )
        worker_factory = (
            create_consul_rule_publication_worker
            if provider is ConfigurationSourceProvider.CONSUL
            else create_nacos_rule_publication_worker
        )
        rule_publication_worker = worker_factory(
            runtime_engine,
            target_policy=target_policy,
            credential_resolver=source_store,
            credential_reference_resolver=(
                configuration.source_credential_reference_resolver
            ),
            profile_id=configuration.rule_publication_profile_id or "",
            ssl_context=configuration.registered_source_ssl_context,
        )

    app = build_sql_identity_app(
        runtime_engine,  # type: ignore[arg-type]
        attempt_limit=configuration.login_attempt_limit,
        account_command_keys=configuration.account_command_keys,
        client_identity_key=configuration.client_identity_key,
        session_ttl=configuration.session_ttl,
        setup_window_reader=setup_window,
        bootstrap_operator_verifier=bootstrap_authority,
        bootstrap_authorization_authority=bootstrap_authority,
        allowed_browser_origins=configuration.allowed_browser_origins,
        client_address_resolver=configuration.client_address_resolver,
        bootstrap_initialization_reader=coordinator,
        bootstrap_initializer=coordinator,
        bootstrap_initialization_operation_reader=coordinator,
        bootstrap_database_checker=BootstrapDatabaseConnector(
            configuration.database_target_policy,
            postgresql_root_certificate=configuration.postgresql_root_certificate,
            mysql_ssl_context=configuration.mysql_ssl_context,
        ),
        runtime_database_provider=runtime_provider,
        registered_source_keys=configuration.registered_source_keys,
        bootstrap_source_checker=bootstrap_source_checker,
        source_credential_reference_resolver=(
            configuration.source_credential_reference_resolver
        ),
        registered_source_checker=registered_source_checker,
        rule_mutation_authority=configuration.rule_mutation_authority,
        rule_command_keys=configuration.rule_command_keys,
        rule_mutation_binding_reader=rule_mutation_binding_reader,
        system_protocols_reader=configuration.system_protocols_reader,
        system_connections_reader=configuration.system_connections_reader,
        system_audit_reader=configuration.system_audit_reader,
        observation_catalog_reader=configuration.observation_catalog_reader,
        instance_catalog_reader=configuration.instance_catalog_reader,
        instance_observation_reader=configuration.instance_observation_reader,
        metrics_reader=configuration.metrics_reader,
        fleet_overview_reader=configuration.fleet_overview_reader,
        incident_timeline_reader=configuration.incident_timeline_reader,
        incident_evidence_reader=configuration.incident_evidence_reader,
        rule_publication_worker=rule_publication_worker,
        rule_activation_plan_worker=configuration.rule_activation_plan_worker,
        dashboard_web_directory=configuration.dashboard_web_directory,
        dashboard_base_path=configuration.dashboard_base_path,
    )
    return app


__all__ = [
    "FirstRunSqlIdentityConfiguration",
    "build_first_run_sql_identity_app",
]


def _parse_database_targets(value: str) -> tuple[BootstrapDatabaseTargetRule, ...]:
    """Parse ``kind|cidr|port;...`` without accepting wildcard grants."""
    if not isinstance(value, str) or not value:
        raise ValueError("database target policy is required")
    rules: list[BootstrapDatabaseTargetRule] = []
    for entry in value.split(";"):
        parts = entry.split("|")
        if len(parts) != 3:
            raise ValueError("database target policy is invalid")
        kind = BootstrapDatabaseKind(parts[0])
        if kind is BootstrapDatabaseKind.SQLITE:
            raise ValueError("SQLite is not a production bootstrap target")
        port = _parse_port(parts[2])
        rules.append(
            BootstrapDatabaseTargetRule.create(kind, parts[1], frozenset({port}))
        )
    if not rules:
        raise ValueError("database target policy is required")
    return tuple(rules)


def _parse_source_targets(value: str) -> tuple[RegisteredSourceTargetRule, ...]:
    """Parse ``provider|hostname|cidr,cidr|port,port;...`` grants."""
    if not isinstance(value, str) or not value:
        raise ValueError("registered-source target policy is required")
    rules: list[RegisteredSourceTargetRule] = []
    for entry in value.split(";"):
        parts = entry.split("|")
        if len(parts) != 4:
            raise ValueError("registered-source target policy is invalid")
        provider = ConfigurationSourceProvider(parts[0])
        networks = tuple(parts[2].split(","))
        ports = frozenset(_parse_port(port) for port in parts[3].split(","))
        rules.append(
            RegisteredSourceTargetRule.create(
                provider, parts[1], networks, ports
            )
        )
    if not rules:
        raise ValueError("registered-source target policy is required")
    return tuple(rules)


def _parse_port(value: str) -> int:
    if not isinstance(value, str) or _POSITIVE_INTEGER.fullmatch(value) is None:
        raise ValueError("target port is invalid")
    port = int(value)
    if port > 65_535:
        raise ValueError("target port is invalid")
    return port


def _optional_csv(values: Mapping[str, str], key: str) -> tuple[str, ...]:
    value = values.get(key, "")
    if not isinstance(value, str):
        raise ValueError("trusted proxy policy is invalid")
    return tuple(entry.strip() for entry in value.split(",") if entry.strip())


def _absolute_optional_path(
    values: Mapping[str, str], key: str
) -> Path | None:
    value = values.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("certificate path is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("certificate path must be absolute")
    return path


def _positive_integer(
    values: Mapping[str, str], key: str, *, default: int | None = None
) -> int:
    value = values.get(key)
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or _POSITIVE_INTEGER.fullmatch(value) is None:
        raise ValueError("positive integer deployment setting is invalid")
    if len(value) > 10 or int(value) > 2_147_483_647:
        raise ValueError("positive integer deployment setting is invalid")
    return int(value)


def _normalized_state_path(path: Path) -> Path:
    """Compare configured local state paths without requiring them to exist."""
    return path.resolve(strict=False)
