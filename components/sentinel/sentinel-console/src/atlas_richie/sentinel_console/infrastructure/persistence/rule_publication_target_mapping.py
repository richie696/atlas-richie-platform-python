"""Strict persistence mapping for provider-specific publication targets."""

from __future__ import annotations

from ...domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    RulePublicationTarget,
)

_NACOS_FIELDS = frozenset(
    {
        "schemaVersion",
        "provider",
        "bindingId",
        "sourceId",
        "namespace",
        "group",
        "dataId",
    }
)
_CONSUL_FIELDS = frozenset(
    {
        "schemaVersion",
        "provider",
        "bindingId",
        "sourceId",
        "datacenter",
        "key",
    }
)


def target_body(target: RulePublicationTarget) -> dict[str, object]:
    """Serialize one exact mapping using an explicit finite provider schema."""
    if isinstance(target, NacosRulePublicationTarget):
        return {
            "schemaVersion": 1,
            "provider": "nacos",
            "bindingId": target.binding_id,
            "sourceId": target.source_id,
            "namespace": target.namespace,
            "group": target.group,
            "dataId": target.data_id,
        }
    if isinstance(target, ConsulRulePublicationTarget):
        return {
            "schemaVersion": 1,
            "provider": "consul",
            "bindingId": target.binding_id,
            "sourceId": target.source_id,
            "datacenter": target.datacenter,
            "key": target.key,
        }
    raise ValueError("rule publication target provider is unsupported")


def target_location(target: RulePublicationTarget) -> str:
    """Return the credential-free UI location for one exact provider target."""
    if isinstance(target, NacosRulePublicationTarget):
        return f"nacos://{target.namespace}/{target.group}/{target.data_id}"
    if isinstance(target, ConsulRulePublicationTarget):
        datacenter = f"{target.datacenter}/" if target.datacenter else ""
        return f"consul://{datacenter}{target.key}"
    raise ValueError("rule publication target provider is unsupported")


def target_from_body(value: object) -> RulePublicationTarget:
    """Decode only the exact finite target fields, rejecting schema drift."""
    if not isinstance(value, dict):
        raise ValueError("rule publication target body must be an object")
    provider = value.get("provider")
    expected_fields = {
        "nacos": _NACOS_FIELDS,
        "consul": _CONSUL_FIELDS,
    }.get(provider)
    if (
        expected_fields is None
        or set(value) != expected_fields
        or type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] != 1
    ):
        raise ValueError("rule publication target schema is invalid")
    if provider == "nacos":
        return NacosRulePublicationTarget(
            binding_id=_required_string(value, "bindingId"),
            source_id=_required_string(value, "sourceId"),
            namespace=_required_string(value, "namespace"),
            group=_required_string(value, "group"),
            data_id=_required_string(value, "dataId"),
        )
    datacenter = value["datacenter"]
    if datacenter is not None and not isinstance(datacenter, str):
        raise ValueError("Consul publication target datacenter is invalid")
    return ConsulRulePublicationTarget(
        binding_id=_required_string(value, "bindingId"),
        source_id=_required_string(value, "sourceId"),
        datacenter=datacenter,
        key=_required_string(value, "key"),
    )


def _required_string(value: dict[str, object], field: str) -> str:
    result = value[field]
    if not isinstance(result, str):
        raise ValueError("rule publication target identity is invalid")
    return result
