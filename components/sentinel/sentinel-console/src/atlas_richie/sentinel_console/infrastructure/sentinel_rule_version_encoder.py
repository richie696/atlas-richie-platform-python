"""Encode one Console rule version as a native same-kind Sentinel JSON array."""

from __future__ import annotations

import json

from ..application.rule_publication_ports import (
    RulePublicationProfileUnsupported,
    RulePublicationValueUnsupported,
)
from ..application.rule_value_projection import rule_value_fields
from ..domain.rule_snapshots import DegradeGrade, DegradeRuleValue, FlowRuleValue
from ..domain.rule_versions import RuleSetVersion


class SentinelRuleVersionJsonEncoder:
    """Project typed Console values into the configured native Sentinel profile.

    Console record IDs and API discriminators are management metadata, so only
    the rule value object is included in the provider-facing array.
    """

    def __init__(self, profile_id: str) -> None:
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("Sentinel rule encoder profile identity is invalid")
        self._profile_id = profile_id

    def encode_rule_version(self, version: RuleSetVersion) -> bytes:
        """Return compact UTF-8 JSON preserving the immutable version order."""
        if not isinstance(version, RuleSetVersion):
            raise ValueError("Sentinel rule encoder version is invalid")
        if version.profile != self._profile_id:
            raise RulePublicationProfileUnsupported(
                "rule version profile is not supported by this encoder"
            )

        try:
            values = []
            for record in version.records:
                _validate_profile_semantics(record.rule)
                values.append(rule_value_fields(record.rule))
            return json.dumps(
                values,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except RulePublicationValueUnsupported:
            raise
        except (TypeError, ValueError):
            raise RulePublicationValueUnsupported(
                "rule version contains a value outside the supported profile"
            ) from None


def _validate_profile_semantics(rule: object) -> None:
    """Reject populated fields whose conditions make them inactive on wire."""
    if isinstance(rule, FlowRuleValue):
        if not rule.cluster_mode and rule.cluster_config is not None:
            raise RulePublicationValueUnsupported(
                "disabled cluster flow rule cannot carry cluster configuration"
            )
    elif isinstance(rule, DegradeRuleValue):
        if (
            rule.slow_ratio_threshold is not None
            and rule.grade is not DegradeGrade.SLOW_REQUEST_RATIO
        ):
            raise RulePublicationValueUnsupported(
                "slow ratio threshold requires the slow request ratio grade"
            )


__all__ = ["SentinelRuleVersionJsonEncoder"]
