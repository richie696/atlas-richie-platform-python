"""Strict wire parsing for every supported ruleset mutation."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.api.rule_mutation_parsing import (
    InvalidRuleMutation,
    parse_rule_mutation,
)
from atlas_richie.sentinel_console.application.mutate_rule_set import (
    CancelRuleActivationPlan,
    ConfigureRulePublicationTarget,
    CreateRuleActivationPlan,
    DeleteRuleDraft,
    FreezeRuleVersion,
    PublishRuleVersion,
    SaveRuleDraft,
)

_BINDING_ID = "binding-1"


def _command(kind: str, **fields: object) -> dict[str, object]:
    return {
        "requestKey": "mutation-request-1",
        "mutation": {"kind": kind, **fields},
    }


class RuleMutationParsingTest(unittest.TestCase):
    def test_publication_target_values_use_512_utf16_wire_units(self) -> None:
        target_text = "🚀" * 256
        body = _command(
            "configure_target",
            expectedSourceRevision="source-revision-1",
            expectedTargetRevision=None,
            target={
                "provider": "nacos",
                "sourceId": "nacos-main",
                "namespace": target_text,
                "group": "DEFAULT_GROUP",
                "dataId": "rules.json",
            },
        )
        command = parse_rule_mutation(_BINDING_ID, body)
        self.assertIsInstance(command.mutation, ConfigureRulePublicationTarget)
        self.assertEqual(command.mutation.target.namespace, target_text)

        oversized = {
            **body,
            "mutation": {
                **body["mutation"],
                "target": {**body["mutation"]["target"], "namespace": "🚀" * 257},
            },
        }
        with self.assertRaises(InvalidRuleMutation):
            parse_rule_mutation(_BINDING_ID, oversized)

    def test_parses_all_six_command_variants(self) -> None:
        candidate = {
            "bindingId": _BINDING_ID,
            "profile": "sentinel-rule-profile-v1",
            "kind": "flow",
            "baseVersionId": None,
            "baseChecksum": "sha256:baseline",
            "sourceRevision": None,
            "rules": [],
        }
        cases = (
            (
                _command(
                    "save_draft",
                    draftId=None,
                    expectedRevision=None,
                    candidate=candidate,
                ),
                SaveRuleDraft,
            ),
            (
                _command(
                    "delete_draft", draftId="draft-1", expectedRevision="rev-1"
                ),
                DeleteRuleDraft,
            ),
            (
                _command(
                    "freeze_version",
                    draftId="draft-1",
                    expectedRevision="rev-1",
                    validationId="validation-1",
                    candidateChecksum="sha256:candidate",
                    name="Routine",
                    note="",
                ),
                FreezeRuleVersion,
            ),
            (
                _command(
                    "publish",
                    versionId="version-1",
                    versionChecksum="sha256:version",
                    expectedVersionId=None,
                    expectedChecksum="sha256:baseline",
                    expectedSourceRevision=None,
                    reason="Approved change",
                ),
                PublishRuleVersion,
            ),
            (
                _command(
                    "create_plan",
                    schedule={
                        "bindingId": _BINDING_ID,
                        "versionId": "version-1",
                        "restoreVersionId": "version-2",
                        "activateAt": "2026-10-10T10:00:00.000Z",
                        "deactivateAt": "2026-10-10T11:00:00.000Z",
                        "timeZone": "Asia/Shanghai",
                    },
                ),
                CreateRuleActivationPlan,
            ),
            (
                _command(
                    "cancel_plan",
                    planId="plan-1",
                    expectedRevision="rev-1",
                    reason="No longer needed",
                ),
                CancelRuleActivationPlan,
            ),
        )

        for body, expected_type in cases:
            with self.subTest(kind=body["mutation"]["kind"]):
                command = parse_rule_mutation(_BINDING_ID, body)
                self.assertEqual(command.request_key, "mutation-request-1")
                self.assertIsInstance(command.mutation, expected_type)

    def test_rejects_cross_runtime_blank_names_and_reasons(self) -> None:
        blank_values = (" ", "\u0085", "\u001c", "\ufeff")
        for blank in blank_values:
            mutations = (
                _command(
                    "freeze_version",
                    draftId="draft-1",
                    expectedRevision="revision-1",
                    validationId="validation-1",
                    candidateChecksum="sha256:candidate",
                    name=blank,
                    note="",
                ),
                _command(
                    "publish",
                    versionId="version-1",
                    versionChecksum="sha256:version",
                    expectedVersionId=None,
                    expectedChecksum="sha256:baseline",
                    expectedSourceRevision=None,
                    reason=blank,
                ),
                _command(
                    "cancel_plan",
                    planId="plan-1",
                    expectedRevision="revision-1",
                    reason=blank,
                ),
                _command(
                    "create_plan",
                    schedule={
                        "bindingId": _BINDING_ID,
                        "versionId": "version-1",
                        "restoreVersionId": "version-2",
                        "activateAt": "2026-10-10T10:00:00.000Z",
                        "deactivateAt": "2026-10-10T11:00:00.000Z",
                        "timeZone": blank,
                    },
                ),
            )
            for body in mutations:
                with self.subTest(blank=repr(blank), kind=body["mutation"]["kind"]):
                    with self.assertRaises(InvalidRuleMutation):
                        parse_rule_mutation(_BINDING_ID, body)

    def test_rejects_unknown_or_extra_fields_and_binding_mismatch(self) -> None:
        valid_candidate = {
            "bindingId": _BINDING_ID,
            "profile": "sentinel-rule-profile-v1",
            "kind": "flow",
            "baseVersionId": None,
            "baseChecksum": "sha256:baseline",
            "sourceRevision": None,
            "rules": [],
        }
        valid_schedule = {
            "bindingId": _BINDING_ID,
            "versionId": "version-1",
            "restoreVersionId": "version-2",
            "activateAt": "2026-10-10T10:00:00.000Z",
            "deactivateAt": "2026-10-10T11:00:00.000Z",
            "timeZone": "Asia/Shanghai",
        }
        cases = (
            _command("unsupported"),
            {
                **_command(
                    "save_draft",
                    draftId=None,
                    expectedRevision=None,
                    candidate=valid_candidate,
                ),
                "extra": True,
            },
            _command(
                "save_draft",
                draftId=None,
                expectedRevision="revision-without-draft",
                candidate=valid_candidate,
            ),
            _command(
                "save_draft",
                draftId=None,
                expectedRevision=None,
                candidate={**valid_candidate, "bindingId": "another-binding"},
            ),
            _command(
                "create_plan",
                schedule={**valid_schedule, "activateAt": "2026-10-10T10:00:00Z"},
            ),
            _command(
                "create_plan",
                schedule={
                    **valid_schedule,
                    "activateAt": "2026-10-10T10:00:00.000+00:00",
                },
            ),
            _command(
                "create_plan",
                schedule={
                    **valid_schedule,
                    "activateAt": "2026-10-10T10:00:00.000000Z",
                },
            ),
            _command(
                "create_plan",
                schedule={
                    **valid_schedule,
                    "activateAt": "1969-12-31T23:59:59.999Z",
                },
            ),
        )

        for body in cases:
            with self.subTest(body=body):
                with self.assertRaises(InvalidRuleMutation):
                    parse_rule_mutation(_BINDING_ID, body)
