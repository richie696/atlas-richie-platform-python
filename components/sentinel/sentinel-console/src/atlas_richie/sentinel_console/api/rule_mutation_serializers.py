"""Allow-listed serialization for accepted and completed rule commands."""

from __future__ import annotations

from ..application.mutate_rule_set import (
    FrozenRuleVersionResult,
    RuleMutationOperation,
    RuleMutationResult,
    RuleMutationKind,
    RuleOperationStatus,
)
from ..domain.rule_activation_plans import RuleActivationPlan
from ..domain.rule_drafts import StoredRuleDraft
from ..domain.rule_publications import RulePublication
from ..domain.rule_versions import RuleSetVersion
from ..domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from .rule_activation_plan_serializers import rule_activation_plan_body
from .rule_draft_serializers import stored_rule_draft_body
from .rule_publication_serializers import rule_publication_body
from .rule_version_serializers import rule_set_version_body


def rule_mutation_operation_body(
    operation: RuleMutationOperation,
) -> dict[str, object]:
    """Project a durable command receipt without credentials or exception details."""
    body: dict[str, object] = {
        "requestKey": operation.request_key,
        "bindingId": operation.binding_id,
        "status": operation.status.value,
    }
    if operation.status is RuleOperationStatus.REJECTED:
        assert operation.reason is not None
        body["reason"] = operation.reason.value
    elif operation.status is RuleOperationStatus.COMPLETED:
        assert operation.mutation_kind is not None and operation.result is not None
        body["result"] = _result_body(operation.mutation_kind, operation.result)
    return body


def _result_body(
    kind: RuleMutationKind, result: RuleMutationResult
) -> dict[str, object]:
    match kind:
        case RuleMutationKind.SAVE_DRAFT if isinstance(result, StoredRuleDraft):
            return {"kind": kind.value, "draft": stored_rule_draft_body(result)}
        case RuleMutationKind.DELETE_DRAFT if isinstance(result, str):
            return {"kind": kind.value, "draftId": result}
        case RuleMutationKind.FREEZE_VERSION if isinstance(
            result, FrozenRuleVersionResult
        ):
            return {
                "kind": kind.value,
                "draftId": result.draft_id,
                "draftRevision": result.draft_revision,
                "version": rule_set_version_body(result.version),
            }
        case RuleMutationKind.PUBLISH if isinstance(result, RulePublication):
            return {"kind": kind.value, "publication": rule_publication_body(result)}
        case (
            RuleMutationKind.CREATE_PLAN | RuleMutationKind.CANCEL_PLAN
        ) if isinstance(result, RuleActivationPlan):
            return {"kind": kind.value, "plan": rule_activation_plan_body(result)}
        case RuleMutationKind.CONFIGURE_TARGET if isinstance(
            result, VersionedRulePublicationTarget
        ):
            return {"kind": kind.value, **_publication_target_body(result)}
        case _:
            raise ValueError("rule operation result does not match its command kind")


def _publication_target_body(
    result: VersionedRulePublicationTarget,
) -> dict[str, object]:
    """Expose only the exact credential-free destination and its revisions."""
    target = result.target
    if isinstance(target, NacosRulePublicationTarget):
        target_body: dict[str, object] = {
            "provider": "nacos",
            "sourceId": target.source_id,
            "namespace": target.namespace,
            "group": target.group,
            "dataId": target.data_id,
        }
    elif isinstance(target, ConsulRulePublicationTarget):
        target_body = {
            "provider": "consul",
            "sourceId": target.source_id,
            "key": target.key,
            "datacenter": target.datacenter,
        }
    else:
        raise ValueError("rule publication target provider is unsupported")
    return {
        "bindingId": target.binding_id,
        "targetRevision": result.revision,
        "sourceRevision": result.source_revision,
        "target": target_body,
    }
