"""Compose the isolated Metrics V2 Collector ASGI application."""

from __future__ import annotations

import ssl
from functools import partial

from starlette.applications import Starlette

from ...api.incident_ingest import incident_ingest_route
from ...api.metrics_ingest import metrics_ingest_route
from ...api.protocol_negotiation_ingest import (
    agent_reporting_negotiation_route,
    incident_event_negotiation_route,
    rule_load_observation_negotiation_route,
)
from ...api.rule_load_observation_ingest import (
    rule_load_observation_ingest_route,
)
from ...api.rule_publication_receipt_ingest import (
    rule_publication_receipt_ingest_route,
)
from ...application.ingest_incident_event import IngestIncidentEvent
from ...application.ingest_metrics import IngestMetrics
from ...application.ingest_rule_load_observation import (
    IngestRuleLoadObservation,
)
from ...application.ingest_rule_publication_receipt import (
    IngestRulePublicationReceipt,
)
from ...application.negotiate_agent_reporting import NegotiateAgentReporting
from ...application.negotiate_incident_events import NegotiateIncidentEvents
from ...application.negotiate_rule_load_observation import (
    NegotiateRuleLoadObservation,
)
from .database_engine_adapters import DatabaseEngineAdapterRegistry
from .database_runtime import create_database_engine_from_locator
from .incident_event_adapter import SQLAlchemyIncidentEventAdapter
from .metrics_history_store import SQLAlchemyMetricsHistoryAdapter
from .protocol_negotiation_store import SQLAlchemyProtocolNegotiationStore
from .rule_load_observation_inbox import SQLAlchemyRuleLoadObservationInbox
from .rule_publication_receipt_inbox import SQLAlchemyRulePublicationReceiptInbox
from .runtime_database_engine_provider import RuntimeDatabaseEngineProvider
from .runtime_database_lifecycle import install_runtime_database_lifecycle
from .runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)


def build_metrics_collector_app(
    runtime_locator_configuration: RuntimeDatabaseLocatorConfiguration,
    *,
    postgresql_root_certificate: str | None = None,
    mysql_ssl_context: ssl.SSLContext | None = None,
    adapter_registry: DatabaseEngineAdapterRegistry | None = None,
) -> Starlette:
    """Build only the mTLS ingest surface against the selected Console database.

    The Collector intentionally does not mount browser, bootstrap, identity,
    rule-management, or history-query routes. The certificate enrolled by the
    existing durable Reporter directory is the sole ingest principal; the
    returned receipt remains commit-gated by the SQL Adapter.
    """
    if not isinstance(
        runtime_locator_configuration, RuntimeDatabaseLocatorConfiguration
    ):
        raise TypeError("runtime database locator configuration is required")

    runtime_database_engine_factory = partial(
        create_database_engine_from_locator,
        postgresql_root_certificate=postgresql_root_certificate,
        mysql_ssl_context=mysql_ssl_context,
        adapter_registry=adapter_registry,
    )
    runtime_provider = RuntimeDatabaseEngineProvider(
        runtime_locator_configuration.create_store(),
        engine_factory=runtime_database_engine_factory,
    )
    history = SQLAlchemyMetricsHistoryAdapter(runtime_provider.require_engine)
    ingest = IngestMetrics(history, history)
    incidents = SQLAlchemyIncidentEventAdapter(runtime_provider.require_engine)
    incident_ingest = IngestIncidentEvent(incidents, incidents)
    negotiations = SQLAlchemyProtocolNegotiationStore(runtime_provider.require_engine)
    protocol_negotiation = NegotiateAgentReporting(negotiations)
    incident_event_negotiation = NegotiateIncidentEvents(negotiations)
    rule_load_observation_negotiation = NegotiateRuleLoadObservation(negotiations)
    receipt_inbox = SQLAlchemyRulePublicationReceiptInbox(
        runtime_provider.require_engine
    )
    receipt_ingest = IngestRulePublicationReceipt(receipt_inbox)
    rule_load_inbox = SQLAlchemyRuleLoadObservationInbox(
        runtime_provider.require_engine
    )
    rule_load_ingest = IngestRuleLoadObservation(rule_load_inbox)
    app = Starlette(
        routes=[
            metrics_ingest_route(ingest),
            incident_ingest_route(incident_ingest),
            agent_reporting_negotiation_route(protocol_negotiation),
            incident_event_negotiation_route(incident_event_negotiation),
            rule_load_observation_negotiation_route(rule_load_observation_negotiation),
            rule_publication_receipt_ingest_route(receipt_ingest),
            rule_load_observation_ingest_route(rule_load_ingest),
        ]
    )
    install_runtime_database_lifecycle(app, runtime_provider)
    return app


__all__ = ["build_metrics_collector_app"]
