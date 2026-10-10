"""Wire projection for binding-scoped rule publication phases."""

from __future__ import annotations

from ..domain.rule_publications import (
    PublicationPhase,
    RulePublication,
    RulePublicationCollection,
    RulePublicationReceiptPage,
)
from ..domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from .system_observation_access import utc_timestamp


def rule_publication_collection_body(
    collection: RulePublicationCollection,
) -> dict[str, object]:
    """Serialize the complete publication collection and its sample time."""
    return {
        "bindingId": collection.binding_id,
        "asOf": utc_timestamp(collection.as_of),
        "items": [rule_publication_body(item) for item in collection.items],
    }


def rule_publication_body(publication: RulePublication) -> dict[str, object]:
    """Serialize one publication attempt without rule contents or credentials."""
    return {
        "id": publication.id,
        "bindingId": publication.binding_id,
        "targetVersionId": publication.target_version_id,
        "targetChecksum": publication.target_checksum,
        "baseVersionId": publication.base_version_id,
        "createdAt": utc_timestamp(publication.created_at),
        "validation": _phase_body(publication.validation),
        "configurationWrite": _phase_body(publication.configuration_write),
        "readBack": _phase_body(publication.read_back),
    }


def rule_publication_target_body(
    binding_id: str,
    versioned: VersionedRulePublicationTarget | None,
) -> dict[str, object]:
    """Serialize exact target metadata without source credentials or rule content."""
    if versioned is None:
        return {"bindingId": binding_id, "target": None}
    target = versioned.target
    if isinstance(target, NacosRulePublicationTarget):
        value: dict[str, object] = {
            "provider": "nacos",
            "sourceId": target.source_id,
            "namespace": target.namespace,
            "group": target.group,
            "dataId": target.data_id,
        }
    elif isinstance(target, ConsulRulePublicationTarget):
        value = {
            "provider": "consul",
            "sourceId": target.source_id,
            "key": target.key,
            "datacenter": target.datacenter,
        }
    else:
        raise ValueError("unsupported publication target")
    return {
        "bindingId": binding_id,
        "targetRevision": versioned.revision,
        "sourceRevision": versioned.source_revision,
        "target": value,
    }


def _phase_body(phase: PublicationPhase) -> dict[str, object]:
    return {
        "state": phase.state.value,
        "observedAt": (
            utc_timestamp(phase.observed_at) if phase.observed_at is not None else None
        ),
        "reason": phase.reason.value if phase.reason is not None else None,
    }


def rule_publication_receipt_page_body(
    page: RulePublicationReceiptPage,
) -> dict[str, object]:
    """Serialize aggregate coverage separately from the returned page rows."""
    return {
        "publicationId": page.publication_id,
        "bindingId": page.binding_id,
        "page": page.page,
        "pageSize": page.page_size,
        "asOf": utc_timestamp(page.as_of),
        "total": page.total,
        "expected": page.expected,
        "inventorySource": page.inventory_source,
        "applied": page.applied,
        "pending": page.pending,
        "failed": page.failed,
        "unknown": page.unknown,
        "restartRequired": page.restart_required,
        "items": [
            {
                "instanceId": item.instance_id,
                "processEpoch": item.process_epoch,
                "loadedProcessEpoch": item.loaded_process_epoch,
                "targetVersionId": item.target_version_id,
                "loadedVersionId": item.loaded_version_id,
                "loadedChecksum": item.loaded_checksum,
                "appliedAt": (
                    utc_timestamp(item.applied_at)
                    if item.applied_at is not None
                    else None
                ),
                "lastReportAt": (
                    utc_timestamp(item.last_report_at)
                    if item.last_report_at is not None
                    else None
                ),
                "state": item.state.value,
            }
            for item in page.items
        ],
    }
