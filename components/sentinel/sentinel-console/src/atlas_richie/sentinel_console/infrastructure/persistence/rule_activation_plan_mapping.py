"""Strict reconstruction of persisted activation-plan facts."""

from __future__ import annotations

from datetime import UTC

from ...domain.rule_activation_plans import (
    RuleActivationPlan,
    RuleActivationPlanState,
)


def activation_plan_body_from_row(row) -> dict[str, object]:
    """Project one database row into the shared plan wire-shaped mapping."""
    return {
        "id": row["plan_id"],
        "revision": row["revision"],
        "bindingId": row["binding_id"],
        "versionId": row["version_id"],
        "restoreVersionId": row["restore_version_id"],
        "activateAt": _instant(row["activate_at"]),
        "deactivateAt": _instant(row["deactivate_at"]),
        "timeZone": row["time_zone"],
        "state": row["state"],
        "activationPublicationId": row["activation_publication_id"],
        "restorePublicationId": row["restore_publication_id"],
    }


def activation_plan_from_body(body: dict[str, object]) -> RuleActivationPlan:
    """Rebuild one plan through its domain invariants."""
    return RuleActivationPlan(
        id=str(body["id"]),
        revision=str(body["revision"]),
        binding_id=str(body["bindingId"]),
        version_id=str(body["versionId"]),
        restore_version_id=str(body["restoreVersionId"]),
        activate_at=_parse_instant(body["activateAt"]),
        deactivate_at=_parse_instant(body["deactivateAt"]),
        time_zone=str(body["timeZone"]),
        state=RuleActivationPlanState(str(body["state"])),
        activation_publication_id=_optional_string(body["activationPublicationId"]),
        restore_publication_id=_optional_string(body["restorePublicationId"]),
    )


def activation_plan_result_body(plan: RuleActivationPlan) -> dict[str, object]:
    """Encode a JSON-safe, API-independent snapshot for command recovery."""
    return {
        "id": plan.id,
        "revision": plan.revision,
        "bindingId": plan.binding_id,
        "versionId": plan.version_id,
        "restoreVersionId": plan.restore_version_id,
        "activateAt": _instant(plan.activate_at),
        "deactivateAt": _instant(plan.deactivate_at),
        "timeZone": plan.time_zone,
        "state": plan.state.value,
        "activationPublicationId": plan.activation_publication_id,
        "restorePublicationId": plan.restore_publication_id,
    }


def _instant(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat().replace("+00:00", "Z")


def _parse_instant(value: object):
    from datetime import datetime

    if not isinstance(value, str):
        raise ValueError("activation plan timestamp is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("activation publication identity is invalid")
    return value
