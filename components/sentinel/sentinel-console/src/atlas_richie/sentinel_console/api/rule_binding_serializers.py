"""Wire projection for safe, query-bound rule binding directory pages."""

from __future__ import annotations

from ..domain.rule_bindings import RuleBinding, RuleBindingPage


def rule_binding_page_body(page: RuleBindingPage) -> dict[str, object]:
    """Serialize the exact query, filtered total, and redacted binding facts."""
    query = page.query
    return {
        "query": {
            "environmentId": query.environment_id,
            "appId": query.app_id,
            "kind": query.kind.value if query.kind is not None else None,
            "search": query.search,
            "page": query.page,
            "pageSize": query.page_size,
        },
        "total": page.total,
        "items": [_rule_binding_body(item) for item in page.items],
    }


def rule_binding_body(binding: RuleBinding) -> dict[str, object]:
    """Serialize one safe binding fact for a create response."""
    return _rule_binding_body(binding)


def _rule_binding_body(binding: RuleBinding) -> dict[str, object]:
    return {
        "id": binding.id,
        "environmentId": binding.environment_id,
        "appId": binding.app_id,
        "kind": binding.kind.value,
        "profile": binding.profile,
        "sourceId": binding.source_id,
        "sourceLabel": binding.source_label,
        "location": binding.location,
    }

