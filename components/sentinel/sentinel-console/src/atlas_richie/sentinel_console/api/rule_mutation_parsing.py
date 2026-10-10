"""Strict HTTP parsing for the six typed rule-workflow mutations."""

from __future__ import annotations

from datetime import datetime
import re

from ..application.mutate_rule_set import (
    CancelRuleActivationPlan,
    ConfigureRulePublicationTarget,
    CreateRuleActivationPlan,
    DeleteRuleDraft,
    FreezeRuleVersion,
    PublishRuleVersion,
    RuleMutation,
    RuleMutationCommand,
    RuleMutationKind,
    SaveRuleDraft,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
)
from ..domain.utc_time import is_wire_utc_millisecond_instant
from ..domain.wire_strings import has_non_blank_wire_content, is_bounded_wire_text
from .rule_candidate_parsing import InvalidCandidateShape, parse_rule_candidate

_REQUEST_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_UTC_MILLISECOND = re.compile(
    r"^(?:19[7-9]\d|[2-9]\d{3})-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


class InvalidRuleMutation(ValueError):
    """The request does not match exactly one rule command contract."""


def parse_rule_mutation(
    binding_id: str, body: dict[str, object] | None
) -> RuleMutationCommand:
    """Parse a strict command body and bind it to the route's exact ruleset."""
    if not is_rule_binding_identifier(binding_id):
        raise InvalidRuleMutation("rule binding identity is invalid")
    data = _object(body, {"requestKey", "mutation"})
    request_key = _text(data["requestKey"], 128)
    if _REQUEST_KEY.fullmatch(request_key) is None:
        raise InvalidRuleMutation("rule request key is invalid")
    mutation = _parse_payload(data["mutation"], binding_id)
    return RuleMutationCommand(binding_id, request_key, mutation)


def _parse_payload(value: object, binding_id: str) -> RuleMutation:
    if not isinstance(value, dict):
        raise InvalidRuleMutation("rule mutation must be an object")
    kind = value.get("kind")
    try:
        command_kind = RuleMutationKind(kind)
    except (TypeError, ValueError) as error:
        raise InvalidRuleMutation("rule mutation kind is unsupported") from error

    match command_kind:
        case RuleMutationKind.SAVE_DRAFT:
            data = _object(
                value,
                {"kind", "draftId", "expectedRevision", "candidate"},
            )
            draft_id = _nullable_identifier(data["draftId"])
            revision = _nullable_identifier(data["expectedRevision"])
            if (draft_id is None) != (revision is None):
                raise InvalidRuleMutation(
                    "draft identity and revision must appear together"
                )
            candidate_value = data["candidate"]
            if not isinstance(candidate_value, dict):
                raise InvalidRuleMutation("rule draft candidate is invalid")
            try:
                candidate = parse_rule_candidate(candidate_value)
            except (InvalidCandidateShape, TypeError, ValueError) as error:
                raise InvalidRuleMutation("rule draft candidate is invalid") from error
            if candidate.binding_id != binding_id:
                raise InvalidRuleMutation("candidate does not match the route binding")
            return SaveRuleDraft(draft_id, revision, candidate)
        case RuleMutationKind.DELETE_DRAFT:
            data = _object(value, {"kind", "draftId", "expectedRevision"})
            return DeleteRuleDraft(
                _identifier(data["draftId"]),
                _identifier(data["expectedRevision"]),
            )
        case RuleMutationKind.FREEZE_VERSION:
            data = _object(
                value,
                {
                    "kind",
                    "draftId",
                    "expectedRevision",
                    "validationId",
                    "candidateChecksum",
                    "name",
                    "note",
                },
            )
            name = _text(data["name"], 200)
            note = _text(data["note"], 2_000)
            if not has_non_blank_wire_content(name):
                raise InvalidRuleMutation("version name is required")
            return FreezeRuleVersion(
                _identifier(data["draftId"]),
                _identifier(data["expectedRevision"]),
                _identifier(data["validationId"]),
                _identifier(data["candidateChecksum"]),
                name,
                note,
            )
        case RuleMutationKind.PUBLISH:
            data = _object(
                value,
                {
                    "kind",
                    "versionId",
                    "versionChecksum",
                    "expectedVersionId",
                    "expectedChecksum",
                    "expectedSourceRevision",
                    "reason",
                },
            )
            reason = _text(data["reason"], 2_000)
            if not has_non_blank_wire_content(reason):
                raise InvalidRuleMutation("publication reason is required")
            return PublishRuleVersion(
                _identifier(data["versionId"]),
                _identifier(data["versionChecksum"]),
                _nullable_identifier(data["expectedVersionId"]),
                _identifier(data["expectedChecksum"]),
                _nullable_identifier(data["expectedSourceRevision"]),
                reason,
            )
        case RuleMutationKind.CREATE_PLAN:
            data = _object(value, {"kind", "schedule"})
            schedule = _object(
                data["schedule"],
                {
                    "bindingId",
                    "versionId",
                    "restoreVersionId",
                    "activateAt",
                    "deactivateAt",
                    "timeZone",
                },
            )
            if _identifier(schedule["bindingId"]) != binding_id:
                raise InvalidRuleMutation("schedule does not match the route binding")
            time_zone = _text(schedule["timeZone"], 128)
            if not has_non_blank_wire_content(time_zone):
                raise InvalidRuleMutation("schedule time zone is required")
            return CreateRuleActivationPlan(
                _identifier(schedule["versionId"]),
                _identifier(schedule["restoreVersionId"]),
                _instant(schedule["activateAt"]),
                _instant(schedule["deactivateAt"]),
                time_zone,
            )
        case RuleMutationKind.CANCEL_PLAN:
            data = _object(value, {"kind", "planId", "expectedRevision", "reason"})
            reason = _text(data["reason"], 2_000)
            if not has_non_blank_wire_content(reason):
                raise InvalidRuleMutation("cancellation reason is required")
            return CancelRuleActivationPlan(
                _identifier(data["planId"]),
                _identifier(data["expectedRevision"]),
                reason,
            )
        case RuleMutationKind.CONFIGURE_TARGET:
            data = _object(
                value,
                {
                    "kind",
                    "expectedSourceRevision",
                    "expectedTargetRevision",
                    "target",
                },
            )
            source_revision = _identifier(data["expectedSourceRevision"])
            target_revision = _nullable_identifier(data["expectedTargetRevision"])
            target_value = data["target"]
            if not isinstance(target_value, dict):
                raise InvalidRuleMutation("publication target is invalid")
            provider = target_value.get("provider")
            if provider == "nacos":
                target_data = _object(
                    target_value,
                    {"provider", "sourceId", "namespace", "group", "dataId"},
                )
                target = NacosRulePublicationTarget(
                    binding_id=binding_id,
                    source_id=_identifier(target_data["sourceId"]),
                    namespace=_text(target_data["namespace"], 512),
                    group=_text(target_data["group"], 512),
                    data_id=_text(target_data["dataId"], 512),
                )
            elif provider == "consul":
                target_data = _object(
                    target_value,
                    {"provider", "sourceId", "key"},
                )
                target = ConsulRulePublicationTarget(
                    binding_id=binding_id,
                    source_id=_identifier(target_data["sourceId"]),
                    key=_text(target_data["key"], 512),
                )
            else:
                raise InvalidRuleMutation("publication target provider is unsupported")
            return ConfigureRulePublicationTarget(
                expected_source_revision=source_revision,
                expected_target_revision=target_revision,
                target=target,
            )
    raise InvalidRuleMutation("rule mutation is unsupported")


def _object(value: object, required: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != required:
        raise InvalidRuleMutation("rule command fields do not match the contract")
    if any(not isinstance(key, str) for key in value):
        raise InvalidRuleMutation("rule command field names are invalid")
    return value


def _text(value: object, maximum: int) -> str:
    if not is_bounded_wire_text(value, maximum):
        raise InvalidRuleMutation("rule command text field is invalid")
    return value


def _identifier(value: object) -> str:
    text = _text(value, 200)
    if not is_rule_binding_identifier(text):
        raise InvalidRuleMutation("rule command identity is invalid")
    return text


def _nullable_identifier(value: object) -> str | None:
    return None if value is None else _identifier(value)


def _instant(value: object) -> datetime:
    text = _text(value, 32)
    if _UTC_MILLISECOND.fullmatch(text) is None:
        raise InvalidRuleMutation("rule schedule instant must be UTC milliseconds")
    try:
        instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidRuleMutation("rule schedule instant is invalid") from error
    if (
        not is_wire_utc_millisecond_instant(instant)
        or instant.utcoffset().total_seconds() != 0
    ):
        raise InvalidRuleMutation("rule schedule instant is invalid")
    return instant
