"""Safe API 0.9 serialization for provider-observed binding states."""

from __future__ import annotations

from ..domain.rule_catalog import RuleBindingObservedStateItem, RuleBindingStatesPage
from .rule_binding_serializers import _rule_binding_body
from .system_observation_access import utc_timestamp


def rule_binding_states_page_body(page: RuleBindingStatesPage) -> dict[str, object]:
    """Serialize typed binding states without provider payloads or credentials."""
    query = page.query
    return {
        "query": {
            "environmentId": query.environment_id,
            "appId": query.app_id,
            "kind": query.kind.value if query.kind is not None else None,
            "page": query.page,
            "pageSize": query.page_size,
        },
        "asOf": utc_timestamp(page.as_of),
        "coverage": page.coverage.value,
        "total": page.total,
        "hasMore": page.has_more,
        "items": [_item_body(item) for item in page.items],
    }


def _item_body(item: RuleBindingObservedStateItem) -> dict[str, object]:
    return {
        "binding": _rule_binding_body(item.binding),
        "state": item.state.value,
        "ruleCount": item.rule_count,
        "sourceRevision": item.source_revision,
        "lastAttemptAt": utc_timestamp(item.last_attempt_at) if item.last_attempt_at else None,
        "freshness": item.freshness.value,
        "hasLastKnownGood": item.has_last_known_good,
    }


__all__ = ["rule_binding_states_page_body"]
