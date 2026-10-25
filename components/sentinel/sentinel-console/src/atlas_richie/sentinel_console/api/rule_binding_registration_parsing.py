"""Strict request parser for creating a rule binding and provider target."""

from __future__ import annotations

import re

from ..application.rule_binding_ports import RegisterRuleBinding
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_bindings import RuleKind
from ..domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
)
from ..domain.wire_strings import is_bounded_wire_identifier

_REQUEST_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_NACOS_TARGET_FIELDS = frozenset({"provider", "namespace", "group", "dataId"})
_CONSUL_TARGET_FIELDS = frozenset({"provider", "datacenter", "key"})
_COMMAND_FIELDS = frozenset(
    {
        "requestKey",
        "bindingId",
        "environmentId",
        "appId",
        "kind",
        "profile",
        "sourceId",
        "sourceRevision",
        "target",
    }
)


def parse_rule_binding_registration(value: object) -> RegisterRuleBinding:
    """Parse only the finite provider-target shape; reject extra fields."""
    if not isinstance(value, dict) or set(value) != _COMMAND_FIELDS:
        raise ValueError("rule binding registration shape is invalid")
    request_key = value["requestKey"]
    binding_id = value["bindingId"]
    environment_id = value["environmentId"]
    app_id = value["appId"]
    profile = value["profile"]
    source_id = value["sourceId"]
    source_revision = value["sourceRevision"]
    if (
        not isinstance(request_key, str)
        or _REQUEST_KEY.fullmatch(request_key) is None
        or not all(
            is_bounded_wire_identifier(item, 200)
            for item in (binding_id, environment_id, app_id, profile, source_id, source_revision)
        )
    ):
        raise ValueError("rule binding registration identity is invalid")
    try:
        kind = RuleKind(value["kind"])
        target_data = value["target"]
        if not isinstance(target_data, dict):
            raise ValueError("provider target must be an object")
        provider = target_data.get("provider")
        if provider == ConfigurationSourceProvider.NACOS.value:
            if set(target_data) != _NACOS_TARGET_FIELDS:
                raise ValueError("Nacos target fields are invalid")
            target = NacosRulePublicationTarget(
                binding_id=binding_id,
                source_id=source_id,
                namespace=target_data["namespace"],
                group=target_data["group"],
                data_id=target_data["dataId"],
            )
        elif provider == ConfigurationSourceProvider.CONSUL.value:
            if set(target_data) != _CONSUL_TARGET_FIELDS:
                raise ValueError("Consul target fields are invalid")
            target = ConsulRulePublicationTarget(
                binding_id=binding_id,
                source_id=source_id,
                datacenter=target_data["datacenter"],
                key=target_data["key"],
            )
        else:
            raise ValueError("provider is unsupported")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("rule binding registration values are invalid") from error
    return RegisterRuleBinding(
        request_key=request_key,
        binding_id=binding_id,
        environment_id=environment_id,
        app_id=app_id,
        kind=kind,
        profile=profile,
        source_revision=source_revision,
        target=target,
    )


__all__ = ["parse_rule_binding_registration"]
