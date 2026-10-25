"""Safe serialization of historical process-epoch rule-load observations."""

from __future__ import annotations

from ..domain.rule_load_observation_history import RuleLoadObservationHistoryPage
from .rule_load_observation_serializers import _item_body
from .system_observation_access import utc_timestamp


def rule_load_history_page_body(page: RuleLoadObservationHistoryPage) -> dict[str, object]:
    query = page.query
    return {
        "query": {
            "environmentId": query.environment_id,
            "appId": query.app_id,
            "bindingId": query.binding_id,
            "instanceId": query.instance_id,
            "page": query.page,
            "pageSize": query.page_size,
        },
        "asOf": utc_timestamp(page.as_of),
        "coverage": page.coverage.value,
        "total": page.total,
        "hasMore": page.has_more,
        "items": [
            {
                "observationId": item.observation_id,
                "epochStatus": item.epoch_status.value,
                "observation": _item_body(item.observation),
            }
            for item in page.items
        ],
    }


__all__ = ["rule_load_history_page_body"]
