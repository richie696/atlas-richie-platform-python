"""Allow-listed wire serialization for activation plan snapshots."""

from __future__ import annotations

from ..domain.rule_activation_plans import RuleActivationPlan, RuleActivationPlanCollection
from .system_observation_access import utc_timestamp


def rule_activation_plan_collection_body(
    collection: RuleActivationPlanCollection,
) -> dict[str, object]:
    """Serialize all persisted schedule facts without inferred active state."""
    return {
        "bindingId": collection.binding_id,
        "asOf": utc_timestamp(collection.as_of),
        "items": [rule_activation_plan_body(item) for item in collection.items],
    }


def rule_activation_plan_body(plan: RuleActivationPlan) -> dict[str, object]:
    """Serialize one persisted plan with UTC instants and no inferred state."""
    return {
        "id": plan.id,
        "revision": plan.revision,
        "bindingId": plan.binding_id,
        "versionId": plan.version_id,
        "restoreVersionId": plan.restore_version_id,
        "activateAt": utc_timestamp(plan.activate_at),
        "deactivateAt": utc_timestamp(plan.deactivate_at),
        "timeZone": plan.time_zone,
        "state": plan.state.value,
        "activationPublicationId": plan.activation_publication_id,
        "restorePublicationId": plan.restore_publication_id,
    }
